"""`difftate agent [<name>]`: which coding agent replies in this repository.
With a name, it sets the repository's agent (in its git config, shared by its
worktrees); with none, it says which agent the repository uses and where that
comes from. It needs no watcher: the watcher reads the choice when a run starts."""
import os

from ....core.review.model import CouldNotRead, NotFound
from .options import Exit

USAGE = """Usage:
  difftate agent [<name>] [--cwd <path>]

  <name>      Set the agent for this repository (and its worktrees) from the agent list
  --cwd       A folder of the repository (default: current directory)"""


def run_agent(argv, wiring):
    """Run `difftate agent` as <argv> says (wiring.Wiring); the exit code."""
    try:
        cwd, names = os.getcwd(), []
        i = 0
        while i < len(argv):
            if argv[i] in ("--help", "-h"):
                raise Exit(0, USAGE)
            if argv[i] == "--cwd" and i + 1 < len(argv):
                cwd, i = argv[i + 1], i + 2
                continue
            if argv[i].startswith("--"):
                raise Exit(1, f"Unknown flag: {argv[i]}\n{USAGE}")
            names.append(argv[i])
            i += 1
        if len(names) > 1:
            raise Exit(1, f"Error: one agent name at most, not {' and '.join(repr(n) for n in names)}\n{USAGE}")
        if wiring.difftate_folder(cwd) is None:
            raise Exit(1, f"Error: {cwd} is not a checked-out folder of a git repository")
        try:
            if names:
                wiring.set_agent(cwd, names[0])
            chosen = wiring.agent_choice(cwd)
        except (NotFound, CouldNotRead) as e:
            raise Exit(1, f"Error: {e}")
        where = ("this repository's own setting" if chosen.source == "repository"
                 else f"the machine default, from {chosen.path}")
        print(f"{'Set: ' if names else ''}{chosen.name} replies here (from {where}); the list: {', '.join(chosen.names)}")
        return 0
    except Exit as e:
        if e.message:
            print(e.message)
        return e.code
