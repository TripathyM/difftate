"""Marking the review Done, or undoing it: the reviewer has finished the review
at the commit the branch is at (GLOSSARY.md, Done)."""
from __future__ import annotations

from ...changes.ports import ForReadingTheCode
from ..model import CouldNotRead, DoneStatus, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def set_done(store: ForKeepingTheReview, code: ForReadingTheCode, history: ForRecordingReviewHistory,
             author: str, done: bool = True) -> DoneStatus:
    """The review Done at the commit its branch is at (or, <done> False, not
    Done), as <author> says. A review Done at an older commit was cleared by
    the new one: that is kept first. Nothing is kept for a review already as
    asked. Raises NotAllowed for anyone but a reviewer, Conflict when marking
    while another branch is checked out, and CouldNotRead when there is no
    commit to be Done at (marking) or the mark can't be kept; nothing is kept
    then. A Done keeps the text of review-path.md as it is then (none, with no
    file)."""
    review = Review.from_events(store.load())
    head = code.head_commit()
    if done:
        events = review.mark_done(author, head, code.on_branch(), _review_path_now(code))
    else:
        events = review.undo_done(author, head)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.done_status(head)


def _review_path_now(code: ForReadingTheCode):
    """The review path's text, or None: a path that can't be read never stops
    a review from being Done."""
    try:
        return code.review_path_text()
    except CouldNotRead:
        return None
