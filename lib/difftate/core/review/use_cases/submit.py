"""Submitting a batched review: its held threads go to the coding agent, as
one run (GLOSSARY.md, Submit)."""
from __future__ import annotations

from ..model import ModeStatus, NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def submit(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
           author: str) -> ModeStatus:
    """<author> submits the review: its held threads become waiting, and
    Dispatch sends them as one run, or queues them while a run is busy. The
    answer names them: none when none was held, and then nothing is kept.
    Raises NotAllowed for anyone but a reviewer, and CouldNotRead when the
    submit can't be kept; nothing is kept then."""
    review = Review.from_events(store.load() + notes.events())
    held = [t.id for t in review.held()]
    events = review.submit(author)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.mode_status(submitted=held if events else ())
