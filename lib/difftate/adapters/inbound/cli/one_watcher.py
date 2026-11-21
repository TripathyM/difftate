"""One watcher for the machine (ADR 0008). Whoever starts it holds watcher.lock
in the difftate folder of the home, from the moment it looks for a running
watcher until that one answers: a second `difftate` meanwhile waits for it,
sees it run, and uses it. The watcher itself holds no lock: it runs until
`difftate stop`."""
import fcntl
import os
import time

from .options import Exit

# How long a `difftate` waits for another to start the watcher, and for the watcher it started
STARTING_S = 60


def ensure(home, running_watcher, start):
    """The pid of the watcher serving from <home>, started now if none runs.
    running_watcher(home) is its pid or None; start() starts one in the
    background and returns a function that says whether it is still alive (so
    a watcher that dies while starting is no reason to wait)."""
    os.makedirs(home, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(home, "watcher.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + STARTING_S
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                pass
            pid = running_watcher(home)
            if pid:
                return pid
            if time.time() > deadline:
                raise Exit(1, f"Error: another difftate is starting the watcher, and it didn't answer within {STARTING_S}s")
            time.sleep(0.1)
        pid = running_watcher(home)
        if pid:
            return pid
        alive = start()
        while time.time() < deadline:
            pid = running_watcher(home)
            if pid:
                return pid
            if not alive():
                break
            time.sleep(0.1)
        raise Exit(1, "Error: the watcher did not start" + (f" within {STARTING_S}s" if alive() else "")
                   + f"; its log is {os.path.join(home, 'log')}\n{_tail(os.path.join(home, 'log'))}")
    finally:
        os.close(fd)  # closing it unlocks it


def _tail(path, lines=5):
    """The last <lines> lines of the file <path>, indented."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "\n".join("  " + line for line in f.read().splitlines()[-lines:])
    except OSError:
        return ""
