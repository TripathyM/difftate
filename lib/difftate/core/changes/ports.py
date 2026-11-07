"""The Changes context's driven port: reading the code.

Only the part that opening a thread needs is here so far. The rest (file
versions and hunks, the checked-out branch, the changeset for a view) comes
with the use cases that need it.
"""
from __future__ import annotations

from typing import Protocol

from .model import Snapshot


class ForReadingTheCode(Protocol):
    def snapshot(self, file: str, side: str, view: str, start_line: int, end_line: int) -> Snapshot:
        """<file> on <side> ("old" or "new") of <view> ("" for all changes) as it
        is now, kept so a thread can move with its code later, and the code on
        lines <start_line>..<end_line> in it. Raises the core's CouldNotRead
        when the code can't be read."""
        ...
