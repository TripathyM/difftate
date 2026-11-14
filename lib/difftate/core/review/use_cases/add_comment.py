"""Adding a comment: a reviewer's comment, the coding agent's reply or
difftate's note, at the end of a thread."""
from __future__ import annotations

from typing import Optional

from ..model import Comment, NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def add_comment(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
                author: str, thread_id: str, kind: str, body: str, by: Optional[str] = None) -> Comment:
    """<author>'s <kind> ("comment", "reply", "queued" or "progress") with <body>
    at the end of the thread; <by>: the reviewer name of a reviewer's comment.
    Raises NotFound for no such thread, and NotAllowed when <kind> isn't
    <author>'s to write or <by> names a non-reviewer; nothing is kept then. A
    note isn't final yet: <notes> holds it, and neither the store nor the
    review history gets it."""
    review = Review.from_events(store.load() + notes.events())
    events = review.add_comment(author, thread_id, kind, body, by)
    notes.hold(events)
    kept = lasting(events)
    if kept:
        store.append(kept)
        history.record(kept)
    return events[0].comment
