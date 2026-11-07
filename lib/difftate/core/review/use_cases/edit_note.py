"""Editing a note: difftate changes a queued or progress note in its place."""
from __future__ import annotations

from ..model import Comment, NotesInProgress, NoteWritten, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def edit_note(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
              author: str, note_id: str, kind: str, body: str, final: bool = False) -> Comment:
    """The note with <kind> ("queued" or "progress") and <body>, in its place.
    <final> when it won't change again (a run's last line): only then do the
    store and the review history get it; until then <notes> holds it. Raises
    NotFound for no such note, NotAllowed for anyone but difftate or for a
    comment or reply, and Conflict for a note that is final; nothing changes
    then."""
    review = Review.from_events(store.load() + notes.events())
    events = review.edit_note(author, note_id, kind, body, final)
    notes.hold(events)
    kept = lasting(events)
    if kept:
        store.append(kept)
        history.record(kept)
    return next(e.comment for e in events if isinstance(e, NoteWritten))
