"""The Review's driven ports: what the Review needs from outside the core.

Each is a typing.Protocol: any object with these methods plugs in, with no
base class to inherit. The adapters in difftate/adapters/outbound/ do.
"""
from __future__ import annotations

from typing import List, Protocol

from .model import Event


class ForKeepingTheReview(Protocol):
    """Keeps a review's events. A store applies no rules and changes nothing:
    the Review decides, and the store keeps what it decided."""

    def load(self) -> List[Event]:
        """Every event of the review, oldest first."""
        ...

    def append(self, events: List[Event]) -> None:
        """Keep <events> after the ones already kept. A note that isn't final
        yet (NoteWritten, final False) need last only as long as this process:
        load() returns it until then, and a store may keep only what
        model.lasting() keeps for good."""
        ...


class ForRecordingReviewHistory(Protocol):
    """The review history: every thread, comment and reply from every review
    on this machine, never deleted."""

    def record(self, events: List[Event]) -> None:
        """Add <events> to the review history. The use cases record only the
        events that last (model.lasting): no note that isn't final yet."""
        ...
