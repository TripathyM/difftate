"""Choosing the agent of one review, or clearing the choice (GLOSSARY.md, Agent override)."""
from __future__ import annotations

from ..model import NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def set_agent_override(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
                       author: str, agent: str) -> str:
    """The review's agent chosen as <author> says: <agent>, or "" to clear the
    choice. The answer is the choice kept. Nothing is kept for the choice it
    has already. Raises NotAllowed for anyone but a reviewer, and CouldNotRead
    when the change can't be kept; nothing is kept then. Whether <agent> is
    on the machine's list is for the caller to check."""
    review = Review.from_events(store.load() + notes.events())
    events = review.set_agent_override(author, agent)
    store.append(lasting(events))
    history.record(lasting(events))
    return review.agent_override()
