"""Recovering runs: a watcher killed during a run left it in progress."""
from __future__ import annotations

from typing import List

from ..model import NotesInProgress, Review, Thread, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def recover_runs(store: ForKeepingTheReview, notes: NotesInProgress,
                 history: ForRecordingReviewHistory) -> List[Thread]:
    """When a watcher opens a review: a run that never ended (its watcher was
    killed) ends as interrupted, kept and recorded. Returns the open threads
    such a run left failed: no reply to them. Raises CouldNotRead when the
    end can't be kept."""
    review = Review.from_events(store.load() + notes.events())
    ran = {tid for run in review.runs() if run.outcome is None for tid in run.threads}
    events = review.recover_runs()
    if events:
        store.append(lasting(events))
        history.record(lasting(events))
    return [t for t in review.threads("open") if t.id in ran and review.state(t.id) == "failed"]
