"""The command line's options: the flags, the help, and the errors they give."""
import math
import os

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
                         switch views
  --cwd <path>           The repository's folder the coding agent works in (default: current
                         directory)
  --interval <seconds>   Polling interval in seconds (default: 1)
  --cmd <binary>         Override the CLI binary or shell alias (e.g. a wrapper around claude)
  --model <model>        Model for the coding agent (default: the coding agent's own default)
  --open <where>         browser, nvim, herdr or both (default: $DT_OPEN, else browser).
                         The viewer to open, not the host. nvim: the Neovim viewer, in a
                         "Review · <folder>" tab running nvim when difftate runs where Herdr is reachable (or
                         switches to it), else the command to run is printed.
                         herdr: the Herdr viewer, frozen: a Review tab in the Herdr app, or
                         the browser if Herdr can't be reached
  --help                 Show this help

Each run starts a fresh agent session of the coding agent.

Examples:
  # Claude Code
  difftate-watch.py --tool claude --interval 1

  # Claude Code on Opus, against the develop branch
  difftate-watch.py --base develop --tool claude --model claude-opus-5-5 --interval 1

  # OpenCode, the last 3 commits
  difftate-watch.py --ref HEAD~3 --tool opencode --interval 1"""

FLAGS = {"--ref": "ref", "--base": "base", "--tool": "tool", "--model": "model", "--cwd": "cwd",
         "--interval": "interval", "--cmd": "cmd", "--open": "open"}


class Exit(Exception):
    """End the command with <code>, printing <message> (if any)."""

    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


def one_of(names):
    """("browser", "herdr", "both") as "browser, herdr or both"."""
    names = list(names)
    return " or ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else "".join(names)


def parse(argv, coding_agents, open_in):
    """The options in <argv>. --tool names one of <coding_agents>, and --open
    one of <open_in>. Raises Exit for --help and for a wrong option."""
    opts = {"ref": "", "base": "", "tool": "", "model": "", "cwd": "", "interval": "1", "cmd": "",
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
    if opts["open"] not in open_in:
        raise Exit(1, f"Error: --open (or DT_OPEN) must be {one_of(open_in)}, not '{opts['open']}'")
    if opts["tool"] not in coding_agents:
        raise Exit(1, f"Error: unsupported tool '{opts['tool']}'. Supported: {' '.join(coding_agents)}")
    try:
        interval = float(opts["interval"])
    except ValueError:
        interval = None
    if interval is None or not math.isfinite(interval) or interval <= 0:
        raise Exit(1, f"Error: --interval must be a number of seconds, not '{opts['interval']}'")
    opts["interval"] = interval
    return opts
