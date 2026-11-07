"""The Review's driven ports: what the Review needs from outside the core.

Each is a typing.Protocol: any object with these methods plugs in, with no
base class to inherit. The adapters in difftate/adapters/outbound/ do.
"""
from __future__ import annotations

from typing import List, Protocol

from .model import Event


class ForKeepingTheReview(Protocol):
    """Keeps a review's events. A store applies no rules and changes nothing:
    the Review decides, and the store keeps what it decided. That includes
    which events last: the core gives a store no note that isn't final yet
    (model.lasting, model.NotesInProgress), so a store keeps every event it
    is given."""

    def load(self) -> List[Event]:
        """Every event of the review, oldest first."""
        ...

    def append(self, events: List[Event]) -> None:
        """Keep <events> after the ones already kept."""
        ...


class ForRecordingReviewHistory(Protocol):
    """The review history: every thread, comment and reply from every review
    on this machine, never deleted."""

    def record(self, events: List[Event]) -> None:
        """Add <events> to the review history: the same events the store
        keeps, never a note that isn't final yet."""
        ...
