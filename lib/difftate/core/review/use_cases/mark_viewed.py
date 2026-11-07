"""Marking a file viewed: the reviewer has read a file of the changeset as its
diff is now, or unmarks it."""
from __future__ import annotations

from typing import List

from ...changes.ports import ForReadingTheCode
from ..model import Review
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def mark_viewed(store: ForKeepingTheReview, code: ForReadingTheCode, history: ForRecordingReviewHistory,
                file: str, viewed: bool = True) -> List[str]:
    """<file> viewed (or unmarked, <viewed> False); returns the files viewed, in
    order. Marks whose diff changed since are cleared too. Raises NotFound for a
    file not in the changeset, Conflict while another branch is checked out, and
    CouldNotRead when the changeset can't be read; nothing is kept then."""
    review = Review.from_events(store.load())
    on_branch = code.on_branch()
    # Off the branch, the files on disk aren't this review's
    diff_hashes = code.diff_hashes() if on_branch else {}
    events = review.mark_viewed(file, viewed, diff_hashes, on_branch)
    events += review.clear_changed_marks(diff_hashes)
    store.append(events)
    history.record(events)
    return sorted(review.viewed())
