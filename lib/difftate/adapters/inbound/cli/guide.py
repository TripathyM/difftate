"""`difftate --guide`: prints the viewer guide of this difftate (ADR 0010). Its
one source is docs/viewer-guide.md in this checkout, which GitHub shows too.
It needs no watcher and no repository."""
import sys

from .options import USAGE


def run_guide(argv, path):
    """Print the viewer guide at <path>; the exit code."""
    if argv:
        print(f"Error: --guide takes no argument\n{USAGE}")
        return 1
    try:
        with open(path, encoding="utf-8") as f:
            sys.stdout.write(f.read())
    except OSError as e:
        print(f"Error: the viewer guide can't be read ({e})")
        return 1
    return 0
