"""The composition root (ADR 0003): it picks the adapters, builds them, binds
them to the core's use cases with functools.partial, and runs the command
line, which starts the review API and the loop.

It is the only module that imports both the core and the adapters
(tests/test_core_boundary.py). difftate-watch.py (the watcher), bin/difftate, bin/dt-export and
bin/dt-reply call it.
"""
import functools
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

from .adapters.inbound import cli
from .adapters.inbound.review_api import ReviewApi, ShownView, ask_running_watcher, running_watcher, token_file
from .adapters.outbound import agent_list, git
from .adapters.outbound.coding_agents import ClaudeCode, CodingAgent, OffLimits, OpenCode, find_command
from .adapters.outbound.coding_agents.reply_channel import ReplyError, RunFolder, reply_command
from .adapters.outbound.git import GitCodeReader
from .adapters.outbound.history_files import HistoryFiles
from .adapters.outbound.local_store import LocalStore, review_id
from .adapters.outbound.memory_store import MemoryStore
from .adapters.outbound.terminal import Terminal
from .core.changes.use_cases.changeset import changeset
from .core.changes.use_cases.checked_out import checked_out
from .core.changes.use_cases.commit_messages import commit_messages
from .core.dispatch.model import CouldNotStart, Dispatch
from .core.dispatch.use_cases.poll import poll
from .core.dispatch.use_cases.recover_runs import recover_runs as recover_interrupted_runs
from .core.dispatch.use_cases.stop_run import stop_run
from .core.review.model import NotesInProgress, NotFound
from .core.review.use_cases.add_comment import add_comment
from .core.review.use_cases.clear_done import clear_done
from .core.review.use_cases.edit_note import edit_note
from .core.review.use_cases.end_run import end_run
from .core.review.use_cases.export_review import export_review
from .core.review.use_cases.list_threads import list_threads
from .core.review.use_cases.list_viewed import list_viewed
from .core.review.use_cases.mark_viewed import mark_viewed
from .core.review.use_cases.move_with_code import move_with_code
from .core.review.use_cases.open_thread import open_thread
from .core.review.use_cases.read_agent_override import read_agent_override
from .core.review.use_cases.read_done import read_done
from .core.review.use_cases.read_mode import read_mode
from .core.review.use_cases.recover_runs import recover_runs
from .core.review.use_cases.set_agent_override import set_agent_override
from .core.review.use_cases.set_done import set_done
from .core.review.use_cases.set_mode import set_mode
from .core.review.use_cases.set_status import set_status
from .core.review.use_cases.start_run import start_run
from .core.review.use_cases.submit import submit

# ═══ The adapters ══════════════════════════════════════════════════════════
# Which adapter plugs into each port. They are picked here and nowhere else:
# picking them from a config file (#70) changes only this block.
STORE = LocalStore              # for keeping the review
REVIEW_HISTORY = HistoryFiles   # for recording review history
CODE_READER = GitCodeReader     # for reading the code
REPOSITORY = git                # the repository: its difftate folders, base, branch, views and kept snapshots (goes with CODE_READER)
REPORTER = Terminal             # for reporting
CODING_AGENTS = {a.name: a for a in (ClaudeCode, OpenCode)}  # for asking the coding agent: an entry of the agent list picks one
VIEWERS = {"browser": cli.open_browser, "nvim": cli.open_in_nvim}  # where the review opens: --open picks
# ═══════════════════════════════════════════════════════════════════════════

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))  # this checkout of difftate


def difftate_home():
    """The difftate folder of the machine: the watcher's running files, token, lock
    and log, and the review history. $DIFFTATE_HOME, else ~/.difftate."""
    return os.environ.get("DIFFTATE_HOME") or os.path.join(os.path.expanduser("~"), ".difftate")


