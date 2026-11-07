"""Reading the run's news: what the coding agent did since the last poll."""
from __future__ import annotations

from typing import Optional

from ..model import (
    NOT_FINISHED, AgentSessionStarted, ContextUsed, Dispatch, Exited, Finished, ModelChosen, Output, Reply, Said, Step,
    Unparsed,
)
from ..ports import ForReporting


def read_news(dispatch: Dispatch, report: ForReporting, stopped: bool = False) -> Optional[int]:
    """Take the run in progress's news: report what the coding agent does,
    keep its steps in the progress note, and its replies for post_replies.
    Returns the run's exit code once it is over, else None. <stopped>: the
    watcher stopped the run, so a coding agent that didn't finish was stopped,
    not crashed."""
    run = dispatch.run
    if run is None:
        return None
    exited = None
    for news in run.handle.news():
        if isinstance(news, Reply):
            run.replies.append(news)
        elif isinstance(news, Exited):
            exited = news.code
        elif isinstance(news, Step):
            report.step(news.label, news.failed)
            run.progress.step(news.label)
            run.changed = True
        elif isinstance(news, Finished):
            if news.error:
                report.coding_agent_failed(news.error)
            finished(dispatch, report, news)
        elif isinstance(news, ContextUsed):
            run.progress.use(news)
        elif isinstance(news, Said):
            report.said(news.text)
        elif isinstance(news, AgentSessionStarted):
            report.agent_session_started(news.agent_session, news.model)
        elif isinstance(news, ModelChosen):
            report.model_chosen(news.model, news.source)
        elif isinstance(news, Output):
            report.output(news.line)
        elif isinstance(news, Unparsed):
            report.unparsed(news.reason)
    if exited is not None and not stopped and not run.progress.finished:
        # The coding agent crashed, or was killed, before it said it finished
        finished(dispatch, report, Finished(False, error=NOT_FINISHED))
    return exited


def finished(dispatch: Dispatch, report: ForReporting, news: Finished) -> None:
    """The coding agent says it finished. Each time is reported; the progress
    note keeps the first."""
    run = dispatch.run
    assert run is not None
    report.finished(news.ok, dispatch.secs(run.started), news.cost, run.progress.context())
    if run.progress.finish(news.ok, news.error):
        run.changed = True
        run.ending_secs = dispatch.secs(run.started)
