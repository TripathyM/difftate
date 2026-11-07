"""Listing viewed files: the files the reviewer marked viewed whose diff
hasn't changed since."""
from __future__ import annotations

from typing import List

from ...changes.ports import ForReadingTheCode
from ..model import Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def list_viewed(store: ForKeepingTheReview, code: ForReadingTheCode,
                history: ForRecordingReviewHistory) -> List[str]:
    """The files viewed, in order. A mark whose file's diff changed is cleared
    (and kept so), so undoing the change doesn't bring it back. While another
    branch is checked out, the marks stay as they are and the code isn't read.
    Raises CouldNotRead when the changeset can't be read."""
    review = Review.from_events(store.load())
    if code.on_branch():
        events = review.clear_changed_marks(code.diff_hashes())
        if events:
            store.append(lasting(events))
            history.record(lasting(events))
    return sorted(review.viewed())
