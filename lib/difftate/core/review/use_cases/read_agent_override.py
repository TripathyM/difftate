"""Reading the agent chosen for one review: for a viewer, or the run that starts."""
from __future__ import annotations

from ..model import Review
from ..ports import ForKeepingTheReview


def read_agent_override(store: ForKeepingTheReview) -> str:
    """The agent a reviewer chose for this review: "" when none. It keeps nothing."""
    return Review.from_events(store.load()).agent_override()
