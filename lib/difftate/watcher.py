"""The watcher: one per review. Opens the review in its store (diffity, started or
reused; or difftate's own local store with DT_STORE=local), serves the review
API, and dispatches waiting threads to the coding agent until Ctrl+C.

The difftate / dtc / dto shell functions start it (difftate.zsh).
"""
import fcntl
import os
import shutil
import signal
import subprocess
import sys
import time

from . import changes, diffity, viewer
from .agent import AGENTS
from .api import ReviewApi, ShownView, ask_running_watcher, running_watcher
from .dispatch import Dispatch, now
from .local import LocalStore
from .review import Review
from .store import StoreError

STORES = ("diffity", "local")
# How long a second watcher waits for one that is starting (diffity can take a while)
STARTING_S = 60

USAGE = """difftate-watch.py — Open the review and poll for comments, dispatching them to the coding agent.
(Normally run via the difftate / dtc / dto shell functions.)

Usage:
  difftate-watch.py --tool <claude|opencode> [options]

Required:
  --tool <tool>          AI tool to dispatch to (claude, opencode)

Optional:
  --base <branch>        The branch the review compares against (default: the repository's
                         default branch, origin/HEAD; else main or master)
  --ref <view>           The starting view of the review (default: all changes). HEAD~2: the
                         commits after it; HEAD: uncommitted; staged; unstaged. Viewers
                         switch views; with diffity, its viewer stays on this one
  --session <id>         Resume an existing session (full conversation context)
  --cwd <path>           Repo path for headless mode (default: current directory)
  --interval <seconds>   Polling interval in seconds (default: 1)
  --cmd <binary>         Override the CLI binary or shell alias (e.g. a wrapper around claude)
  --model <model>        Model for the coding agent (default: Claude with --session matches the
                         session's latest interactive model)
  --open <where>         browser, herdr or both (default: $DT_OPEN, else browser).
                         herdr opens a Review tab in the Herdr app, or switches to it;
                         if Herdr can't be reached it falls back to the browser
  --help                 Show this help

Environment:
  DT_STORE               diffity (default) or local: difftate's own store, in the
                         repository's git folder, with no diffity

Examples:
  # Claude Code — headless (no session context)
  difftate-watch.py --tool claude --interval 1

  # Claude Code — resume mode (full session context), against the develop branch
  difftate-watch.py --base develop --tool claude --session <full-uuid> --interval 1

  # OpenCode — headless, the last 3 commits
  difftate-watch.py --ref HEAD~3 --tool opencode --interval 1

  # OpenCode — resume mode
  difftate-watch.py --tool opencode --session <session-id> --interval 1"""

FLAGS = {"--ref": "ref", "--base": "base", "--tool": "tool", "--session": "session", "--model": "model", "--cwd": "cwd",
         "--interval": "interval", "--cmd": "cmd", "--open": "open"}


class Exit(Exception):
    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


def parse(argv):
    opts = {"ref": "", "base": "", "store": os.environ.get("DT_STORE") or "diffity", "tool": "", "session": "", "model": "", "cwd": "", "interval": "1", "cmd": "",
            "open": os.environ.get("DT_OPEN") or "browser"}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            raise Exit(0, USAGE)
        if arg not in FLAGS or i + 1 >= len(argv):
            raise Exit(1, f"Unknown flag: {arg}\n{USAGE}" if arg not in FLAGS else f"Error: {arg} needs a value")
        opts[FLAGS[arg]] = argv[i + 1]
        i += 2
    if not opts["tool"]:
        raise Exit(1, "Error: --tool is required")
    opts["cwd"] = opts["cwd"] or os.getcwd()
    if opts["open"] not in viewer.OPEN_IN:
        raise Exit(1, f"Error: --open (or DT_OPEN) must be browser, herdr or both, not '{opts['open']}'")
    if opts["store"] not in STORES:
        raise Exit(1, f"Error: DT_STORE must be diffity or local, not '{opts['store']}'")
    if opts["tool"] not in AGENTS:
        raise Exit(1, f"Error: unsupported tool '{opts['tool']}'. Supported: {' '.join(AGENTS)}")
    try:
        opts["interval"] = float(opts["interval"])
    except ValueError:
        raise Exit(1, f"Error: --interval must be a number of seconds, not '{opts['interval']}'")
    return opts


