"""Stopping the run in progress: the watcher stops."""
from __future__ import annotations

from ..model import WATCHER_STOPPED, Dispatch, NotStarted
from ..ports import ForReporting
from .end_run import end_run
from .read_news import read_news


def stop_run(dispatch: Dispatch, report: ForReporting, say: bool = True) -> None:
    """Stop the run in progress, and everything it started. Its last replies
    are posted; its threads with no reply fail ("the watcher stopped")."""
    run = dispatch.run
    if run is None:
        return
    if say and not isinstance(run.handle, NotStarted):
        report.stopping(run.handle.pid)
    run.handle.stop()
    read_news(dispatch, report, stopped=True)  # what it did last, and the replies it left
    end_run(dispatch, report, "stopped", WATCHER_STOPPED, say=False)
