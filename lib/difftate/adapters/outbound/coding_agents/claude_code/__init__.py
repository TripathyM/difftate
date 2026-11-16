"""Claude Code: `claude -p <prompt> --output-format stream-json --verbose`,
with each run's sandbox settings (RunAccess)."""
from __future__ import annotations

import json
from collections import namedtuple
from typing import List, Tuple

from .....core.dispatch.model import ModelChosen, News
from ..coding_agent import CodingAgent
from ..reply_channel import RunFolder
from .events import ClaudeEvents


class RunAccess(namedtuple("RunAccess", "write deny_write deny_read")):
    """What one run may touch: it may write the folders in <write> (its run's
    folder), and may not write <deny_write> (the store) or read <deny_read> (the
    API token). Claude's sandbox and permission rules enforce it."""


class ClaudeCode(CodingAgent):
    name = "claude"
    default_cmd = "claude"

    @staticmethod
    def run_settings(access: RunAccess) -> str:
        """Claude's settings for one run, merged into the user's own. The sandbox
        binds the Bash tool (and is ignored when the sandbox is off); permission
        rules bind Claude's own file tools (Edit rules cover Write too). A path
        rule starts with "//" for an absolute path."""
        deny = [f"Edit(/{path}/**)" for path in access.deny_write] + [f"Read(/{path})" for path in access.deny_read]
        return json.dumps({
            "sandbox": {"filesystem": {"allowWrite": list(access.write), "denyWrite": list(access.deny_write),
                                       "denyRead": list(access.deny_read)}},
            "permissions": {"deny": deny}}, separators=(",", ":"))

    def command(self, prompt: str, folder: RunFolder) -> Tuple[List[str], List[News]]:
        access = RunAccess(write=[folder.path], deny_write=self.keep_out, deny_read=self.secrets)
        args = ["--allowedTools", "Edit", "Write", "Read", "Bash", "--settings", self.run_settings(access),
                "--output-format", "stream-json", "--verbose"]
        if self.model:
            args += ["--model", self.model]
        return [self.cmd, "-p", prompt, *args], [ModelChosen(self.model, "--model" if self.model else "")]

    def events(self) -> ClaudeEvents:
        return ClaudeEvents()
