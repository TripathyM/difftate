"""Checking the review path: why review-path.md can't be used, or why it is
out of date, for a warning about the review."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..model import CouldNotRead
from ..review_path import BadReviewPath, parse


def review_path_problem(code: ForReadingTheCode) -> Optional[str]:
    """What is wrong with the folder's review-path.md, as a line a viewer shows
    as a warning; None when there is no file or it reads as a review path of
    this changeset. A path that can't be read is not used; a path naming files
    with no changes is used, out of date: the line names those files first, so
    a narrow notification still shows them. The file is read each time, so a
    fixed one has no problem on the next call. Writes nothing: the viewed marks
    are not read. While another branch is checked out the file is that
    branch's: no problem is said."""
    try:
        if not code.on_branch():
            return None
        text = code.review_path_text()
        if text is None:
            return None
        gone = parse(text).against(code.diff_hashes()).out_of_date()
    except (BadReviewPath, CouldNotRead) as e:
        return f"review-path.md is not used, files are in the changeset's order: {e}"
    if not gone:
        return None
    names = ", ".join(f"`{f}`" for f in gone)
    return f"review-path.md is out of date: {names} {'has' if len(gone) == 1 else 'have'} no changes. Ask the agent to rewrite it"
