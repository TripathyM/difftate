"""The watcher: one per checked-out folder of a repository (the repository
itself, or one of its worktrees). It opens the review of the branch checked out
there, serves the review API, and runs the loop every --interval until
Ctrl+C. It follows the checked-out branch: between runs, it moves to that
branch's review (started if new), and back again.

What it holds for a folder is one FolderEntry, in a table keyed by the folder's
top (Watcher.folders). Today the table has one entry.

It runs on what main.py wired (wiring.Wiring): it knows no store, git, coding
agent or HTTP of its own.
"""
import signal
import time

from ....core.changes.model import View
from ....core.dispatch.model import CouldNotStart
from ....core.review.model import CouldNotRead, NotFound
from . import one_watcher, timer, viewers
from .options import Exit


def now():
    return time.strftime("%H:%M:%S")


def view_name(view):
    """How the terminal names a view."""
    return View(view or "").name


class FolderEntry:
    """What the watcher holds for one checked-out folder: its reviews, the
    branch whose review it shows, the review API and Dispatch loop, and the
    view shown."""

    def __init__(self, wiring, cwd, folder, watcher_folder, root, base, tampered):
        self.wiring = wiring
        self.cwd = cwd  # the checked-out folder
        self.folder = folder  # its reviews' folder
        self.watcher_folder = watcher_folder  # its watcher's folder
        self.root = root  # its top
        self.base = base
        self.tampered = tampered  # called with the threads restored
        self.api = None
        self.loop = None
        self.reviews = {}  # branch: its review, once opened
        self.branch = None  # the branch whose review the entry shows
        self.unreadable_branch = None  # whose review couldn't be read (warned once)

    def open_review(self, branch):
        """The review of <branch> against the base: the one this entry opened
        before, or the store's."""
        if branch not in self.reviews:
            self.reviews[branch] = self.wiring.open_review(self.folder, self.cwd, branch, self.base,
                                                           self.tampered)
        return self.reviews[branch]

    def follow_branch(self):
        """Between runs: when another branch is checked out, the entry and its
        viewers move to that branch's review (started if new). A review opened
        now may have a run its watcher was killed during: recover_runs ends it."""
        branch = self.wiring.review_branch(self.cwd, self.base)
        if not branch or branch == self.branch:
            return  # no commit to stand in for the branch, or the same one: stay
        new = branch not in self.reviews
        try:
            review = self.open_review(branch)
            if new:
                self.loop.recover_runs(review)
        except (CouldNotRead, OSError) as e:
            if new:
                self.reviews.pop(branch, None)  # opened again, and recovered, on the next try
            if branch != self.unreadable_branch:
                print(f"[{now()}] Warning: could not read the review of {branch} ({e}): "
                      f"still showing the review of {self.branch}")
            self.unreadable_branch = branch
            return
        self.branch, self.unreadable_branch = branch, None
        shown = self.api.shown
        try:
            shown.check(shown.current())
            print(f"[{now()}] {self.banner(branch, shown.current())}")
        except NotFound:
            print(f"[{now()}] {self.banner(branch, shown.current())}: not on this branch")
            shown.switch("")
        self.api.switch_review(review)
        self.loop.switch_review(review)

    def banner(self, branch, view):
        return f"The review of {branch} against {self.base}, showing {view_name(view)}"

    def stop(self, say=True):
        """Stop the run, every process it started, and the API."""
        if self.loop:
            self.loop.stop(say)
        if self.api:
            self.api.stop()


class Watcher:
    def __init__(self, opts, wiring):
        self.opts = opts
        self.wiring = wiring
        self.folders = {}  # the folder's top: its FolderEntry

    @property
    def entry(self):
        """The one entry, until the watcher serves more folders."""
        return next(iter(self.folders.values()))

    def setup(self):
        o, w = self.opts, self.wiring
        found = w.difftate_folder(o["cwd"])
        if found is None:
            raise Exit(1, f"Error: {o['cwd']} is not a git repository")
        self.folder, self.watcher_folder, self.root = found  # the reviews', the watcher's, the top
        self.lock = one_watcher.claim(self.watcher_folder, o["ref"], o["open"], w.running_watcher,
                                      w.ask_running_watcher)
        try:
            self.coding_agent = w.coding_agent(o["tool"], o["cmd"], o["model"], o["cwd"], self.folder,
                                               self.watcher_folder)
        except CouldNotStart as e:
            raise Exit(1, f"Error: {e}")

    def start(self):
        o, w = self.opts, self.wiring
        try:
            base = w.base(o["cwd"], o["base"])
            view = w.need_view(o["cwd"], o["ref"])
        except NotFound as e:
            raise Exit(1, f"Error: {e}")
        entry = FolderEntry(w, o["cwd"], self.folder, self.watcher_folder, self.root, base, self.tampered)
        self.folders[self.root] = entry
        entry.branch = w.review_branch(o["cwd"], base)
        if not entry.branch:
            raise Exit(1, "Error: the repository has no commit yet")
        print(entry.banner(entry.branch, view))
        try:
            review = entry.open_review(entry.branch)
        except (CouldNotRead, OSError) as e:
            raise Exit(1, f"Error: could not read the review ({e})")
        entry.api = w.review_api(review, self.watcher_folder, self.root, view,
                                 lambda view: w.need_view(o["cwd"], view), self.view_shown)
        entry.api.start()

        url = entry.api.page_url()
        print(f"  → {url}")
        self.open_viewer(o["open"], url)
        print()
        print(f"Watching for comments every {o['interval']:g}s")
        print(f"  Coding agent: {o['tool']} (cmd: {self.coding_agent.cmd})")
        print(f"  In {o['cwd']}: each run starts a fresh agent session")
        print()
        print("Press Ctrl+C to stop")
        print()
        entry.loop = w.loop(review, self.coding_agent)
        try:
            entry.loop.recover_runs(review)
        except CouldNotRead as e:
            raise Exit(1, f"Error: could not read the review ({e})")

    def forever(self):
        """The loop, every interval until Ctrl+C."""
        entry = self.entry
        timer.every(self.opts["interval"], lambda: entry.loop.poll(entry.follow_branch))

    def open_viewer(self, where, url=None):
        """Open the review in the viewer (<where>: one of the viewers, or both),
        at <url> (default: a new link to difftate's own page, with a single-use
        launch code: it never carries the review token). Every viewer reads the
        review API."""
        entry = self.entry
        viewers.open_review(self.wiring.viewers, where, url or entry.api.page_url(), entry.root)

    def view_shown(self, view, open_in):
        """A viewer, or another `difftate` call, switched the view."""
        print(f"[{now()}] Showing {view_name(view)}")
        if open_in:
            self.open_viewer(open_in)

    def tampered(self, thread_ids):
        names = ", ".join(t[:8] for t in thread_ids) or "no thread named"
        print(f"[{now()}] Warning: the stored review was changed outside difftate ({names}): restored it")
        for entry in self.folders.values():
            if entry.loop:
                entry.loop.warn_tampered(thread_ids)

    def stop(self, say=True):
        """Stop every entry's run, every process it started, and its API."""
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if say:
            print()
            print("Stopping watcher...")
        for entry in self.folders.values():
            entry.stop(say)
        if say:
            print("Done.")
