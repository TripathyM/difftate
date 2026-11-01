#!/usr/bin/env python3
"""difftate's Python watcher (Python 3.9+, standard library only).

Opt-in: DT_WATCHER=python makes difftate / dtc / dto start this instead of
difftate-watch.sh. Same options; run with --help for them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))

from difftate.watcher import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
