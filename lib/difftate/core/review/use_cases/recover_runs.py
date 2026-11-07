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
    ran = review.in_progress()
    events = review.recover_runs()
    if events:
        store.append(lasting(events))
        history.record(lasting(events))
    return review.failed_among(ran)
