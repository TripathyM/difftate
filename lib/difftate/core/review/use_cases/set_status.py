"""Setting a thread status: a reviewer opens, resolves or dismisses a thread."""
from __future__ import annotations

from ..model import Review, Thread
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def set_status(store: ForKeepingTheReview, history: ForRecordingReviewHistory,
               author: str, thread_id: str, status: str) -> Thread:
    """The thread with <status> ("open", "resolved" or "dismissed"). Raises
    NotFound for no such thread, and NotAllowed for anyone but a reviewer;
    nothing is kept then."""
    review = Review.from_events(store.load())
    events = review.set_status(author, thread_id, status)
    store.append(events)
    history.record(events)
    return review.thread(thread_id)
