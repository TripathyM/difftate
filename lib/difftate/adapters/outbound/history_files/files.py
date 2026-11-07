"""The review history: every thread, comment and reply from every review on
this machine, in one JSON-lines file per month (`~/.difftate/history/
YYYY-MM.jsonl`), never deleted.

A line is the line the local store keeps for the event (local_store/lines.py),
with the review it came from added: {"repo": {"path", "remote"}, "branch",
"base", "review"}. Every store gets the review history, so it is its own
adapter, apart from any store (ADR 0003).
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from ....core.review.model import Event
from ..local_store.lines import lines_text


def history_folder() -> str:
    """Where the review history is kept: ~/.difftate/history/."""
    return os.path.join(os.path.expanduser("~"), ".difftate", "history")


class HistoryFiles:
    def __init__(self, about: Dict[str, Any], folder: Optional[str] = None) -> None:
        """<about>: the review the events come from, added to each line.
        <folder>: where the files go (history_folder() when not given)."""
        self.about = about
        self.folder = folder or history_folder()

    def record(self, events: List[Event]) -> None:
        """Add <events> to this month's file. A history that can't be written
        is a warning: the review goes on, as today (local.py)."""
        if not events:
            return
        month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        try:
            os.makedirs(self.folder, mode=0o700, exist_ok=True)
            with open(os.path.join(self.folder, f"{month}.jsonl"), "a", encoding="utf-8") as f:
                f.write(lines_text(events, self.about))
        except OSError as e:
            print(f"Warning: could not write the review history ({e})")
