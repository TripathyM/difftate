"""Changing the review mode: live or batched (GLOSSARY.md, Review mode)."""
from __future__ import annotations

from ..model import ModeStatus, NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def set_mode(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
             author: str, mode: str) -> ModeStatus:
    """The review in <mode>, as <author> says. A change from batched to live
    submits the held threads: the answer names them. Nothing is kept for a
    review in <mode> already. Raises NotAllowed for anyone but a reviewer,
    ValueError for a mode that isn't one, and CouldNotRead when the change
    can't be kept; nothing is kept then."""
    review = Review.from_events(store.load() + notes.events())
    events = review.set_mode(author, mode)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.mode_status(events)
