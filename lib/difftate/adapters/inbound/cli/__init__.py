"""The command line: an inbound adapter that starts the watcher and drives
the loop (the port for running the loop), ADR 0003.

options.py is the flags, the help and their errors. one_watcher.py keeps one
watcher per checked-out folder (watcher.lock), and asks a running one to switch the
view. viewers.py opens the review in the browser or a Herdr Review tab.
timer.py runs the loop every --interval. watcher.py is the watcher: its
start, following the checked-out branch, and its stop. command.py runs it,
with the exit codes. status.py is `difftate status`: a review's Done state,
read-only, with no watcher. export.py is `dt-export`: a review's export, asked
of the watcher of a folder. reply.py is `dt-reply`: a run's answer into its
folder, or an agent session's, posted through the review API of the watcher of
a folder (ADR 0006). wiring.py is what main.py plugs in: the adapters it
picked, bound to the core.
"""
from .command import run
from .export import run_export
from .reply import ReplyRefused, run_reply
from .status import run_status
from .viewers import open_browser, open_in_herdr, where_to_open
from .wiring import Loop, Wiring

__all__ = ["Loop", "ReplyRefused", "Wiring", "open_browser", "open_in_herdr", "run", "run_export", "run_reply",
           "run_status", "where_to_open"]
