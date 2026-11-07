"""Moving the threads with their code, and saying which became outdated."""
from __future__ import annotations

from ...review.model import CouldNotRead
from ..ports import ForReporting, ReviewForDispatch


def move_with_code(review: ReviewForDispatch, report: ForReporting) -> None:
    """Each thread moves with its code, or is outdated (the Review decides):
    each outdated thread is reported. Code that can't be read is a warning,
    and the loop goes on."""
    try:
        for tid in review.move_with_code():
            report.outdated(tid)
    except CouldNotRead as e:
        report.warning(f"could not follow the threads' code ({e})")
