"""The watcher: one for the machine (ADR 0008). It serves the review API on one
port with one token, and holds a table of the checked-out folders it serves
(Watcher.folders, one FolderEntry for each, keyed by the folder's top): a
folder is added on the first request that names it. An entry opens the review
of the branch checked out in its folder, and runs its own loop every
interval, on a thread of its own, so runs of different reviews can overlap
(one review has one run at a time). It follows the checked-out branch:
between runs, it moves to that branch's review (started if new), and back
again.

It runs on what main.py wired (wiring.Wiring): it knows no store, git, coding
agent or HTTP of its own. It runs in the background: what it says goes to its
log, each line saying which folder and review it is about.
"""
import os
import signal
import threading
import time
import traceback

from ....core.changes.model import View
from ....core.review.model import CouldNotRead, NotFound
from .options import Exit


def now():
    return time.strftime("%H:%M:%S")


def view_name(view):
    """How the log names a view."""
    return View(view or "").name


class FolderEntry:
    """What the watcher holds for one checked-out folder: its reviews, the
    branch whose review it shows, the view shown, and its Dispatch loop."""

    def __init__(self, wiring, found, base, agent, on_tamper):
        self.wiring = wiring
        self.root = found.root  # the checked-out folder's top: where its runs work
        self.folder = found.reviews  # its reviews' folder
        self.base = base
        self.agent = agent
        self.on_tamper = on_tamper  # called with this entry and the threads restored
        self.lock = threading.RLock()  # one thing at a time on the entry: a poll, a switch, a stop
        self.shown = None  # the view viewers show (a ShownView)
        self.review = None  # the review it serves now
        self.loop = None
        self.reviews = {}  # (branch, base): its review, once opened
        self.branch = None  # the branch whose review the entry shows
        self.key = None  # (branch, base) of the review shown
        self.wanted_base = None  # a base asked for while a run held the review: shown once it ends
        self.unreadable = None  # (branch, base) whose review couldn't be read (warned once)
        self.thread = None

    def label(self):
        """What a line of the log about this entry starts with."""
        return f"{self.root} ({self.branch or 'starting'})"

    def open_review(self, branch, base):
        """The review of <branch> against <base>: the one this entry opened
        before, or the store's."""
        key = (branch, base)
        if key not in self.reviews:
            self.reviews[key] = self.wiring.open_review(self.folder, self.root, branch, base,
                                                        lambda thread_ids: self.on_tamper(self, thread_ids))
        return self.reviews[key]

    def start(self, view):
        """Open the review of the checked-out branch, showing <view>, and start the loop.
        Raises the core's NotFound, or CouldNotRead."""
        w = self.wiring
        self.branch = w.review_branch(self.root, self.base)
        if not self.branch:
            raise NotFound("the repository has no commit yet")
        self.key = (self.branch, self.base)
        try:
            self.review = self.open_review(*self.key)
        except OSError as e:
            raise CouldNotRead(f"could not read the review ({e})") from e
        self.shown = self.wiring.shown_view(view, lambda given: w.need_view(self.root, given), self.view_shown)
        print(self.banner(self.branch, view))
        self.loop = w.loop(self.review, self.agent)
        self.loop.recover_runs(self.review)

    def follow_branch(self):
        """Between runs: when another branch is checked out (or another base was
        asked for), the entry and its viewers move to that review (started if
        new). A review opened now may have a run its watcher was killed during:
        recover_runs ends it."""
        base = self.wanted_base or self.base
        branch = self.wiring.review_branch(self.root, base)
        key = (branch, base)
        if not branch or key == self.key:
            return  # no commit to stand in for the branch, or the same one: stay
        new = key not in self.reviews
        try:
            review = self.open_review(branch, base)
            if new:
                self.loop.recover_runs(review)
        except (CouldNotRead, OSError) as e:
            if new:
                self.reviews.pop(key, None)  # opened again, and recovered, on the next try
            if key != self.unreadable:
                print(f"[{now()}] Warning: could not read the review of {branch} against {base} ({e}): "
                      f"still showing the review of {self.branch} against {self.base}")
            self.unreadable = key
            return
        self.branch, self.base, self.key, self.wanted_base, self.unreadable = branch, base, key, None, None
        shown = self.shown
        try:
            shown.check(shown.current())
            print(f"[{now()}] {self.banner(branch, shown.current())}")
        except NotFound:
            print(f"[{now()}] {self.banner(branch, shown.current())}: not on this branch")
            shown.switch("")
        self.review = review
        self.loop.switch_review(review)

    def use_base(self, given):
        """A request named a base: show the review against it. While a run holds
        the review, it is shown once the run ends. Raises the core's NotFound
        for a base that isn't one."""
        base = self.wiring.base(self.root, given)
        with self.lock:
            if base == (self.wanted_base or self.base):
                return
            self.wanted_base = base
            if not self.loop.busy():
                self.follow_branch()

    def banner(self, branch, view):
        return f"The review of {branch} against {self.base}, showing {view_name(view)}"

    def view_shown(self, view):
        """A viewer, or another `difftate` call, switched the view."""
        print(f"[{now()}] Showing {view_name(view)}")

    def run(self, interval, stopping, log):
        """The loop, every interval until the watcher stops."""
        if log:
            log.about(self.label)
        shown_error = None
        while not stopping.is_set():
            try:
                with self.lock:
                    if stopping.is_set():
                        break  # stop() has run this entry's run down: a new run would be nobody's
                    self.loop.poll(self.follow_branch)
                shown_error = None
            except Exception as e:  # one folder's trouble is not the others'
                if repr(e) != shown_error:
                    print(f"[{now()}] Error in the loop: {traceback.format_exc()}")
                shown_error = repr(e)
            stopping.wait(interval)

    def stop(self, say=True):
        """Stop the run and every process it started."""
        with self.lock:
            if self.loop:
                self.loop.stop(say)


