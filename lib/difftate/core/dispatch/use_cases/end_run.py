"""Ending a run: its last replies are posted, the threads it didn't reply to
are failed, and every progress note gets its final line."""
from __future__ import annotations

from typing import Collection, Optional

from ...review.model import DIFFTATE, CouldNotRead, ReviewError, Thread
from ..model import TAMPERED, WATCHER_STOPPED, Dispatch, no_reply, stopped
from ..ports import ForReporting, ReviewForDispatch
from .post_replies import post_replies
from .read_news import read_news


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
            warn_once(dispatch, report, f"could not record the end of the run ({e}): "
                                        "no run starts until it is recorded")
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


def stop_run(dispatch: Dispatch, report: ForReporting, say: bool = True) -> None:
    """Stop the run in progress, and everything it started. Its last replies
    are posted; its threads with no reply fail ("the watcher stopped")."""
    run = dispatch.run
    if run is None:
        return
    if say:
        report.stopping(run.handle.pid)
    run.handle.stop()
    read_news(dispatch, report, replies_only=True)  # the replies it left
    end_run(dispatch, report, "stopped", WATCHER_STOPPED, say=False)


def warn_once(dispatch: Dispatch, report: ForReporting, text: str) -> None:
    """A failing store isn't warned about on every poll."""
    if text != dispatch.warned:
        report.warning(text)
    dispatch.warned = text


def fail_thread(review: ReviewForDispatch, thread: Thread, secs: Optional[int], why: str = "",
                note_id: Optional[str] = None, failed_ending: Optional[str] = None,
                tampered: Collection[str] = ()) -> None:
    """The run's progress note on <thread> (<note_id>; a new one when it has
    none) ends as failed, with "no reply" (and <why>). <secs> None: the run's
    length isn't known. When the coding agent said the run failed
    (<failed_ending>), the note keeps why, and adds that this thread got no
    reply."""
    text = no_reply(secs, why)
    if note_id is None:
        try:
            note_id = review.add_comment(DIFFTATE, thread.id, "progress", text).id
        except ReviewError:
            return
        body = text
    elif failed_ending:
        body = f"{failed_ending}\n\nNo reply{why}."
    else:
        body = text
    final_line(review, thread.id, note_id, body, tampered)


def final_line(review: ReviewForDispatch, thread_id: str, note_id: str, body: str,
               tampered: Collection[str] = ()) -> None:
    if thread_id in tampered:
        body += f"\n\n{TAMPERED}"
    try:
        review.edit_note(DIFFTATE, note_id, "progress", body, final=True)
    except ReviewError:
        pass

