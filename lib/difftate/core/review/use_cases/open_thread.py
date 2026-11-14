"""Opening a thread: a reviewer writes the first comment, on an anchor or on
the changeset as a whole."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..model import Anchor, ListedThread, NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def open_thread(store: ForKeepingTheReview, notes: NotesInProgress, code: ForReadingTheCode,
                history: ForRecordingReviewHistory, author: str, body: str,
                anchor: Optional[Anchor] = None) -> ListedThread:
    """A thread on <anchor> (None: a general thread), with <author>'s comment
    <body>, and its thread state now. Raises NotAllowed for anyone but a
    reviewer, Conflict while another branch is checked out, and CouldNotRead
    when the code can't be read; nothing is kept then."""
    review = Review.from_events(store.load() + notes.events())  # notes too: a comment's seq comes after them
    on_branch = code.on_branch()
    snapshot = None
    if anchor is not None and on_branch:  # off the branch, the files on disk aren't this review's
        snapshot = code.snapshot(anchor.file, anchor.side, anchor.view, anchor.start_line, anchor.end_line)
    events = review.open_thread(author, body, anchor, snapshot, on_branch)
    if snapshot is not None:
        code.keep(review.snapshots())  # so git gc can't take it
    store.append(lasting(events))
    history.record(lasting(events))
    thread_id = events[0].thread_id  # events[0] is the ThreadOpened
    return ListedThread(review.thread(thread_id), review.state(thread_id))
