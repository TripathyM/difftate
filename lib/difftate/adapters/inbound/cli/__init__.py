"""The command line: an inbound adapter that starts the watcher and drives
the loop (the port for running the loop), ADR 0003.

options.py is the flags, the help and their errors. one_watcher.py keeps one
watcher per repository (watcher.lock), and asks a running one to switch the
view. viewers.py opens the review in the browser or a Herdr Review tab.
timer.py runs the loop every --interval. watcher.py is the watcher: its
start, following the checked-out branch, and its stop. command.py runs it,
with the exit codes. wiring.py is what main.py plugs in: the adapters it
picked, bound to the core.
"""
from .command import run
from .viewers import open_browser, open_in_herdr, where_to_open
from .wiring import Loop, Wiring

__all__ = ["Loop", "Wiring", "open_browser", "open_in_herdr", "run", "where_to_open"]
