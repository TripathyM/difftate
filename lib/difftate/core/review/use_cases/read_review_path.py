"""Reading the review path: the coding agent's reading order for the
review's changed files, from the text of review-path.md as it is now."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory
from ..review_path import ReviewPath, check_files, parse
from .list_viewed import list_viewed


def read_review_path(store: ForKeepingTheReview, code: ForReadingTheCode,
                     history: ForRecordingReviewHistory) -> Optional[ReviewPath]:
    """The review path, each stop with the reviewer's viewed mark for its file
    (as list_viewed has them) and the changed files it names nowhere; None when the folder has no review-path.md.
    The text is read each time, so a rewrite shows on the next call. Raises
    CouldNotRead when the file or the changeset can't be read, and
    BadReviewPath when the file can't be read as a review path: a heading out
    of shape, a file named twice, a file not in the changeset."""
    text = code.review_path_text()
    if text is None:
        return None
    path = parse(text)
    check_files(path, code.diff_hashes())
    viewed = list_viewed(store, code, history)
    return path.with_viewed(viewed).with_changed_files(list(code.diff_hashes()))
