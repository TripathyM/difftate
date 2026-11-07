"""Claude Code: `claude -p <prompt> --output-format stream-json --verbose`,
with each run's sandbox settings (RunAccess)."""
from __future__ import annotations

import glob
import json
import os
from collections import namedtuple
from typing import List, Tuple

from .....core.dispatch.model import ModelChosen, News
from ..coding_agent import NONE_FOUND, CodingAgent
from ..reply_channel import RunFolder
from .events import ClaudeEvents


class RunAccess(namedtuple("RunAccess", "write deny_write deny_read")):
    """What one run may touch: it may write the folders in <write> (its run's
    folder), and may not write <deny_write> (the store) or read <deny_read> (the
    API token). Claude's sandbox and permission rules enforce it."""


class ClaudeCode(CodingAgent):
    name = "claude"
    default_cmd = "claude"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same rule as claude itself. A wrapper that sets its own config dir needs
        # CLAUDE_CONFIG_DIR exported for the watcher too.
        self.home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

    def _session_file(self):
        found = glob.glob(os.path.join(glob.escape(self.home), "projects", "*", f"{glob.escape(self.session)}.jsonl"))
        return found[0] if found else None

    def session_exists(self) -> bool:
        return self._session_file() is not None

    def list_sessions(self) -> List[str]:
        files = sorted(glob.glob(os.path.join(glob.escape(self.home), "projects", "*", "*.jsonl")))
        if not files:
            return [NONE_FOUND]
        return [os.path.basename(f)[: -len(".jsonl")] for f in files][-5:]

    def session_model(self) -> str:
        """The model of the session's latest interactive (cli) turn.

        The model isn't stored with a session: each `claude -p` picks the current
        default, which changes whenever /model is used in ANY session. Reading it
        from the session keeps replies on the same model, with its thinking blocks
        (other models drop them)."""
        path = self._session_file()
        if not path:
            return ""
        interactive = any_model = ""
        try:
            with open(path, errors="replace") as f:
                for line in f:
                    if '"assistant"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    model = (e.get("message") or {}).get("model") or ""
                    if e.get("type") != "assistant" or not model or model.startswith("<"):
                        continue
                    any_model = model
                    if e.get("entrypoint") == "cli":
                        interactive = model
        except OSError:
            return ""
        return interactive or any_model

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
        model, source = self.model, "--model"
        if not model and self.session:
            model, source = self.session_model(), "session"
        if model:
            args += ["--model", model]
        if self.session:
            args += ["--resume", self.session]
        return [self.cmd, "-p", prompt, *args], [ModelChosen(model, source if model else "")]

    def events(self) -> ClaudeEvents:
        return ClaudeEvents()
