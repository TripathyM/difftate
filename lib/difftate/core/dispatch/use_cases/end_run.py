"""Ending a run: its last replies are posted, the threads it didn't reply to
are failed, and every progress note gets its final line."""
from __future__ import annotations

from ...review.model import CouldNotRead
from ..final_notes import fail_thread, final_line
from ..model import Dispatch, stopped
from ..ports import ForReporting
from .post_replies import post_replies


def end_run(dispatch: Dispatch, report: ForReporting, outcome: str = "done", why: str = "",
            say: bool = True) -> None:
    """The run in progress ended: <outcome> done, failed or stopped (the
    watcher stopped it). <why> is added to the "no reply" line; <say> False
    reports no thread left with no reply.

    The run's end is kept first. When the store can't keep it, the run is
    still in progress in the review: poll tries again before anything else,
    so no other run starts first."""
    run = dispatch.run
    if run is None:
        return
    post_replies(dispatch, report, last_try=True)
    dispatch.run = None
    secs = dispatch.secs(run.started)
    progress = run.progress
    ending = progress.render(run.ending_secs or 0) if progress.finished else None  # how the coding agent said it ended
    failed_ending = ending if progress.state == "failed" else None
    review, notes, tampered = dispatch.review, run.notes, run.tampered

    def close() -> bool:
        try:
            failed = review.end_run(outcome)
            thread_ids = {t.thread.id for t in review.list_threads()}
        except CouldNotRead as e:
            text = f"could not record the end of the run ({e}): no run starts until it is recorded"
            if dispatch.should_warn(text):
                report.warning(text)
            return False
        dispatch.unended, dispatch.warned = None, None
        for t in failed:
            if say:
                report.no_reply(t.id, False)
            fail_thread(review, t, secs, why, notes.get(t.id), failed_ending, tampered)
        failed_ids = {t.id for t in failed}
        for tid, note_id in notes.items():
            if tid not in failed_ids and tid in thread_ids:
                body = ending or (stopped(secs) if outcome == "stopped" else f"✅ **Done** in {secs}s")
                final_line(review, tid, note_id, body, tampered)
        return True

    dispatch.unended = close
    close()
