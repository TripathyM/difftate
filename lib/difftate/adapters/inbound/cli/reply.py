"""`dt-reply`: a coding agent's answer to a review thread.

  dt-reply [--folder <folder>] <thread> ["<answer>"]

Inside a run (DT_RUN_DIR is set) the answer is left in the run's folder, and the
run's end gives it to Dispatch, which posts it: the run has no review API and no
token (its sandbox denies it), so it never takes the other path, even when its
folder is gone. Outside a run, in an agent session the reviewer started with an
export (GLOSSARY.md, Export), the answer is posted through the review API of the
watcher, naming the checked-out folder the command runs in, or <folder>: found as
`dt-export` finds it. It never writes the store (ADR 0006), so it works only
while that watcher runs. The answer is posted as a coding agent's reply, with no
progress note, and changes no thread status.
"""
import os
import sys

from .difftate import with_folder

USAGE = """dt-reply — The coding agent's answer to a review thread.

Usage:
  dt-reply [--folder <folder>] <thread> "<answer>"
  dt-reply [--folder <folder>] <thread> <<'EOF'        (the answer from stdin, for quotes or several lines)

<thread> is the thread's id, or its first 8 characters as the prompt or the export
shows them. Write only the answer: difftate posts it as a reply.

Inside a difftate run (which sets DT_RUN_DIR) it leaves the answer for the run.
In an agent session you started with dt-export, it posts the answer through the
difftate watcher, naming the checked-out folder you run it in, or <folder> (the
export names it when you gave one): it must be running, or nothing is posted."""


class ReplyRefused(Exception):
    """The run's folder refused the answer: the message says why."""


def _parse(argv):
    """(folder or None, thread, answer or None for stdin), or None for a usage error."""
    folder = None
    if argv[:1] == ["--folder"]:
        if len(argv) < 2:
            return None
        folder, argv = argv[1], argv[2:]
    if len(argv) not in (1, 2):
        return None
    return folder, argv[0], (argv[1] if len(argv) == 2 and argv[1] != "-" else None)


def run_reply(argv, wiring, env=None, cwd=None, stdin=sys.stdin, out=sys.stdout, err=sys.stderr):
    """Reply as `dt-reply` says; the exit code. <wiring> is wiring.Wiring (only
    for a reply outside a run). <env> and <cwd> default to the process's own.
    The answer is read from <stdin> when argv has none; "Replied" goes to <out>,
    what went wrong to <err>."""
    if argv[:1] in (["-h"], ["--help"]):
        print(USAGE, file=out)
        return 0
    parsed = _parse(argv)
    if parsed is None:
        print(USAGE, file=err)
        return 2
    folder, thread, answer = parsed
    env = os.environ if env is None else env
    run_dir = env.get("DT_RUN_DIR")
    if run_dir and folder is not None:
        print("dt-reply: --folder is for a session outside a run: a run answers through its own folder", file=err)
        return 1
    body = stdin.read() if answer is None else answer
    if run_dir:
        try:
            posted = wiring.reply_in_run(run_dir, thread, body)
        except (ReplyRefused, OSError) as e:
            print(f"dt-reply: {e}", file=err)
            return 1
    else:
        posted = _reply_through_watcher(wiring, folder, os.getcwd() if cwd is None else cwd, thread, body, err)
        if posted is None:
            return 1
    print(f"Replied to thread {posted[:8]}.", file=out)
    return 0


def _reply_through_watcher(wiring, given, cwd, thread, body, err):
    """The full id of the thread replied to, or None after saying (on <err>) why not."""
    if not body.strip():
        print("dt-reply: the answer is empty", file=err)
        return None
    where = os.path.abspath(given) if given else cwd
    found = wiring.difftate_folder(where)
    if found is None:
        print(f"dt-reply: {where} is not a git repository", file=err)
        return None
    top, home = found.root, wiring.difftate_home
    pid = wiring.running_watcher(home)
    if not pid:
        print("dt-reply: No difftate is running: run `difftate` in a terminal; nothing was posted", file=err)
        return None
    try:
        status, threads = wiring.ask_running_watcher(home, "GET", with_folder("/api/threads", top))
        if status != 200 or not isinstance(threads, list):
            print(f"dt-reply: difftate could not list the review's threads: {_said(threads) or status}; nothing was posted", file=err)
            return None
        matches = [t["id"] for t in threads if thread and t["id"].startswith(thread)]
        if len(matches) != 1:
            print(f"dt-reply: no thread {thread!r} in this review" if not matches
                  else f"dt-reply: {thread!r} matches several threads", file=err)
            return None
        status, answer = wiring.ask_running_watcher(
            home, "POST", with_folder(f"/api/threads/{matches[0]}/comments", top), {"kind": "reply", "body": body})
    except (OSError, ValueError, KeyError) as e:
        print(f"dt-reply: difftate is running (pid {pid}), but it didn't answer ({e}); nothing was posted", file=err)
        return None
    if status != 200:
        print(f"dt-reply: difftate refused the reply: {_said(answer) or status}", file=err)
        return None
    return matches[0]


def _said(answer):
    return answer.get("error") if isinstance(answer, dict) else None
