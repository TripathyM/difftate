"""Finding a coding agent's command, and stopping a process and everything
it started."""
import os
import shutil
import signal
import subprocess
import time

from ....core.dispatch.model import CouldNotStart

STOP_GRACE_S = 3


def find_command(cmd):
    """The command's path, following a zsh alias when it isn't on PATH.
    Raises the core's CouldNotStart when it is neither."""
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
    raise CouldNotStart(f"command '{cmd}' not found (not in PATH, not a shell alias)")


def descendants(pid):
    """Every process below <pid>, children first."""
    try:
        rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    except OSError:
        return []
    children = {}
    for row in rows.splitlines():
        parts = row.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(0), []):
            found.append(child)
            todo.append(child)
    return found


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # it exists, owned by someone else
    return True


def stop_tree(proc):
    """Stop <proc> (a Popen started with start_new_session=True), its process
    group and every process below it: SIGTERM first, SIGKILL after a grace period."""
    pids = [proc.pid] + descendants(proc.pid)
    _signal_group(proc.pid, signal.SIGTERM)
    for pid in pids:
        _signal(pid, signal.SIGTERM)
    try:
        proc.wait(timeout=STOP_GRACE_S)
    except subprocess.TimeoutExpired:
        pass
    deadline = time.time() + STOP_GRACE_S
    while time.time() < deadline and any(_alive(p) for p in pids[1:]):
        time.sleep(0.05)
    _signal_group(proc.pid, signal.SIGKILL)
    for pid in pids:
        if _alive(pid):
            _signal(pid, signal.SIGKILL)
    try:
        proc.wait(timeout=STOP_GRACE_S)
    except subprocess.TimeoutExpired:
        pass
