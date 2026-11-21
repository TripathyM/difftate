#!/usr/bin/env python3
"""difftate's watcher (latest Python, standard library only): the one watcher for the machine.

`difftate` starts it in the background; run it yourself only to debug. --help lists its options.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))

from difftate.main import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
