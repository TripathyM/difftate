"""Listing threads, each with its thread state."""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..model import NotesInProgress, Review, Thread
from ..ports import ForKeepingTheReview


def list_threads(store: ForKeepingTheReview, notes: NotesInProgress,
                 status: Optional[str] = None) -> List[Tuple[Thread, Optional[str]]]:
    """The threads, oldest first, with the notes that aren't final yet, each
    with its thread state (None for a resolved or dismissed thread). With a
    <status>, only those with it."""
    review = Review.from_events(store.load() + notes.events())
    return [(thread, review.state(thread.id)) for thread in review.threads(status)]
