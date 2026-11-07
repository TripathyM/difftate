"""One watcher per repository: it holds watcher.lock in the repository's
difftate folder until it exits. A second `difftate` asks the running watcher
to show the view it was asked for, and exits."""
import fcntl
import os
import time

from ....core.changes.model import View
from .options import Exit

# How long a second watcher waits for one that is starting
STARTING_S = 60


def claim(folder, view, open_in, running_watcher, ask_running_watcher):
    """Become the watcher of the repository whose difftate folder is <folder>:
    the lock's file descriptor, held until the process exits. When another
    watcher holds it, ask that one to show <view> (opened in <open_in>) once it
    serves the review API, and raise Exit.

    running_watcher(folder) is the pid of the watcher serving the review API,
    or None; ask_running_watcher(folder, method, path, payload) calls it."""
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(folder, "watcher.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + STARTING_S
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            other = running_watcher(folder)  # one from before the lock file
            if other:
                switch(other, folder, view, open_in, ask_running_watcher)
            return fd
        except BlockingIOError:
            pass
        other = running_watcher(folder)
        if other:
            switch(other, folder, view, open_in, ask_running_watcher)
        if time.time() > deadline:
            os.close(fd)
            raise Exit(1, "Error: another watcher is starting for this repository, and it didn't serve "
                          f"the review within {STARTING_S}s")
        time.sleep(0.1)


def switch(pid, folder, view, open_in, ask_running_watcher):
    """Ask the watcher <pid> to show <view>, and raise Exit with what it said."""
    try:
        status, answer = ask_running_watcher(folder, "PUT", "/api/view", {"view": view, "open": open_in})
    except (OSError, ValueError, KeyError) as e:
        raise Exit(1, f"Error: difftate is already running for this repository (pid {pid}), "
                      f"but it didn't answer ({e})")
    if status != 200:
        raise Exit(1, f"Error: {(answer or {}).get('error') or status}")
    raise Exit(0, f"difftate is already running for this repository (pid {pid}): "
                  f"switched it to {View(answer['view'] or '').name}")
