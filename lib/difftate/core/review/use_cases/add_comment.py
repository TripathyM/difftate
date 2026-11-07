"""Adding a comment: a reviewer's comment, the coding agent's reply or
difftate's note, at the end of a thread."""
from __future__ import annotations

from ..model import Comment, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def add_comment(store: ForKeepingTheReview, history: ForRecordingReviewHistory,
                author: str, thread_id: str, kind: str, body: str) -> Comment:
    """<author>'s <kind> ("comment", "reply", "queued" or "progress") with <body>
    at the end of the thread. Raises NotFound for no such thread, and
    NotAllowed when <kind> isn't <author>'s to write; nothing is kept then. A
    note is kept only for this process until it is final."""
    review = Review.from_events(store.load())
    [event] = review.add_comment(author, thread_id, kind, body)
    store.append([event])
    history.record(lasting([event]))
    return event.comment
