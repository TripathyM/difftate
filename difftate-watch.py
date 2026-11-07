#!/usr/bin/env python3
"""difftate's watcher (Python 3.9+, standard library only).

The difftate / dtc / dto shell functions start it. Run with --help for its options.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))

from difftate.main import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
