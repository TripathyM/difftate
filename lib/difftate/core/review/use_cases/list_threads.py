"""Listing threads, each with its thread state."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import Review, Thread
from ..ports import ForKeepingTheReview


def list_threads(store: ForKeepingTheReview, status: Optional[str] = None) -> List[Tuple[Thread, Optional[str]]]:
    """The threads, oldest first, each with its thread state (None for a
    resolved or dismissed thread). With a <status>, only those with it."""
    review = Review.from_events(store.load())
    return [(thread, review.state(thread.id)) for thread in review.threads(status)]
