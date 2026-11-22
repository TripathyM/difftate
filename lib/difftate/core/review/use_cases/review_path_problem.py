"""Checking the review path: why review-path.md can't be used, for a warning
about the review."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..model import CouldNotRead
from ..review_path import BadReviewPath, check_files, parse


def review_path_problem(code: ForReadingTheCode) -> Optional[str]:
    """What is wrong with the folder's review-path.md, as a line a viewer shows
    as a warning; None when there is no file or it reads as a review path. The
    file is read each time, so a fixed one has no problem on the next call.
    Writes nothing: the viewed marks are not read."""
    try:
        text = code.review_path_text()
        if text is None:
            return None
        check_files(parse(text), code.diff_hashes())
    except BadReviewPath as e:
        problem = str(e)
    except CouldNotRead as e:
        problem = str(e)
    else:
        return None
    return f"review-path.md is not used, files are in the changeset's order: {problem}"
