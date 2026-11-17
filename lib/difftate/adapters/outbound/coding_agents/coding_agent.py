"""What every coding agent has: its command, its model, and where its runs
work."""
from __future__ import annotations

import os
from typing import Callable, Dict, List, NamedTuple, Sequence, Tuple

from ....core.dispatch.model import CouldNotStart, News
from .events import ReadsEvents
from .reply_channel import REPLY_COMMAND, RunFolder
from .run import ProcessRun


class OffLimits(NamedTuple):
    """What one run may not touch: write the folders in <keep_out> (difftate's
    folders) or read the files in <secrets> (the review API tokens)."""
    keep_out: Sequence[str] = ()
    secrets: Sequence[str] = ()


class CodingAgent:
    """A coding agent, and how this watcher runs it: the command and a model
    override (empty for the default). Each run starts a fresh agent session.
    Its runs work in <cwd>; <off_limits>() is what a run may not touch, read
    again for each run (a worktree added since gets its watcher's folder)."""
    name = default_cmd = ""
    reply_command = REPLY_COMMAND

    def __init__(self, cmd: str, model: str = "", cwd: str = ".",
                 off_limits: Callable[[], OffLimits] = OffLimits):
        self.cmd = cmd
        self.model = model
        self.cwd = cwd
        self.off_limits = off_limits

    def command(self, prompt: str, folder: RunFolder) -> Tuple[List[str], List[News]]:
        """The command line for one run whose replies go to <folder>, and its
        first news. A coding agent with a sandbox keeps the run to
        self.off_limits()."""
        raise NotImplementedError

    def events(self) -> ReadsEvents:
        """A reader for one run's event stream."""
        raise NotImplementedError

    def start(self, prompt: str, threads: Sequence[str]) -> ProcessRun:
        try:
            folder = RunFolder.create(threads)
        except OSError as e:
            raise CouldNotStart(f"could not make the run's folder ({e})")
        argv, first = self.command(prompt, folder)
        env: Dict[str, str] = dict(os.environ, DT_RUN_DIR=folder.path)
        return ProcessRun(argv, self.cwd, env, self.events(), folder, first)
