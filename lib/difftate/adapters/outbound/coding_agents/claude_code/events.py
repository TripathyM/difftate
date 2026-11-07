"""Claude Code's event stream (`--output-format stream-json --verbose`), read
into news."""
from __future__ import annotations

from typing import List

from .....core.dispatch.model import ContextUsed, Finished, News, Said, SessionStarted, Step, short
from ..events import describe

ERROR_MAX = 300


class ClaudeEvents:
    def news(self, event: dict) -> List[News]:
        kind = event.get("type")
        found: List[News] = []
        if kind == "system" and event.get("subtype") == "init":
            found.append(SessionStarted(event.get("session_id", "?"), event.get("model", "?")))
        elif kind == "assistant":
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            if usage:
                found.append(ContextUsed(tokens=sum(usage.get(k) or 0 for k in (
                    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))))
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    found.append(Step(describe(block.get("name", "?"), block.get("input"))))
                elif block.get("type") == "text" and block.get("text", "").strip():
                    found.append(Said(block["text"]))
        elif kind == "result":
            windows = [m.get("contextWindow") or 0 for m in (event.get("modelUsage") or {}).values()]
            if max(windows, default=0):
                found.append(ContextUsed(window=max(windows)))
            cost = event.get("total_cost_usd")
            if event.get("is_error"):
                found.append(Finished(False, cost, short(str(event.get("result") or event.get("subtype")), ERROR_MAX)))
            else:
                found.append(Finished(True, cost))
        return found
