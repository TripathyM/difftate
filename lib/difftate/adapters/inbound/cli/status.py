"""`difftate status`: whether a review is Done, read from outside difftate.

  difftate status [--json] [--branch <branch>] [--base <branch>] [--cwd <path>]

It prints the current Done state and the last mark (done, undone, or cleared
by a commit), each with its time and commit. It only reads: the review's
folder is never started or written, so it works with a watcher running or
not, and for any branch of the repository, whatever the folder has checked
out. The review of a branch whose own checkout is elsewhere, or that was
merged and deleted, answers too.

A review whose branch got a new commit since it was marked Done shows as
cleared by that commit, at the time it is read: the watcher keeps the clearing
with its own time (the review history). The JSON has the shape of
GET /api/done, with "branch" and "base" added.
"""
import json
import os

from ....core.review.model import CouldNotRead, NotFound
from .options import Exit

USAGE = """difftate status — Whether a review is Done.

Usage:
  difftate status [--json] [--branch <branch>] [--base <branch>] [--cwd <path>]

Options:
  --json             Print the state as JSON: done, time, commit, lastMark {kind, time, commit},
                     head, openThreads, runsInFlight (with branch and base)
  --branch <branch>  The branch whose review to read (default: the checked-out branch)
  --base <branch>    The branch the review compares against (default: the repository's default branch)
  --cwd <path>       A folder of the repository (default: the current directory)
  --help             Show this help

It works whether or not difftate is running, and for any branch of the repository."""

FLAGS = {"--branch": "branch", "--base": "base", "--cwd": "cwd"}


def parse(argv):
    """The options in <argv>. Raises Exit for --help and for a wrong option."""
    opts = {"json": False, "branch": "", "base": "", "cwd": ""}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--help", "-h"):
            raise Exit(0, USAGE)
        if arg == "--json":
            opts["json"] = True
            i += 1
            continue
        if arg not in FLAGS or i + 1 >= len(argv):
            raise Exit(1, f"Unknown flag: {arg}\n{USAGE}" if arg not in FLAGS else f"Error: {arg} needs a value")
        opts[FLAGS[arg]] = argv[i + 1]
        i += 2
    opts["cwd"] = opts["cwd"] or os.getcwd()
    return opts


def _mark(mark):
    return None if mark is None else {"kind": mark.kind, "time": mark.time, "commit": mark.commit}


def status_json(branch, base, status):
    """The state as JSON: GET /api/done's, with the review's <branch> and <base>."""
    return {"branch": branch, "base": base, "head": status.head, "done": status.done,
            "time": status.mark.time if status.mark else None, "commit": status.mark.commit if status.mark else None,
            "lastMark": _mark(status.last_mark), "openThreads": status.open_threads,
            "runsInFlight": status.in_flight}


def _short(commit):
    return (commit or "")[:7]


def status_line(branch, base, status):
    """The state in a line, for a person."""
    said = {
        "done": lambda m: f"Done at {_short(m.commit)} ({m.time})",
        "undone": lambda m: f"not Done (undone at {m.time})",
        "cleared": lambda m: f"not Done (cleared by commit {_short(m.commit)} at {m.time})",
    }
    now = said[status.last_mark.kind](status.last_mark) if status.last_mark else "not Done"
    more = f", {status.open_threads} thread{'' if status.open_threads == 1 else 's'} still open" \
        if status.open_threads else ""
    return f"{branch} against {base}: {now}{more}"


def run_status(argv, wiring):
    """Print the Done state of a review, as `difftate status` says; the exit code.
    <wiring> is wiring.Wiring."""
    try:
        opts = parse(argv)
        found = wiring.difftate_folder(opts["cwd"])
        if found is None:
            raise Exit(1, f"Error: {opts['cwd']} is not a git repository")
        folder = found.reviews  # the reviews', shared by the repository's worktrees
        try:
            base = wiring.base(opts["cwd"], opts["base"])
            branch = opts["branch"] or wiring.review_branch(opts["cwd"], base)
            if not branch:
                raise Exit(1, "Error: the repository has no commit yet")
            status = wiring.done_status(folder, opts["cwd"], branch, base)
        except (NotFound, CouldNotRead) as e:
            raise Exit(1, f"Error: {e}")
    except Exit as e:
        if e.message:
            print(e.message)
        return e.code
    print(json.dumps(status_json(branch, base, status)) if opts["json"] else status_line(branch, base, status))
    return 0
