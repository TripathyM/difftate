"""A review whose branch no served folder has checked out: its waiting
threads wait, and say so."""
from __future__ import annotations

from ...review.model import DIFFTATE, ReviewError
from ..model import NO_BRANCH_NOTE, Dispatch, queued, waiting
from .dispatch_waiting import every_thread


def hold_for_branch(dispatch: Dispatch, branch: str) -> None:
    """Each waiting or queued thread of the review gets a note saying to check
    <branch> out: a thread that has a queued note has its text changed. Nothing
    else changes: the next run takes the note as its progress note (or marks
    it picked up), as it does a queued note, so it goes when the run starts."""
    listed = every_thread(dispatch)
    text = NO_BRANCH_NOTE.format(branch=branch)
    for t in waiting(listed) + queued(listed):
        try:
            if t.id in dispatch.queued:
                dispatch.review.edit_note(DIFFTATE, dispatch.queued[t.id], "queued", text)
            else:
                dispatch.queued[t.id] = dispatch.review.add_comment(DIFFTATE, t.id, "queued", text).id
        except ReviewError:
            continue
