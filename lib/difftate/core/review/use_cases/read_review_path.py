"""Reading the review path: the coding agent's reading order for the
review's changed files, from the text of review-path.md as it is now."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory
from ..review_path import ReviewPath, check_files, parse
from .list_viewed import list_viewed


def read_review_path(store: ForKeepingTheReview, code: ForReadingTheCode,
                     history: ForRecordingReviewHistory, view: str = "") -> Optional[ReviewPath]:
    """The review path, each stop with the reviewer's viewed mark for its file
    (as list_viewed has them) and the changed files it names nowhere; None
    when the folder has no review-path.md.
    In <view> ("" for all changes) the path is cut down to the view's files,
    their numbers kept, and "not on the path" is the view's files only. The
    file is checked against all changes, whatever the view: a broken path is
    broken in every view. Raises NotFound when <view> is no view.
    The text is read each time, so a rewrite shows on the next call. Raises
    CouldNotRead when the file or the changeset can't be read, and
    BadReviewPath when the file can't be read as a review path: a heading out
    of shape, a file named twice, a file not in the changeset."""
    text = code.review_path_text()
    if text is None:
        return None
    path = parse(text)
    changed = list(code.diff_hashes())
    check_files(path, changed)
    viewed = list_viewed(store, code, history)
    path = path.with_viewed(viewed)
    if view:
        changed = list(code.changeset(view).versions)  # the files of the view, in the changeset's order
        path = path.cut_to(changed)
    return path.with_changed_files(changed)
