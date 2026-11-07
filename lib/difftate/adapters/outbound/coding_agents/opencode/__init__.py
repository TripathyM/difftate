"""OpenCode: `opencode run <prompt> --format json`. It has no sandbox
setting, so a run's access isn't enforced for it: the watcher's checks are."""
from __future__ import annotations

import subprocess
from typing import List, Tuple

from .....core.dispatch.model import News
from ..coding_agent import NONE_FOUND, CodingAgent
from ..reply_channel import RunFolder
from .events import OpenCodeEvents


class OpenCode(CodingAgent):
    name = "opencode"
    default_cmd = "opencode"

    def _list(self) -> Tuple[int, str]:
        try:
            r = subprocess.run(["opencode", "session", "list"], capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr
        except OSError:
            return 1, ""

    def session_exists(self) -> bool:
        return self.session in self._list()[1]

    def list_sessions(self) -> List[str]:
        code, out = self._list()
        return out.rstrip("\n").split("\n") if code == 0 else [NONE_FOUND]

    def command(self, prompt: str, folder: RunFolder) -> Tuple[List[str], List[News]]:
        args = ["--auto", "--format", "json"]
        if self.model:
            args += ["--model", self.model]
        if self.session:
            args += ["--session", self.session]
        return [self.cmd, "run", prompt, *args], []

    def events(self) -> OpenCodeEvents:
        return OpenCodeEvents()