class Watcher:
    def __init__(self, opts, wiring):
        self.opts = opts
        self.wiring = wiring
        self.folders = {}  # the folder's top: its FolderEntry
        self._tops = {}  # a path a request named: the top of the checked-out folder it is in
        self.stopping = threading.Event()
        self.api = None
        self.log = None
        self._adding = threading.Lock()

    def folder(self, path, base=""):
        """What the watcher serves for the checked-out folder <path> is in, with
        the review against <base> (the entry's base, or the repository's default
        branch for a new entry, when none is given): the first request that
        names a folder adds it. Raises the core's NotFound for a path that is
        in no checked-out folder, or a base that isn't one."""
        entry = self.folders.get(self._tops.get(path))
        if entry is not None and not os.path.isdir(entry.root):
            entry = None  # the folder is gone: ask git again (it refuses, or finds where it moved)
        if entry is None:  # git says which folder it is, once for each way a request spells it
            found = self.wiring.difftate_folder(path)
            if found is None:
                raise NotFound(f"{path} is not a checked-out folder of a git repository")
            with self._adding:
                entry = self.folders.get(found.root)
                if entry is None:
                    entry = self.add(found, base)
            self._tops[path] = found.root
        if base:
            entry.use_base(base)
        if self.log:
            self.log.about(entry.label)  # a request's thread: what it prints is about this folder
        return entry

    def add(self, found, base):
        """Serve the checked-out folder <found> (a DifftateFolders)."""
        entry = FolderEntry(self.wiring, found, self.wiring.base(found.root, base),
                            self.wiring.coding_agent(found.root, found.reviews), self.tampered)
        if self.log:
            self.log.about(entry.label)
        entry.start("")
        self.folders[found.root] = entry
        entry.thread = threading.Thread(target=entry.run, args=(self.opts["interval"], self.stopping, self.log),
                                        daemon=True)
        entry.thread.start()
        return entry

    def serve(self):
        """Serve the review API until something stops the watcher (stop())."""
        w = self.wiring
        self.api = w.review_api(self.folder, w.difftate_home, self.stopping.set)
        self.api.start()
        print(f"[{now()}] difftate watcher started (pid {os.getpid()}, port {self.api.server.server_address[1]})")
        print(f"  Who replies: the repository's agent, else the machine's default, from the agent list; polling every {self.opts['interval']:g}s")
        print("  Each run starts a fresh agent session, in the folder of the review it is for")
        while not self.stopping.wait(0.5):
            pass

    def tampered(self, entry, thread_ids):
        """The stored review of <entry> was changed outside difftate: say so in
        its log lines, and tell its run in progress. No other entry is told."""
        names = ", ".join(t[:8] for t in thread_ids) or "no thread named"
        print(f"[{now()}] Warning: the stored review was changed outside difftate ({names}): restored it")
        if entry.loop:
            entry.loop.warn_tampered(thread_ids)

    def stop(self, say=True):
        """Stop every entry's run and every process it started, then the API."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        self.stopping.set()
        if say:
            print(f"[{now()}] Stopping watcher...")
        for entry in list(self.folders.values()):
            entry.stop(say)
        for entry in list(self.folders.values()):
            if entry.thread:
                entry.thread.join(10)
        if self.api:
            self.api.stop()
        if say:
            print("Done.")
