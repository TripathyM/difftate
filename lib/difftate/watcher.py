"""The watcher: one per review. Starts or reuses diffity, serves the review API,
and dispatches waiting threads to the agent until Ctrl+C.

Same options and terminal output as difftate-watch.sh.
"""
import os
import shutil
import signal
import subprocess
import sys

from . import diffity, viewer
from .agent import AGENTS
from .api import ReviewApi, running_watcher
from .dispatch import Dispatch

USAGE = """difftate-watch.py — Start diffity and poll for comments, dispatching to an AI coding session.
(Normally run via the difftate / dtc / dto shell functions, with DT_WATCHER=python.)

Usage:
  difftate-watch.py --ref <git-ref> --tool <claude|opencode> [options]

Required:
  --ref <ref>            Git ref for diffity (master, HEAD~3, branch-name)
  --tool <tool>          AI tool to dispatch to (claude, opencode)

Optional:
  --session <id>         Resume an existing session (full conversation context)
  --cwd <path>           Repo path for headless mode (default: current directory)
  --interval <seconds>   Polling interval in seconds (default: 1)
  --cmd <binary>         Override the CLI binary or shell alias (e.g. a wrapper around claude)
  --model <model>        Model for the agent (default: Claude with --session matches the
                         session's latest interactive model)
  --open <where>         browser, herdr or both (default: $DT_OPEN, else browser).
                         herdr opens a Review tab in the Herdr app, or switches to it;
                         if Herdr can't be reached it falls back to the browser
  --help                 Show this help

Examples:
  # Claude Code — headless (no session context)
  difftate-watch.py --ref master --tool claude --interval 1

  # Claude Code — resume mode (full session context)
  difftate-watch.py --ref master --tool claude --session <full-uuid> --interval 1

  # OpenCode — headless
  difftate-watch.py --ref master --tool opencode --interval 1

  # OpenCode — resume mode
  difftate-watch.py --ref master --tool opencode --session <session-id> --interval 1"""

FLAGS = {"--ref": "ref", "--tool": "tool", "--session": "session", "--model": "model", "--cwd": "cwd",
         "--interval": "interval", "--cmd": "cmd", "--open": "open"}


class Exit(Exception):
    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


def parse(argv):
    opts = {"ref": "", "tool": "", "session": "", "model": "", "cwd": "", "interval": "1", "cmd": "",
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
    if not opts["ref"]:
        raise Exit(1, "Error: --ref is required")
    if not opts["tool"]:
        raise Exit(1, "Error: --tool is required")
    opts["cwd"] = opts["cwd"] or os.getcwd()
    if opts["open"] not in viewer.OPEN_IN:
        raise Exit(1, f"Error: --open (or DT_OPEN) must be browser, herdr or both, not '{opts['open']}'")
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
        agent_cls = AGENTS[o["tool"]]
        cmd = resolve_cmd(o["cmd"] or agent_cls.default_cmd)
        self.agent = agent_cls(cmd, o["session"], o["model"])
        if o["session"] and not self.agent.session_exists():
            raise Exit(1, "\n".join([
                f"Error: session '{o['session']}' not found for {o['tool']}.",
                f"  Make sure the {o['tool']} session is running in this project directory ({o['cwd']}).",
                "  Available sessions:", *self.agent.list_sessions()]))
        self.folder, self.root = review_folder(o["cwd"])
        other = running_watcher(self.folder)
        if other:
            raise Exit(1, f"Error: a watcher is already running for this repository (pid {other}). "
                          "Stop it first, or use its review.")

    def start(self):
        o = self.opts
        try:
            self.diffity = diffity.launch(o["ref"], o["cwd"])
        except diffity.DiffityStartError as e:
            raise Exit(1, str(e))
        store = self.diffity.store()
        self.api = ReviewApi(store, self.folder, self.root)
        self.api.start()

        url = self.diffity.viewer_url(o["ref"])
        print(f"  → {url}")
        viewer.open_review(o["open"], url, self.root)
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
        self.dispatch = Dispatch(store, self.agent, o["cwd"], o["interval"], self.api.address(),
                                 self.diffity.problem)

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
