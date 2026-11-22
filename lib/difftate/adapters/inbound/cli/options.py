"""The command line's options: the flags, the help, and the errors they give."""
import math
import os

USAGE = """difftate — Open the review of this folder, starting the watcher (once for the machine) if none runs.

Usage:
  difftate [<view>] [--base <branch>] [--open browser|nvim|both]
  difftate browser [<view>] [--base <branch>]   the same, opening the review in the browser
  difftate stop
  difftate restart
  difftate agent [<name>]
  difftate log
  difftate status [--json] [--branch <branch>] [--base <branch>] [--cwd <path>]

The watcher serves the review of every checked-out folder that a request names, in the
background, and dispatches waiting threads to the coding agent in that folder. `difftate` starts
it when none runs, adds this folder, opens its review, and ends. `difftate stop` stops it; `difftate restart` stops it and starts it again, serving the folders it served.
`difftate agent <name>` sets which listed agent replies in this repository; with no name it says which does.
`difftate log` shows its log (each line: the time, then the folder and branch it is about) and
follows new lines until Ctrl+C.

Options:
  <view>                 The view to show (default: leave it). HEAD~2: the commits after it;
                         HEAD: uncommitted; staged; unstaged. Viewers switch views
  --base <branch>        The branch the review compares against (default: the repository's
                         default branch, origin/HEAD; else main or master)
  --open <where>         browser, nvim or both (default: $DT_OPEN, else browser).
                         The viewer to open, not the host. nvim: the Neovim viewer: with a terminal,
                         nvim runs right there, in the repository (difftate ends and nvim takes its
                         place); without one, the command to run is printed (difftate opens no
                         host).
                         both: the browser first, then nvim.
  --cwd <path>           A folder of the repository (default: current directory)
  --help                 Show this help

Who replies is not an option: it is the repository's agent (`difftate agent <name>`), else the
machine's default, from the agent list in the difftate folder (agents.toml).

Each run starts a fresh agent session of the coding agent.

Where it keeps things: the difftate folder in your home (~/.difftate, or $DIFFTATE_HOME): the
watcher's port, pid and token, its log, and the review history."""

WATCHER_USAGE = """difftate-watch.py — The watcher: one for the machine, started in the background by `difftate`.

Usage:
  difftate-watch.py [--interval <seconds>]"""

FLAGS = {"--base": "base", "--cwd": "cwd", "--open": "open"}
WATCHER_FLAGS = {"--interval": "interval"}


class Exit(Exception):
    """End the command with <code>, printing <message> (if any)."""

    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


def one_of(names):
    """("browser", "nvim", "both") as "browser, nvim or both"."""
    names = list(names)
    return " or ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else "".join(names)


def interval_of(text):
    """<text> as the watcher's interval in seconds; raises Exit when it isn't a
    positive, finite number."""
    try:
        interval = float(text)
    except ValueError:
        interval = None
    if interval is None or not math.isfinite(interval) or interval <= 0:
        raise Exit(1, f"Error: the interval must be a number of seconds, not '{text}'")
    return interval


def parse(argv, open_in, env=None):
    """The options of `difftate` in <argv>. --open names one of <open_in>. Raises Exit for --help and for a wrong option."""
    env = os.environ if env is None else env
    opts = {"view": "", "base": "", "cwd": "",
            "open": env.get("DT_OPEN") or "browser", "interval": env.get("DT_INTERVAL") or "1"}
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            raise Exit(0, USAGE)
        if arg.startswith("--"):
            if arg not in FLAGS or i + 1 >= len(argv):
                raise Exit(1, f"Unknown flag: {arg}\n{USAGE}" if arg not in FLAGS else f"Error: {arg} needs a value")
            opts[FLAGS[arg]] = argv[i + 1]
            i += 2
        else:
            positional.append(arg)
            i += 1
    if len(positional) > 1:
        raise Exit(1, f"Error: one view at most, not {' and '.join(repr(p) for p in positional)}\n{USAGE}")
    opts["view"] = positional[0] if positional else ""
    opts["cwd"] = opts["cwd"] or os.getcwd()
    if opts["open"] not in open_in:
        raise Exit(1, f"Error: --open (or DT_OPEN) must be {one_of(open_in)}, not '{opts['open']}'")
    opts["interval"] = interval_of(opts["interval"])
    return opts


def parse_watcher(argv):
    """The options of the watcher process itself, which `difftate` starts."""
    opts = {"interval": "1"}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            raise Exit(0, WATCHER_USAGE)
        if arg not in WATCHER_FLAGS or i + 1 >= len(argv):
            raise Exit(1, f"Unknown flag: {arg}\n{WATCHER_USAGE}" if arg not in WATCHER_FLAGS
                       else f"Error: {arg} needs a value")
        opts[WATCHER_FLAGS[arg]] = argv[i + 1]
        i += 2
    opts["interval"] = interval_of(opts["interval"])
    return opts
