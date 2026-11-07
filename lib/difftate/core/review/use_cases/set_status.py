"""Setting a thread status: a reviewer opens, resolves or dismisses a thread."""
from __future__ import annotations

from ..model import NotesInProgress, Review, Thread, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def set_status(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
               author: str, thread_id: str, status: str) -> Thread:
    """The thread with <status> ("open", "resolved" or "dismissed"). Raises
    NotFound for no such thread, and NotAllowed for anyone but a reviewer;
    nothing is kept then."""
    review = Review.from_events(store.load() + notes.events())
    events = review.set_status(author, thread_id, status)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.thread(thread_id)
