"""Opening a thread: a reviewer writes the first comment, on an anchor or on
the changeset as a whole."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..model import Anchor, NotesInProgress, Review, Thread, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def open_thread(store: ForKeepingTheReview, notes: NotesInProgress, code: ForReadingTheCode,
                history: ForRecordingReviewHistory, author: str, body: str,
                anchor: Optional[Anchor] = None) -> Thread:
    """A thread on <anchor> (None: a general thread), with <author>'s comment
    <body>. Raises NotAllowed for anyone but a reviewer, Conflict while another
    branch is checked out, and CouldNotRead when the code can't be read;
    nothing is kept then."""
    review = Review.from_events(store.load() + notes.events())  # notes too: a comment's seq comes after them
    on_branch = code.on_branch()
    snapshot = None
    if anchor is not None and on_branch:  # off the branch, the files on disk aren't this review's
        snapshot = code.snapshot(anchor.file, anchor.side, anchor.view, anchor.start_line, anchor.end_line)
    events = review.open_thread(author, body, anchor, snapshot, on_branch)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.thread(events[0].thread_id)  # events[0] is the ThreadOpened
