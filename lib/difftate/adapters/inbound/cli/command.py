"""The watcher's command: its options, and how it stops (a signal, or
`difftate stop` through the review API) with its exit code."""
import signal
import sys

from .log import FolderLog
from .options import Exit, parse_watcher
from .watcher import Watcher


def run_watcher(argv, wiring):
    """Run the watcher on <wiring> (wiring.Wiring) with the options in <argv>,
    until it is stopped; the exit code. It runs in the background: standard
    output is its log."""
    log = FolderLog(sys.stdout)
    sys.stdout = log
    watcher = None
    try:
        opts = parse_watcher(argv, wiring.coding_agents)
        watcher = Watcher(opts, wiring)
        watcher.log = log
        watcher.setup()
        # A signal asks it to stop, as `difftate stop` does; closing a terminal
        # doesn't: no terminal holds it
        signal.signal(signal.SIGINT, lambda signum, frame: watcher.stopping.set())
        signal.signal(signal.SIGTERM, lambda signum, frame: watcher.stopping.set())
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        watcher.serve()
        watcher.stop()
        return 0
    except Exit as e:
        if e.message:
            print(e.message)
        if watcher:
            watcher.stop(say=False)
        return e.code
    except BaseException:
        if watcher:
            watcher.stop(say=False)
        raise
