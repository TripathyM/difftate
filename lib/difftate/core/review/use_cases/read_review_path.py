"""Reading the review path: the coding agent's reading order for the
review's changed files, from the text of review-path.md as it is now."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory
from ..review_path import ReviewPath, parse
from .list_viewed import list_viewed


def read_review_path(store: ForKeepingTheReview, code: ForReadingTheCode,
                     history: ForRecordingReviewHistory) -> Optional[ReviewPath]:
    """The review path, each stop with the reviewer's viewed mark for its file
    (as list_viewed has them); None when the folder has no review-path.md.
    The text is read each time, so a rewrite shows on the next call. Raises
    CouldNotRead when the file or the changeset can't be read."""
    text = code.review_path_text()
    if text is None:
        return None
    return parse(text).with_viewed(list_viewed(store, code, history))
