"""What the coding agents' event streams share: one JSON event per line, and
how a step is named. Each coding agent's own events.py reads its events."""
from __future__ import annotations

import json
from typing import Any, List, Protocol

from ....core.dispatch.model import News, Output, Unparsed, short


class ReadsEvents(Protocol):
    def news(self, event: dict) -> List[News]:
        """The news in one event of the coding agent's stream."""
        ...


def read_line(line: str, events: ReadsEvents) -> List[News]:
    """The news in one line of the coding agent's output. A line that isn't
    JSON is shown as it is, so errors stay visible."""
    line = line.rstrip("\n")
    if not line.strip():
        return []
    try:
        event = json.loads(line)
    except ValueError:
        return [Output(line)]
    try:
        return events.news(event)
    except Exception as e:  # never lose the coding agent's run over a formatting bug
        return [Unparsed(str(e))]


def describe(name: str, inp: Any) -> str:
    """A step: the tool's name and its most useful argument."""
    if not isinstance(inp, dict):
        return name
    for key in ("command", "file_path", "filePath", "path", "pattern", "url", "description"):
        if inp.get(key):
            return f"{name}  {short(inp[key], 120)}"
    return name
