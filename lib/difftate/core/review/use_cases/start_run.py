"""Starting a run: the waiting threads go to the coding agent, with every
reviewer comment no run was sent yet."""
from __future__ import annotations

from typing import Sequence

from ..model import NotesInProgress, Review, Run, Thread, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def start_run(store: ForKeepingTheReview, notes: NotesInProgress, history: ForRecordingReviewHistory,
              threads: Sequence[Thread]) -> Run:
    """A run on <threads>, as Dispatch read them for the run's prompt. It is
    sent the reviewer comments in them that no run was sent: a comment written
    since they were read isn't in the prompt, so it waits for the next run.
    The run is kept and recorded before the coding agent starts, so a
    restarted watcher doesn't send it again. Raises NotFound for a thread the
    review doesn't have, and CouldNotRead when the run can't be kept; no run
    starts then."""
    review = Review.from_events(store.load() + notes.events())
    events = review.start_run([t.id for t in threads], seen={c.id for t in threads for c in t.comments})
    store.append(lasting(events))
    history.record(lasting(events))
    return review.runs()[-1]