def resolve_cmd(cmd):
    """The command's path, following a zsh alias when it isn't on PATH."""
    if shutil.which(cmd):
        return cmd
    try:
        raw = subprocess.run(["zsh", "-ic", f"which {cmd}"], capture_output=True, text=True).stdout
    except OSError:
        raw = ""
    lines = raw.strip().split("\n")
    raw = lines[-1] if lines else ""
    if "aliased to " in raw:
        resolved = raw.split("aliased to ", 1)[1]
    elif raw.startswith("/"):
        resolved = raw
    else:
        resolved = ""
    if resolved and os.access(resolved, os.X_OK):
        return resolved
    raise Exit(1, f"Error: command '{cmd}' not found (not in PATH, not a shell alias)")


def review_folder(cwd):
    """The repository's difftate folder: inside its git folder (shared by
    worktrees, never committed)."""
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if r.returncode != 0:
        raise Exit(1, f"Error: {cwd} is not a git repository")
    top = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    git_dir = os.path.join(cwd, r.stdout.strip())
    return os.path.realpath(os.path.join(git_dir, "difftate")), os.path.realpath(top.stdout.strip() or cwd)


class Hangup(BaseException):
    """The terminal closed: stop everything, quietly (there's no one to print to)."""


def _terminate(signum, frame):
    raise KeyboardInterrupt


def _hangup(signum, frame):
    raise Hangup


