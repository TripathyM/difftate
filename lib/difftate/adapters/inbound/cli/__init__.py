"""The command line: an inbound adapter that starts the watcher and drives
the loop (the port for running the loop), ADR 0003.

options.py is the flags, the help and their errors. difftate.py is `difftate`:
it starts the watcher when none runs, opens the folder's review, and ends
(`difftate stop` stops it). agent.py is `difftate agent`: which listed agent
replies in the repository. demo.py is `difftate demo`: a throwaway review in a difftate folder
of its own, built through its watcher's review API. one_watcher.py is the machine-wide lock that keeps
it one. viewers.py opens the review in the browser or the Neovim viewer.
watcher.py is the watcher: the table of folders it serves, each one's loop
(following the checked-out branch), and its stop. command.py runs it, with the
exit codes; log.py is its log. status.py is `difftate status`: a review's Done
state, read-only, with no watcher. export.py is `dt-export`: a review's export,
asked of the watcher. reply.py is `dt-reply`: a run's answer into its folder,
or an agent session's, posted through the review API of the watcher (ADR 0006).
wiring.py is what main.py plugs in: the adapters it picked, bound to the core.
"""
from .command import run_watcher
from .difftate import run_difftate, with_folder
from .agent import run_agent
from .demo import run_demo
from .export import run_export
from .reply import ReplyRefused, run_reply
from .status import run_status
from .viewers import open_browser, open_in_nvim, where_to_open
from .wiring import Loop, Wiring

__all__ = ["Loop", "run_agent", "ReplyRefused", "Wiring", "open_browser", "open_in_nvim", "run_demo", "run_difftate",
           "run_export",
           "run_reply", "run_status", "run_watcher", "where_to_open", "with_folder"]
