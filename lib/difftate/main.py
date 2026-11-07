"""The composition root (ADR 0003): it picks the adapters, builds them, binds
them to the core's use cases with functools.partial, and runs the command
line, which starts the review API and the loop.

It is the only module that imports both the core and the adapters
(tests/test_core_boundary.py). difftate-watch.py calls main().
"""
import functools
import os
import threading
from types import SimpleNamespace

from .adapters.inbound import cli
from .adapters.inbound.review_api import ReviewApi, ShownView, ask_running_watcher, running_watcher, token_file
from .adapters.outbound import git
from .adapters.outbound.coding_agents import ClaudeCode, OpenCode, find_command
from .adapters.outbound.git import GitCodeReader
from .adapters.outbound.history_files import HistoryFiles
from .adapters.outbound.local_store import LocalStore
from .adapters.outbound.terminal import Terminal
from .core.changes.use_cases.changeset import changeset
from .core.changes.use_cases.checked_out import checked_out
from .core.dispatch.model import Dispatch
from .core.dispatch.use_cases.poll import poll
from .core.dispatch.use_cases.recover_runs import recover_runs as recover_interrupted_runs
from .core.dispatch.use_cases.stop_run import stop_run
from .core.review.model import NotesInProgress
from .core.review.use_cases.add_comment import add_comment
from .core.review.use_cases.edit_note import edit_note
from .core.review.use_cases.end_run import end_run
from .core.review.use_cases.list_threads import list_threads
from .core.review.use_cases.list_viewed import list_viewed
from .core.review.use_cases.mark_viewed import mark_viewed
from .core.review.use_cases.move_with_code import move_with_code
from .core.review.use_cases.open_thread import open_thread
from .core.review.use_cases.recover_runs import recover_runs
from .core.review.use_cases.set_status import set_status
from .core.review.use_cases.start_run import start_run

# ═══ The adapters ══════════════════════════════════════════════════════════
# Which adapter plugs into each port. They are picked here and nowhere else:
# picking them from a config file (#70) changes only this block.
STORE = LocalStore              # for keeping the review
REVIEW_HISTORY = HistoryFiles   # for recording review history
CODE_READER = GitCodeReader     # for reading the code
REPOSITORY = git                # the repository: its difftate folder, base, branch and views (goes with CODE_READER)
REPORTER = Terminal             # for reporting
CODING_AGENTS = {a.name: a for a in (ClaudeCode, OpenCode)}  # for asking the coding agent: --tool picks one
VIEWERS = {"browser": cli.open_browser, "herdr": cli.open_in_herdr}  # where the review opens: --open picks
# ═══════════════════════════════════════════════════════════════════════════


def bind_review(store, code, history, about):
    """One review: the core's use cases with its ports bound (functools.partial),
    for the review API and Dispatch. <about> is the review's {"id", "branch",
    "base"}.

    The review API serves each request on its own thread while Dispatch runs,
    and a use case reads the store, decides and appends: so the use cases that
    keep something run one at a time on a review, or two could decide on the
    same events. Reading the changeset or the checkout keeps nothing, so it
    doesn't wait."""
    notes = NotesInProgress()  # the notes that aren't final yet, this review's
    lock = threading.Lock()

    def one_at_a_time(use_case, *ports):
        bound = functools.partial(use_case, *ports)

        @functools.wraps(use_case)
        def call(*args, **kwargs):
            with lock:
                return bound(*args, **kwargs)
        return call

    return SimpleNamespace(
        about=about,
        # For reviewing (the review API)
        list_threads=one_at_a_time(list_threads, store, notes, code),
        open_thread=one_at_a_time(open_thread, store, notes, code, history),
        add_comment=one_at_a_time(add_comment, store, notes, history),
        edit_note=one_at_a_time(edit_note, store, notes, history),
        set_status=one_at_a_time(set_status, store, notes, history),
        mark_viewed=one_at_a_time(mark_viewed, store, code, history),
        list_viewed=one_at_a_time(list_viewed, store, code, history),
        changeset=functools.partial(changeset, code),
        checked_out=functools.partial(checked_out, code),
        # For running the loop (Dispatch)
        move_with_code=one_at_a_time(move_with_code, store, code, history),
        start_run=one_at_a_time(start_run, store, notes, history),
        end_run=one_at_a_time(end_run, store, notes, history),
        recover_runs=one_at_a_time(recover_runs, store, notes, history),
    )


def open_review(folder, cwd, branch, base, on_tamper):
    """The review of <branch> against <base>, kept in <folder>, with every
    line of its review history saying which review it came from."""
    store = STORE.open(folder, branch, base, on_tamper=on_tamper)
    about = store.review()
    repo = {"path": os.path.realpath(cwd), "remote": REPOSITORY.remote_url(cwd)}
    history = REVIEW_HISTORY({"repo": repo, "branch": branch, "base": base, "review": about["id"]})
    return bind_review(store, CODE_READER(cwd, base, branch), history, about)


def coding_agent(tool, cmd, session, model, cwd, folder):
    """The coding agent <tool>: its runs work in <cwd>, may not write the
    review's <folder>, and may not read the review API's token."""
    chosen = CODING_AGENTS[tool]
    return chosen(find_command(cmd or chosen.default_cmd), session, model, cwd=cwd, keep_out=[folder],
                  secrets=[token_file(folder)])


def review_api(review, folder, root, view, check, on_switch):
    shown = ShownView(view, check, on_switch, open_in=cli.where_to_open(VIEWERS))
    return ReviewApi(review, folder, root, shown)


def loop(review, coding_agent):
    report = REPORTER()
    dispatch = Dispatch(review)

    def switch_review(review):
        dispatch.review = review

    return cli.Loop(
        poll=functools.partial(poll, dispatch, coding_agent, report),
        recover_runs=functools.partial(recover_interrupted_runs, report=report),
        stop=functools.partial(stop_run, dispatch, report),
        switch_review=switch_review,
        warn_tampered=dispatch.warn_tampered,
    )


def wiring():
    return cli.Wiring(
        coding_agents=list(CODING_AGENTS),
        viewers=VIEWERS,
        difftate_folder=REPOSITORY.difftate_folder,
        running_watcher=running_watcher,
        ask_running_watcher=ask_running_watcher,
        coding_agent=coding_agent,
        base=REPOSITORY.base,
        need_view=REPOSITORY.need_view,
        review_branch=REPOSITORY.review_branch,
        open_review=open_review,
        review_api=review_api,
        loop=loop,
    )


def main(argv):
    return cli.run(argv, wiring())

