"""`difftate`: opens the review of the folder it runs in, starting the watcher
for the machine when none runs, and ends. It is the only thing that starts the
watcher (ADR 0008): viewers and scripts only find the one that runs.

  difftate [<view>] [--base <branch>] [--open browser|nvim|both]
  difftate stop

It adds the folder (the watcher serves a folder from the first request that
names it), shows the view when one is given, and opens the viewer itself: the
watcher never opens one. `difftate stop` stops the watcher through the review
API; a run in flight ends failed "(the watcher stopped)".
"""
import os
import time
import urllib.parse

from ....core.changes.model import View
from . import one_watcher, viewers
from .options import USAGE, Exit, parse

# How long `difftate stop` waits for the watcher to end its runs and exit
STOPPING_S = 30


def with_folder(path, folder, base=""):
    """<path> of the review API, naming <folder> (and <base>, when given)."""
    query = [("folder", folder)] + ([("base", base)] if base else [])
    return path + ("&" if "?" in path else "?") + urllib.parse.urlencode(query)


def _said(answer, status):
    return (answer.get("error") if isinstance(answer, dict) else None) or status


def _ask(wiring, method, path, payload=None):
    """The review API's answer: (status, JSON); raises Exit when it can't be asked."""
    try:
        return wiring.ask_running_watcher(wiring.difftate_home, method, path, payload)
    except (OSError, ValueError, KeyError) as e:
        raise Exit(1, f"Error: difftate is running, but it didn't answer ({e})")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def run_difftate(argv, wiring):
    """Run `difftate` as <argv> says (wiring.Wiring); the exit code."""
    try:
        if argv[:1] == ["stop"]:
            if len(argv) > 1:
                raise Exit(1, f"Error: stop takes no argument\n{USAGE}")
            return _stop(wiring)
        return _open(argv, wiring)
    except Exit as e:
        if e.message:
            print(e.message)
        return e.code


def _open(argv, wiring):
    opts = parse(argv, wiring.coding_agents, viewers.where_to_open(wiring.viewers))
    found = wiring.difftate_folder(opts["cwd"])
    if found is None:
        raise Exit(1, f"Error: {opts['cwd']} is not a checked-out folder of a git repository")
    root = found.root
    pid = one_watcher.ensure(wiring.difftate_home, wiring.running_watcher, lambda: wiring.start_watcher(
        ["--tool", opts["tool"], "--cmd", opts["cmd"], "--model", opts["model"], "--interval", str(opts["interval"])]))
    # The first request that names the folder adds it (and switches to the base, when one is named)
    status, review = _ask(wiring, "GET", with_folder("/api/review", root, opts["base"]))
    if status != 200:
        raise Exit(1, f"Error: {_said(review, status)}")
    shown = {}
    if opts["view"]:
        status, shown = _ask(wiring, "PUT", with_folder("/api/view", root), {"view": opts["view"]})
        if status != 200:
            raise Exit(1, f"Error: {_said(shown, status)}")
    else:
        status, shown = _ask(wiring, "GET", with_folder("/api/view", root))
    print(f"difftate is running (pid {pid}): the review of {review['branch']} against {review['base']} "
          f"in {root}, showing {View((shown or {}).get('view') or '').name}")
    status, launch = _ask(wiring, "POST", with_folder("/api/launch", root))
    if status != 200:
        raise Exit(1, f"Error: {_said(launch, status)}")
    if opts["open"] != "nvim":
        print(f"  → {launch['url']}")
    viewers.open_review(wiring.viewers, opts["open"], launch["url"], root)
    return 0


def _stop(wiring):
    pid = wiring.running_watcher(wiring.difftate_home)
    if not pid:
        print("difftate is not running")
        return 0
    status, answer = _ask(wiring, "POST", "/api/stop", {})
    if status != 200:
        raise Exit(1, f"Error: difftate refused to stop: {_said(answer, status)}")
    deadline = time.time() + STOPPING_S
    while _alive(pid):
        if time.time() > deadline:
            raise Exit(1, f"Error: difftate (pid {pid}) didn't stop within {STOPPING_S}s")
        time.sleep(0.1)
    print(f"difftate stopped (pid {pid})")
    return 0
