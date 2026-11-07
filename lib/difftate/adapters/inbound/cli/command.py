"""The command: its options, the watcher's start, and how it stops (Ctrl+C,
SIGTERM, a closed terminal) with its exit code."""
import signal
import sys

from . import viewers
from .options import Exit, parse
from .watcher import Watcher


class Hangup(BaseException):
    """The terminal closed: stop everything, quietly (there's no one to print to)."""


def _terminate(signum, frame):
    raise KeyboardInterrupt


def _hangup(signum, frame):
    raise Hangup


def run(argv, wiring):
    """Run the watcher on <wiring> (wiring.Wiring) with the options in <argv>;
    the exit code."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _hangup)
    watcher = None
    try:
        opts = parse(argv, wiring.coding_agents, viewers.where_to_open(wiring.viewers))
        watcher = Watcher(opts, wiring)
        watcher.setup()
        watcher.start()
        watcher.forever()
    except Exit as e:
        if e.message:
            print(e.message)
        if watcher:
            watcher.stop(say=False)
        return e.code
    except KeyboardInterrupt:
        if watcher:
            watcher.stop()
        else:
            print()
        return 0
    except Hangup:
        if watcher:
            watcher.stop(say=False)
        return 129
    except BaseException:
        if watcher:
            watcher.stop(say=False)
        raise
