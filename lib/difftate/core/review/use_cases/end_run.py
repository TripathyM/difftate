"""Ending a run: the threads it didn't reply to are failed."""
from __future__ import annotations

from typing import List

from ..model import NotesInProgress, Review, Thread, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def end_run(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
            outcome: str) -> List[Thread]:
    """The run in progress ended (<outcome>: done, failed or stopped); its end
    is kept and recorded. Returns the open threads it left failed: no reply to
    them. Nothing is kept when no run is in progress. Raises CouldNotRead when
    the end can't be kept."""
    review = Review.from_events(store.load() + notes.events())
    ran = review.in_progress()
    events = review.end_run(outcome)
    if events:
        store.append(lasting(events))
        history.record(lasting(events))
    return review.failed_among(ran)
