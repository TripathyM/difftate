"""Recovering runs: a watcher killed during a run left its threads working."""
from __future__ import annotations

from ..model import WATCHER_STOPPED
from ..ports import ForReporting, ReviewForDispatch
from ..final_notes import fail_thread


def recover_runs(review: ReviewForDispatch, report: ForReporting) -> None:
    """When the watcher opens a review: a run that never ended (its watcher was
    killed) ends as interrupted, and each of its threads with no reply fails,
    with a progress note that says so. Raises CouldNotRead when the end can't
    be kept."""
    for t in review.recover_runs():
        report.no_reply(t.id, True)
        fail_thread(review, t, None, WATCHER_STOPPED)
