"""`dt-export`: print a review's export, from outside difftate.

  dt-export [<folder>]

The export is the review's commit messages, every thread in full, which
threads need an answer, and how to reply (GLOSSARY.md, Export). It comes from
the review API of the watcher of the checked-out folder the command runs in,
or of <folder>: the watcher is found as a second `difftate` in that folder
finds it (its own difftate folder, in its own git folder), never through the
store, so the store keeps one writer (ADR 0006). Exporting changes no thread.

With a <folder>, the export's reply command names it (dt-reply --folder), as
the session that reads it may run in another folder. Without one, the session
runs where the command did, and dt-reply finds the watcher from there.
"""
import os
import sys
import urllib.parse

USAGE = """dt-export — Print the export of a review, for an agent session you start.

Usage:
  dt-export [<folder>]

Prints the review's commit messages, every thread in full (open, resolved and
dismissed, with comments, replies, thread status and thread state), which
threads need an answer, and how to reply. It changes nothing.

The review is that of the checked-out folder you run it in, or of <folder>: the
one difftate is running in. One must be running there."""


def run_export(argv, wiring, out=sys.stdout, err=sys.stderr):
    """Print the export as `dt-export` says; the exit code. <wiring> is
    wiring.Wiring. The export goes to <out>, what went wrong to <err>."""
    if argv[:1] in (["-h"], ["--help"]):
        print(USAGE, file=out)
        return 0
    if len(argv) > 1:
        print(USAGE, file=err)
        return 2
    given = argv[0] if argv else None
    cwd = os.path.abspath(given) if given else os.getcwd()
    found = wiring.difftate_folder(cwd)
    if found is None:
        print(f"dt-export: {cwd} is not a git repository", file=err)
        return 1
    _, watcher_folder, top = found
    pid = wiring.running_watcher(watcher_folder)
    if not pid:
        print(f"dt-export: no difftate is running for {top}: start it there, then run dt-export again", file=err)
        return 1
    path = "/api/export" + (f"?folder={urllib.parse.quote(top)}" if given else "")
    try:
        status, answer = wiring.ask_running_watcher(watcher_folder, "GET", path)
    except (OSError, ValueError, KeyError) as e:
        print(f"dt-export: difftate is running for {top} (pid {pid}), but it didn't answer ({e})", file=err)
        return 1
    if status != 200 or not isinstance(answer, str):
        said = (answer or {}).get("error") if isinstance(answer, dict) else None
        print(f"dt-export: difftate could not export the review: {said or status}", file=err)
        return 1
    out.write(answer)
    return 0
