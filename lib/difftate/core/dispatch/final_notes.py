"""The final line of a progress note, written through the Review: for end_run
and recover_runs."""
from __future__ import annotations

from typing import Collection, Optional

from ..review.model import DIFFTATE, ReviewError, Thread
from .model import TAMPERED, no_reply
from .ports import ReviewForDispatch


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

