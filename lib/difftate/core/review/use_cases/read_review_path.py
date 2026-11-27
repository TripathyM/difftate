"""Reading the review path: the coding agent's reading order for the
review's changed files, from the text of review-path.md as it is now."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory
from ..review_path import ReviewPath, parse
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
    of shape, a file named twice. A file it names that is not in the changeset
    is marked so (in_changeset) on its stop, side file or skipped file, and is
    on the path in every view: the path is out of date, not broken."""
    text = code.review_path_text()
    if text is None:
        return None
    changed = list(code.diff_hashes())
    path = parse(text).against(changed)
    viewed = list_viewed(store, code, history)
    path = path.with_viewed(viewed)
    if view:
        changed = list(code.changeset(view).versions)  # the files of the view, in the changeset's order
        path = path.cut_to([*changed, *path.out_of_date()])  # a file with no changes is in no view: kept in each
    return path.with_changed_files(changed)
