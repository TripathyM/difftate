"""What is checked out: the review's branch, or another one whose review the
watcher moves to once the run in progress ends."""
from __future__ import annotations

from ..model import CheckedOut
from ..ports import ForReadingTheCode


def checked_out(code: ForReadingTheCode) -> CheckedOut:
    """Whether the review's branch is checked out now, and what a review of
    the checkout would be of."""
    return CheckedOut(code.on_branch(), code.checked_out_branch())
