"""What every coding agent has: its command, its agent session, its model,
and where its runs work."""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

from ....core.dispatch.model import CouldNotStart, News
from .events import ReadsEvents
from .reply_channel import REPLY_COMMAND, RunFolder
from .run import AgentRun, context_window

NONE_FOUND = "    (none found)"


class CodingAgent:
    """A coding agent, and how this watcher runs it: the command, the agent
    session (empty for headless) and a model override (empty for the default).
    Its runs work in <cwd>; they may not write <keep_out> (the review's
    folder) or read <secrets> (the review API's token)."""
    name = default_cmd = ""
    reply_command = REPLY_COMMAND

    def __init__(self, cmd: str, session: str = "", model: str = "", cwd: str = ".",
                 keep_out: Sequence[str] = (), secrets: Sequence[str] = ()):
        self.cmd = cmd
        self.session = session
        self.model = model
        self.cwd = cwd
        self.keep_out = list(keep_out)
        self.secrets = list(secrets)

    def session_exists(self) -> bool:
        raise NotImplementedError

    def list_sessions(self) -> List[str]:
        raise NotImplementedError

    def command(self, prompt: str, folder: RunFolder) -> Tuple[List[str], List[News]]:
        """The command line for one run whose replies go to <folder>, and its
        first news."""
        raise NotImplementedError

    def events(self) -> ReadsEvents:
        """A reader for one run's event stream."""
        raise NotImplementedError

    def start(self, prompt: str, threads: Sequence[str]) -> AgentRun:
        try:
            folder = RunFolder.create(threads)
        except OSError as e:
            raise CouldNotStart(f"could not make the run's folder ({e})")
        argv, first = self.command(prompt, folder)
        env: Dict[str, str] = dict(os.environ, DT_RUN_DIR=folder.path)
        return AgentRun(argv, self.cwd, env, self.events(), folder, context_window() + first)
