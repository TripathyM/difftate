"""Dispatching the waiting threads: as one run when none is in progress, else
each gets a queued note."""
from __future__ import annotations

from typing import Dict, List, Sequence

from ...review.model import DIFFTATE, CouldNotRead, ListedThread, ReviewError, Thread
from .. import prompt
from ..model import (
    PICKED_UP_NOTE, QUEUED_NOTE, THINKING_NOTE, CouldNotStart, Dispatch, NotStarted, RunInProgress, queued,
    reused_queued_notes, waiting,
)
from ..ports import ForAskingTheCodingAgent, ForReporting
from .end_run import end_run


def dispatch_waiting(dispatch: Dispatch, agent: ForAskingTheCodingAgent, report: ForReporting) -> None:
    """The waiting threads go to the coding agent as one run. While a run is
    in progress, runs stay one at a time: each thread that became waiting
    gets a queued note instead."""
    listed = open_threads(dispatch)
    if dispatch.run is not None:
        post_queued_notes(dispatch, report, listed)
    else:
        start_run(dispatch, agent, report, listed)


def open_threads(dispatch: Dispatch) -> List[ListedThread]:
    try:
        return dispatch.review.list_threads("open")
    except CouldNotRead:
        return []


def start_run(dispatch: Dispatch, agent: ForAskingTheCodingAgent, report: ForReporting,
              listed: Sequence[ListedThread]) -> None:
    sent = waiting(listed)
    if not sent:
        return
    review = dispatch.review
    # The run is kept before anything else, with the comments these threads
    # had when read: the prompt shows them, and a later one waits for the next run
    try:
        recorded = review.start_run(sent)
    except CouldNotRead as e:
        text = f"could not record the run ({e}): it starts once it can be recorded"
        if dispatch.should_warn(text):
            report.warning(text)
        return
    dispatch.warned = None
    report.dispatching(agent.name)

    threads = [t.thread for t in listed]
    text = prompt.build(threads, [t.id for t in sent], list(recorded.sent), agent.reply_command)
    reply_to = frozenset(t.id for t in threads)
    run = dispatch.run = RunInProgress(handle=NotStarted(), reply_to=reply_to, started=dispatch.clock())
    # A thread that ends in its queued note gets that note back as its progress note
    picked_up = {t.id: dispatch.queued.pop(t.id) for t in sent if t.id in dispatch.queued}
    reused = reused_queued_notes(sent, picked_up)
    close_queued_notes(dispatch, [nid for tid, nid in picked_up.items() if tid not in reused])
    run.notes = post_progress_notes(dispatch, report, sent, reused)
    run.edited = dispatch.clock()
    try:
        run.handle = agent.start(text, sorted(reply_to))
    except CouldNotStart as e:
        report.warning(f"could not start {agent.name}: {e}")
        end_run(dispatch, report, "failed", f" (could not start {agent.name}: {e})")



def post_progress_notes(dispatch: Dispatch, report: ForReporting, threads: Sequence[Thread],
                        reused: Dict[str, str]) -> Dict[str, str]:
    """A progress note on each of <threads> ({thread id: note id}). A thread
    that ends in its queued note (<reused>) gets that note back."""
    notes = {}
    for t in threads:
        try:
            if t.id in reused:
                note = dispatch.review.edit_note(DIFFTATE, reused[t.id], "progress", THINKING_NOTE)
            else:
                note = dispatch.review.add_comment(DIFFTATE, t.id, "progress", THINKING_NOTE)
            notes[t.id] = note.id
        except ReviewError as e:
            report.warning(f"could not post the progress note on thread {t.id[:8]} ({e})")
    return notes


def post_queued_notes(dispatch: Dispatch, report: ForReporting, listed: Sequence[ListedThread]) -> None:
    """A queued note on each queued thread that has none yet."""
    for t in queued(listed):
        if t.id in dispatch.queued:
            continue
        try:
            dispatch.queued[t.id] = dispatch.review.add_comment(DIFFTATE, t.id, "queued", QUEUED_NOTE).id
        except ReviewError:
            continue
        report.queued(t.id)


def close_queued_notes(dispatch: Dispatch, note_ids: Sequence[str]) -> None:
    """A queued note that a later comment pushed up the thread can't become the
    progress note (that must come after every comment the run is sent), so it
    says the run picked the thread up instead."""
    for note_id in note_ids:
        try:
            dispatch.review.edit_note(DIFFTATE, note_id, "queued", PICKED_UP_NOTE)
        except ReviewError:
            pass
