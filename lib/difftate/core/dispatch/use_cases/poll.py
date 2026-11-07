"""One poll of the loop: what the timer calls every interval (the driving
port for running the loop)."""
from __future__ import annotations

from typing import Callable

from ..model import Dispatch
from ..ports import ForAskingTheCodingAgent, ForReporting
from .dispatch_waiting import dispatch_waiting
from .edit_progress_note import edit_progress_note
from .end_run import end_run
from .move_with_code import move_with_code
from .post_replies import post_replies
from .read_news import read_news


def poll(dispatch: Dispatch, agent: ForAskingTheCodingAgent, report: ForReporting,
         between_runs: Callable[[], None] = lambda: None) -> None:
    """While a run is in progress: its news, its replies, threads moved with
    their code, queued notes and its progress notes; once it is over, its end.
    Between runs: <between_runs> first (the watcher may switch dispatch.review
    there), then the threads move with their code, and the waiting ones are
    dispatched. A run whose end the store couldn't keep is kept before
    anything else."""
    run = dispatch.run
    if run is not None:
        exited = read_news(dispatch, report)
        post_replies(dispatch, report)
        if exited is not None:
            if exited:
                report.warning(f"dispatch to {agent.name} failed (exit {exited})")
            end_run(dispatch, report, "failed" if exited else "done")
            return
        move_with_code(dispatch.review, report)
        dispatch_waiting(dispatch, agent, report)
        edit_progress_note(dispatch)
        return
    if dispatch.unended and not dispatch.unended():
        return  # the last run is still in progress until its end is kept
    between_runs()
    move_with_code(dispatch.review, report)
    dispatch_waiting(dispatch, agent, report)
