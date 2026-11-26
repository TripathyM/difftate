"""`difftate --guide`: prints the viewer guide of this difftate (ADR 0010). Its
one source is docs/viewer-guide.md in this checkout, which GitHub shows too.
It needs no watcher and no repository."""
import sys

from .options import USAGE, Exit


def run_guide(argv, guide_path):
    """Print the viewer guide kept at <guide_path>; the exit code."""
    try:
        if argv and argv[0] in ("--help", "-h"):
            raise Exit(0, USAGE)
        if argv:
            raise Exit(1, f"Error: --guide takes no argument\n{USAGE}")
        try:
            with open(guide_path, encoding="utf-8") as f:
                sys.stdout.write(f.read())
        except OSError as e:
            raise Exit(1, f"Error: the viewer guide can't be read ({e})")
        return 0
    except Exit as e:
        if e.message:
            print(e.message)
        return e.code
