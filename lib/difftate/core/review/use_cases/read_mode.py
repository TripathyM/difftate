"""Reading the review mode and the held threads: for a viewer, or a reviewing
agent that wants to know whether its comments are answered now."""
from __future__ import annotations

from ..model import ModeStatus, Review
from ..ports import ForKeepingTheReview


def read_mode(store: ForKeepingTheReview) -> ModeStatus:
    """The review mode, and the threads held. It keeps nothing."""
    return Review.from_events(store.load()).mode_status()
