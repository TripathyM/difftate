"""OpenCode's event stream (`opencode run --format json`), read into news."""
from __future__ import annotations

from typing import List

from .....core.dispatch.model import ContextUsed, Finished, News, Said, Step, short
from ..events import describe

ERROR_MAX = 300


class OpenCodeEvents:
    """One run's events. The cost adds up over the run's steps."""

    def __init__(self) -> None:
        self.cost = 0.0

    def news(self, event: dict) -> List[News]:
        kind = event.get("type")
        part = event.get("part") or {}
        found: List[News] = []
        if kind == "tool_use":
            state = part.get("state") or {}
            found.append(Step(describe(part.get("tool", "?"), state.get("input")), failed=state.get("status") == "error"))
        elif kind == "text" and part.get("text", "").strip():
            found.append(Said(part["text"]))
        elif kind == "step_finish":
            self.cost += part.get("cost") or 0
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            used = sum(x or 0 for x in (tokens.get("input"), tokens.get("output"), cache.get("read"), cache.get("write")))
            if used:
                found.append(ContextUsed(tokens=used))
            if part.get("reason") == "stop":
                found.append(Finished(True, self.cost))
        elif kind == "error":
            found.append(Finished(False, self.cost, short(str(event.get("error") or event), ERROR_MAX)))
        return found