class Watcher:
    def __init__(self, opts):
        self.opts = opts
        self.diffity = None
        self.api = None
        self.dispatch = None

    def setup(self):
        o = self.opts
        self.folder, self.root = review_folder(o["cwd"])
        self.claim()
        agent_cls = AGENTS[o["tool"]]
        cmd = resolve_cmd(o["cmd"] or agent_cls.default_cmd)
        self.agent = agent_cls(cmd, o["session"], o["model"])
        if o["session"] and not self.agent.session_exists():
            raise Exit(1, "\n".join([
                f"Error: session '{o['session']}' not found for {o['tool']}.",
                f"  Make sure the {o['tool']} session is running in this project directory ({o['cwd']}).",
                "  Available sessions:", *self.agent.list_sessions()]))

    def claim(self):
        """Become this repository's watcher: hold the lock file in its difftate folder
        until exit. When another watcher holds it, ask that one to show the view
        asked for (once it serves the review API), and exit."""
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(self.folder, "watcher.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.time() + STARTING_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.lock = fd  # held until the process exits
                other = running_watcher(self.folder)  # one from before the lock file
                if other:
                    self.switch_running(other)
                return
            except BlockingIOError:
                pass
            other = running_watcher(self.folder)
            if other:
                self.switch_running(other)
            if time.time() > deadline:
                os.close(fd)
                raise Exit(1, "Error: another watcher is starting for this repository, and it didn't serve "
                              f"the review within {STARTING_S}s")
            time.sleep(0.1)

    def switch_running(self, pid):
        o = self.opts
        try:
            status, answer = ask_running_watcher(self.folder, "PUT", "/api/view", {"view": o["ref"], "open": o["open"]})
        except (OSError, ValueError, KeyError) as e:
            raise Exit(1, f"Error: difftate is already running for this repository (pid {pid}), "
                          f"but it didn't answer ({e})")
        if status != 200:
            raise Exit(1, f"Error: {(answer or {}).get('error') or status}")
        raise Exit(0, f"difftate is already running for this repository (pid {pid}): "
                      f"switched it to {changes.view_name(answer['view'])}")

    def start(self):
        o = self.opts
        try:
            base = changes.resolve_base(o["cwd"], o["base"])
        except changes.ChangesError as e:
            # diffity shown an explicit --ref needs no base (as before the local store)
            if o["store"] == "local" or o["base"] or not o["ref"]:
                raise Exit(1, str(e))
            base = None
        try:
            self.view = changes.need_view(o["cwd"], o["ref"])
        except changes.ChangesError as e:
            raise Exit(1, f"Error: {e}")
        code = None
        if o["store"] == "local":
            store, problem = self.local_store(base), lambda: None
            code = changes.Code(o["cwd"], base, store.info["branch"])
        else:
            try:
                self.diffity = diffity.launch(o["ref"] or base, o["cwd"])
            except diffity.DiffityStartError as e:
                raise Exit(1, str(e))
            store, problem = self.diffity.store(), self.diffity.problem
        diff_hashes = None if base is None else lambda: changes.diff_hashes(changes.changeset(o["cwd"], base)["diff"])
        review = Review(store, code, diff_hashes)
        try:
            interrupted = review.recover_runs()
        except StoreError as e:
            raise Exit(1, f"Error: could not read the review ({e})")
        shown = ShownView(self.view, lambda view: changes.need_view(o["cwd"], view), self.view_shown)
        self.api = ReviewApi(review, self.folder, self.root, lambda view: changes.changeset(o["cwd"], base, view), shown)
        self.api.start()

        self.base = base
        url = self.viewer_url()
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
        self.dispatch = Dispatch(review, self.agent, o["cwd"], self.folder, o["interval"],
                                 self.api.address(), problem)
        self.dispatch.close_interrupted(interrupted)

    def viewer_url(self):
        """The browser viewer's link: diffity's, or difftate's own page with a new
        single-use launch code (it never carries the review token)."""
        return self.diffity.viewer_url(self.opts["ref"] or self.base) if self.diffity else self.api.page_url()

    def open_viewer(self, where, url=None):
        """Open the review in the viewer (<where>: browser, herdr or both), at <url>
        (default: a new link). Viewers show the API's view; diffity's browser viewer
        shows only its own ref. Without diffity, both read the review API."""
        viewer.open_review(where, url or self.viewer_url(), self.root)

    def view_shown(self, view, open_in):
        """A viewer, or another `difftate` call, switched the view."""
        print(f"[{now()}] Showing {changes.view_name(view)}")
        if self.diffity and view != self.view:
            print("  (diffity's browser viewer stays on its own view: DT_STORE=local has views)")
        if open_in:
            self.open_viewer(open_in)

    def local_store(self, base):
        o = self.opts
        try:
            branch = changes.review_branch(o["cwd"], base)
        except changes.ChangesError as e:
            raise Exit(1, str(e))
        print(f"Local store: the review of {branch} against {base}, showing {changes.view_name(self.view)}")
        return LocalStore.open(self.folder, o["cwd"], branch, base, on_tamper=self.tampered)

    def tampered(self, thread_ids):
        names = ", ".join(t[:8] for t in thread_ids) or "no thread named"
        print(f"[{now()}] Warning: the stored review was changed outside difftate ({names}): restored it")
        if self.dispatch:
            self.dispatch.warn_tampered(thread_ids)

    def stop(self, say=True):
        """Stop the run, every process it started, diffity (when started here) and the API."""
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if say:
            print()
            print("Stopping watcher...")
        if self.dispatch:
            self.dispatch.stop_run(say)
        if self.diffity:
            self.diffity.stop(say)
        if self.api:
            self.api.stop()
        if say:
            print("Done.")


def main(argv):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _hangup)
    watcher = None
    try:
        opts = parse(argv)
        watcher = Watcher(opts)
        watcher.setup()
        watcher.start()
        problem = watcher.dispatch.forever()
        print(problem)
        watcher.stop(say=False)
        return 1
    except Exit as e:
        if e.message:
            print(e.message)
        if watcher:
            watcher.stop(say=False)
        return e.code
    except KeyboardInterrupt:
        if watcher:
            watcher.stop()
        else:
            print()
        return 0
    except Hangup:
        if watcher:
            watcher.stop(say=False)
        return 129
    except BaseException:
        if watcher:
            watcher.stop(say=False)
        raise