def bind_review(store, code, history, about):
    """One review: the core's use cases with its ports bound (functools.partial),
    for the review API and Dispatch. <about> is the review's {"id", "branch",
    "base"}.

    The review API serves each request on its own thread while Dispatch runs,
    and a use case reads the store, decides and appends: so the use cases that
    keep something run one at a time on a review, or two could decide on the
    same events. Reading the changeset, the checkout or the commit messages
    keeps nothing, so it doesn't wait."""
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
        set_done=one_at_a_time(set_done, store, code, history),
        read_done=functools.partial(read_done, store, code),
        set_mode=one_at_a_time(set_mode, store, notes, history),
        read_mode=functools.partial(read_mode, store),
        set_agent_override=one_at_a_time(set_agent_override, store, notes, history),
        read_agent_override=functools.partial(read_agent_override, store),
        submit=one_at_a_time(submit, store, notes, history),
        export=one_at_a_time(export_review, store, notes, code, reply_command),
        changeset=functools.partial(changeset, code),
        checked_out=functools.partial(checked_out, code),
        # For running the loop (Dispatch)
        move_with_code=one_at_a_time(move_with_code, store, code, history),
        clear_done=one_at_a_time(clear_done, store, code, history),
        commit_messages=functools.partial(commit_messages, code),
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
    history = REVIEW_HISTORY({"repo": repo, "branch": branch, "base": base, "review": about["id"]},
                             os.path.join(difftate_home(), "history"))
    # The snapshots of a review whose folder was removed can go
    REPOSITORY.forget_kept_snapshots(cwd, STORE.review_ids(folder))
    return bind_review(store, CODE_READER(cwd, base, branch, about["id"]), history, about)


def read_agent_list():
    """The machine's agent list, read now; raises the core's NotFound when it is wrong."""
    try:
        return agent_list.load(difftate_home())
    except agent_list.AgentListError as e:
        raise NotFound(str(e)) from e


def agent_choice(cwd, override=""):
    """The agent that replies in the repository of <cwd>, and where that comes
    from: the review's own choice (<override>, "" for none), else the
    repository's setting, else the machine's default. Its name, source
    ("review", "repository" or "machine"), the list's names and path, and its
    entry; raises the core's NotFound when the list is wrong or the choice
    names an agent that isn't in it."""
    agents = read_agent_list()
    chosen = REPOSITORY.agent_setting(cwd)
    name, source = ((override, "review") if override else (chosen, "repository") if chosen
                    else (agents.default, "machine"))
    try:
        entry = agents.get(name)
    except agent_list.AgentListError as e:
        if source != "review":
            raise NotFound(f"the {source}'s agent {e}") from e
        entry = None  # a review's choice the list lost since: viewers still show it, so it can be cleared; a run refuses it
    return SimpleNamespace(name=name, source=source, names=agents.names, path=agents.path, entry=entry)


def check_agent(name):
    """<name> is an agent a run can start: in the list, and its command found.
    Refused with the core's NotFound, naming the list when it isn't."""
    agents = read_agent_list()
    try:
        entry = agents.get(name)
    except agent_list.AgentListError as e:
        raise NotFound(str(e)) from e
    try:
        find_command(entry.cmd)
    except CouldNotStart as e:
        raise NotFound(f"agent '{name}': {e}") from e


def set_agent(cwd, name):
    """Make <name> the agent of the repository of <cwd> and of its worktrees.
    Refused, with the names, when it isn't in the list or its command isn't found."""
    check_agent(name)
    REPOSITORY.set_agent_setting(cwd, name)


class ChosenAtRunStart:
    """The coding agent of the repository of <cwd>, chosen again each time a
    run starts (the repository's setting, else the machine's default, read from
    the list as it is then): changing it never disturbs a run in flight.
    A run may not write the review's <folder>, or the difftate folder of the
    machine (the watcher's running files, its log and the review history), and may not read
    that or the one review API token. Starting raises the core's CouldNotStart
    for a list that is wrong, an agent that isn't in it, or a command that isn't found."""
    reply_command = CodingAgent.reply_command

    def __init__(self, cwd, folder, override=lambda: ""):
        self.cwd = cwd
        self.folder = folder
        self.override = override  # the agent the reviewer chose for the review being run now ("" for none)

    def for_review(self, override):
        """The same agent, with the choice of the review that <override>() reads."""
        return ChosenAtRunStart(self.cwd, self.folder, override)

    @property
    def name(self):
        """What the run is dispatched to, as the log names it."""
        try:
            return agent_choice(self.cwd, self.override()).name
        except NotFound:
            return self.override() or REPOSITORY.agent_setting(self.cwd) or "agent"

    def start(self, prompt, threads):
        try:
            chosen = agent_choice(self.cwd, self.override())
        except NotFound as e:
            raise CouldNotStart(str(e)) from e
        entry = chosen.entry
        if entry is None:
            raise CouldNotStart(f"the review's agent '{chosen.name}' is not in the agent list ({chosen.path}): "
                                f"{', '.join(chosen.names)}; choose another or clear it")
        found = find_command(entry.cmd)
        home = difftate_home()

        def off_limits():
            return OffLimits(keep_out=[self.folder, home], secrets=[token_file(home), home])

        return CODING_AGENTS[entry.tool](found, entry.model, cwd=self.cwd, off_limits=off_limits,
                                         env=entry.env).start(prompt, threads)


