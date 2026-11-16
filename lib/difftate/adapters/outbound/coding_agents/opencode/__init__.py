"""OpenCode: `opencode run <prompt> --format json`. It has no sandbox
setting, so a run's access isn't enforced for it: the watcher's checks are."""
from __future__ import annotations

from typing import List, Tuple

from .....core.dispatch.model import News
from ..coding_agent import CodingAgent
from ..reply_channel import RunFolder
from .events import OpenCodeEvents


class OpenCode(CodingAgent):
    name = "opencode"
    default_cmd = "opencode"

    def command(self, prompt: str, folder: RunFolder) -> Tuple[List[str], List[News]]:
        args = ["--auto", "--format", "json"]
        if self.model:
            args += ["--model", self.model]
        return [self.cmd, "run", prompt, *args], []

    def events(self) -> OpenCodeEvents:
        return OpenCodeEvents()
