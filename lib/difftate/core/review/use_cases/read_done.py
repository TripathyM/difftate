"""Reading whether the review is Done: for a viewer, or a script outside
difftate."""
from __future__ import annotations

from ...changes.ports import ForReadingTheCode
from ..model import DoneStatus, Review
from ..ports import ForKeepingTheReview


def read_done(store: ForKeepingTheReview, code: ForReadingTheCode) -> DoneStatus:
    """Whether the review is Done with its branch where it is now, and the
    threads still open. It keeps nothing, so it is safe beside a watcher that
    keeps the review: a new commit that cleared Done shows as cleared here,
    and the watcher keeps the clearing (clear_done)."""
    return Review.from_events(store.load()).done_status(code.head_commit())