def coding_agent(cwd, folder):
    """The coding agent whose runs work in <cwd> (the review's checked-out
    folder), and may not write the review's <folder>."""
    return ChosenAtRunStart(cwd, folder)


def shown_view(view, check, on_switch):
    return ShownView(view, check, on_switch)


def review_api(folders, home, on_stop):
    """The review API, with its running files and token in <home>. A reviewer
    who gives no reviewer name is the user: the repository's git user.name, read
    at each request."""
    return ReviewApi(folders, home, default_reviewer=REPOSITORY.user_name, on_stop=on_stop)


def start_watcher(args):
    """Start the watcher in the background, with its own session (closing the
    terminal doesn't stop it) and its log in the difftate folder as its output;
    a function that says whether it is still alive."""
    home = difftate_home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    with open(os.path.join(home, "log"), "a", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, os.path.join(ROOT, "difftate-watch.py"), *args],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    return lambda: process.poll() is None


def loop(review, coding_agent):
    report = REPORTER()
    dispatch = Dispatch(review)
    coding_agent = coding_agent.for_review(lambda: dispatch.review.read_agent_override())

    def switch_review(review):
        dispatch.review = review

    def busy():
        """A run holds the review, or the last run's end isn't kept yet (poll)."""
        return dispatch.run is not None or bool(dispatch.unended and not dispatch.unended())

    return cli.Loop(
        poll=functools.partial(poll, dispatch, coding_agent, report),
        busy=busy,
        recover_runs=functools.partial(recover_interrupted_runs, report=report),
        stop=functools.partial(stop_run, dispatch, report),
        switch_review=switch_review,
        warn_tampered=dispatch.warn_tampered,
    )


def done_status(folder, cwd, branch, base):
    """Whether the review of <branch> against <base> kept in <folder> is Done.
    It starts no review and writes nothing: a watcher may be keeping it."""
    store = STORE.find(folder, branch, base)
    code = CODE_READER(cwd, base, branch, review_id(branch, base))
    if store is None and code.head_commit() is None:
        raise NotFound(f"no branch '{branch}' in this repository, and no review of it")
    return read_done(store or MemoryStore(), code)


def reply_in_run(run_dir, thread, body):
    """A run's answer to <thread>, left in the run's folder (the reply channel)."""
    try:
        return RunFolder(run_dir).write_reply(thread, body)
    except ReplyError as e:
        raise cli.ReplyRefused(str(e)) from e


def wiring():
    return cli.Wiring(
        viewers=VIEWERS,
        difftate_home=difftate_home(),
        difftate_folder=REPOSITORY.difftate_folder,
        running_watcher=running_watcher,
        ask_running_watcher=ask_running_watcher,
        start_watcher=start_watcher,
        reply_in_run=reply_in_run,
        coding_agent=coding_agent,
        agent_choice=agent_choice,
        check_agent=check_agent,
        set_agent=set_agent,
        base=REPOSITORY.base,
        need_view=REPOSITORY.need_view,
        review_branch=REPOSITORY.review_branch,
        open_review=open_review,
        shown_view=shown_view,
        review_api=review_api,
        loop=loop,
        done_status=done_status,
    )


def main(argv):
    """difftate-watch.py: the watcher, which `difftate` starts in the background."""
    return cli.run_watcher(argv, wiring())


def difftate_main(argv):
    """bin/difftate: `status` reads a review's Done state; `agent` says or sets who replies; anything else opens
    the folder's review (starting the watcher if none runs) or stops the watcher."""
    if argv[:1] == ["status"]:
        return cli.run_status(argv[1:], wiring())
    if argv[:1] == ["agent"]:
        return cli.run_agent(argv[1:], wiring())
    return cli.run_difftate(argv, wiring())


def export_main(argv):
    """bin/dt-export: print the export of a review, asked of the watcher."""
    return cli.run_export(argv, wiring())


def reply_main(argv):
    """bin/dt-reply: a run's answer into its folder, or an agent session's,
    posted through the review API of the watcher."""
    return cli.run_reply(argv, wiring())
