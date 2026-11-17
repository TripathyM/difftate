"""Clearing Done: a new commit on the branch ends it (GLOSSARY.md, Done)."""
from __future__ import annotations

from ...changes.ports import ForReadingTheCode
from ..model import Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def clear_done(store: ForKeepingTheReview, code: ForReadingTheCode, history: ForRecordingReviewHistory) -> bool:
    """A review Done at another commit than its branch is at now is cleared,
    and the clearing kept and recorded with the new commit; returns whether
    it was. It works whichever branch is checked out. Nothing is kept for a
    review that isn't Done, is Done at this commit, or whose branch is gone.
    Raises CouldNotRead when the clearing can't be kept."""
    review = Review.from_events(store.load())
    events = review.clear_done(code.head_commit())
    store.append(lasting(events))
    history.record(lasting(events))
    return bool(events)
