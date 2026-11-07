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
    ran = {tid for run in review.runs() if run.outcome is None for tid in run.threads}
    events = review.end_run(outcome)
    if events:
        store.append(lasting(events))
        history.record(lasting(events))
    return [t for t in review.threads("open") if t.id in ran and review.state(t.id) == "failed"]
