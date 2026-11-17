"""Claude Code's event stream (`--output-format stream-json --verbose`), read
into news."""
from __future__ import annotations

from typing import List

from .....core.dispatch.model import Finished, News, Said, AgentSessionStarted, Step, short
from ..events import ERROR_MAX, describe


class ClaudeEvents:
    def news(self, event: dict) -> List[News]:
        kind = event.get("type")
        found: List[News] = []
        if kind == "system" and event.get("subtype") == "init":
            found.append(AgentSessionStarted(event.get("session_id", "?"), event.get("model", "?")))
        elif kind == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    found.append(Step(describe(block.get("name", "?"), block.get("input"))))
                elif block.get("type") == "text" and block.get("text", "").strip():
                    found.append(Said(block["text"]))
        elif kind == "result":
            cost = event.get("total_cost_usd")
            if event.get("is_error"):
                found.append(Finished(False, cost, short(str(event.get("result") or event.get("subtype")), ERROR_MAX)))
            else:
                found.append(Finished(True, cost))
        return found
