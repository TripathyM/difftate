"""The watcher: one per repository. It opens the review of the checked-out
branch, serves the review API, and runs the loop every --interval until
Ctrl+C. It follows the checked-out branch: between runs, it moves to that
branch's review (started if new), and back again.

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


class Watcher:
    def __init__(self, opts, wiring):
        self.opts = opts
        self.wiring = wiring
        self.api = None
        self.loop = None
        self.reviews = {}  # branch: its review, once opened
        self.branch = None  # the branch whose review the watcher shows
        self.unreadable_branch = None  # whose review couldn't be read (warned once)

    def setup(self):
        o, w = self.opts, self.wiring
        found = w.difftate_folder(o["cwd"])
        if found is None:
            raise Exit(1, f"Error: {o['cwd']} is not a git repository")
        self.folder, self.root = found
        self.lock = one_watcher.claim(self.folder, o["ref"], o["open"], w.running_watcher, w.ask_running_watcher)
        try:
            self.agent = w.coding_agent(o["tool"], o["cmd"], o["session"], o["model"], o["cwd"], self.folder)
        except CouldNotStart as e:
            raise Exit(1, f"Error: {e}")
        if o["session"] and not self.agent.session_exists():
            raise Exit(1, "\n".join([
                f"Error: session '{o['session']}' not found for {o['tool']}.",
                f"  Make sure the {o['tool']} session is running in this project directory ({o['cwd']}).",
                "  Available sessions:", *self.agent.list_sessions()]))

    def start(self):
        o, w = self.opts, self.wiring
        try:
            self.base = w.base(o["cwd"], o["base"])
            view = w.need_view(o["cwd"], o["ref"])
        except NotFound as e:
            raise Exit(1, f"Error: {e}")
        self.branch = w.review_branch(o["cwd"], self.base)
        if not self.branch:
            raise Exit(1, "Error: the repository has no commit yet")
        print(self.banner(self.branch, view))
        try:
            review = self.open_review(self.branch)
        except (CouldNotRead, OSError) as e:
            raise Exit(1, f"Error: could not read the review ({e})")
        self.api = w.review_api(review, self.folder, self.root, view,
                                lambda view: w.need_view(o["cwd"], view), self.view_shown)
        self.api.start()

        url = self.api.page_url()
        print(f"  → {url}")
        self.open_viewer(o["open"], url)
        print()
        print(f"Watching for comments every {o['interval']:g}s")
        print(f"  Tool: {o['tool']} (cmd: {self.agent.cmd})")
        if o["session"]:
            print(f"  Session: {o['session']} (resume mode)")
        else:
            print(f"  Headless mode (cwd: {o['cwd']})")
        print()
        print("Press Ctrl+C to stop")
        print()
        self.loop = w.loop(review, self.agent)
        try:
            self.loop.recover_runs(review)
        except CouldNotRead as e:
            raise Exit(1, f"Error: could not read the review ({e})")

    def forever(self):
        """The loop, every interval until Ctrl+C."""
        timer.every(self.opts["interval"], lambda: self.loop.poll(self.follow_branch))

    def open_viewer(self, where, url=None):
        """Open the review in the viewer (<where>: one of the viewers, or both),
        at <url> (default: a new link to difftate's own page, with a single-use
        launch code: it never carries the review token). Every viewer reads the
        review API."""
        viewers.open_review(self.wiring.viewers, where, url or self.api.page_url(), self.root)

    def view_shown(self, view, open_in):
        """A viewer, or another `difftate` call, switched the view."""
        print(f"[{now()}] Showing {view_name(view)}")
        if open_in:
            self.open_viewer(open_in)

    def open_review(self, branch):
        """The review of <branch> against the base: the one this watcher opened
        before, or the store's."""
        if branch not in self.reviews:
            self.reviews[branch] = self.wiring.open_review(self.folder, self.opts["cwd"], branch, self.base,
                                                           self.tampered)
        return self.reviews[branch]

    def follow_branch(self):
        """Between runs: when another branch is checked out, the watcher and its
        viewers move to that branch's review (started if new). A review the
        watcher opens now may have a run its watcher was killed during:
        recover_runs ends it."""
        branch = self.wiring.review_branch(self.opts["cwd"], self.base)
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
        self.loop.dispatch.review = review

    def banner(self, branch, view):
        return f"The review of {branch} against {self.base}, showing {view_name(view)}"

    def tampered(self, thread_ids):
        names = ", ".join(t[:8] for t in thread_ids) or "no thread named"
        print(f"[{now()}] Warning: the stored review was changed outside difftate ({names}): restored it")
        if self.loop:
            self.loop.dispatch.warn_tampered(thread_ids)

    def stop(self, say=True):
        """Stop the run, every process it started, and the API."""
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if say:
            print()
            print("Stopping watcher...")
        if self.loop:
            self.loop.stop(say)
        if self.api:
            self.api.stop()
        if say:
            print("Done.")
