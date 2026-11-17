"""Clearing Done when the branch gets a new commit (GLOSSARY.md, Done)."""
from __future__ import annotations

from ...review.model import CouldNotRead
from ..ports import ForReporting, ReviewForDispatch


def clear_done(review: ReviewForDispatch, report: ForReporting) -> None:
    """A review Done at an older commit than its branch is at now is cleared:
    the Review keeps the clearing, with the new commit. A clearing that can't
    be kept is a warning, and the loop goes on: the next poll tries again."""
    try:
        review.clear_done()
    except CouldNotRead as e:
        report.warning(f"could not keep that the review is no longer Done ({e})")
