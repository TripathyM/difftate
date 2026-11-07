"""Opening a thread: a reviewer writes the first comment, on an anchor or on
the changeset as a whole."""
from __future__ import annotations

from typing import Optional

from ...changes.ports import ForReadingTheCode
from ..model import REVIEWER, Anchor, Review, Thread
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def open_thread(store: ForKeepingTheReview, code: ForReadingTheCode, history: ForRecordingReviewHistory,
                body: str, anchor: Optional[Anchor] = None, author: str = REVIEWER) -> Thread:
    """A thread on <anchor> (None: a general thread), with <author>'s comment
    <body>. Raises NotAllowed for anyone but a reviewer, and CouldNotRead when
    the code can't be read; nothing is kept then."""
    review = Review.from_events(store.load())
    snapshot = None
    if anchor is not None:
        snapshot = code.snapshot(anchor.file, anchor.side, anchor.view, anchor.start_line, anchor.end_line)
    events = review.open_thread(author, body, anchor, snapshot)
    store.append(events)
    history.record(events)
    return review.thread(events[0].thread_id)
