"""The memory store: a review's events in a list in this process's memory,
for tests. It plugs into the core's port for keeping the review."""
from __future__ import annotations

from typing import List

from ....core.review.model import Event


class MemoryStore:
    def __init__(self) -> None:
        self._events: List[Event] = []

    def load(self) -> List[Event]:
        return list(self._events)

    def append(self, events: List[Event]) -> None:
        self._events.extend(events)
