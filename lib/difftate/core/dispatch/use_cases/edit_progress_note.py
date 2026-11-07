"""Editing the progress notes while a run works: its steps, and the time."""
from __future__ import annotations

from ...review.model import DIFFTATE, ReviewError
from ..model import REFRESH_S, Dispatch


def edit_progress_note(dispatch: Dispatch) -> None:
    """The run in progress's progress notes show its steps so far. They are
    edited when the run took a step or finished, and every REFRESH_S seconds
    meanwhile, so the elapsed time moves. They aren't final: the run's end
    writes their last line (end_run)."""
    run = dispatch.run
    if run is None:
        return
    now = dispatch.clock()
    if not run.changed and now - run.edited < REFRESH_S:
        return
    body = run.progress.render(dispatch.secs(run.started))
    for note_id in run.notes.values():
        try:
            dispatch.review.edit_note(DIFFTATE, note_id, "progress", body)
        except ReviewError:
            pass
    run.edited, run.changed = now, False
