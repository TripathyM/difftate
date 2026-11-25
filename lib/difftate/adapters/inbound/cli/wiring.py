"""What main.py plugs into the command line: the adapters it picked, built
and bound to the core. The command line calls them; it never imports another
adapter (tests/test_core_boundary.py)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Loop:
    """Running the loop on one Dispatch: the core's use cases, bound to the
    coding agent and the reporter.

    poll(between_runs) is one poll of the loop; recover_runs(review) ends the
    runs a killed watcher left on <review>; busy() is whether a run holds the
    review (or its end isn't kept yet); stop(say) stops the run in
    progress. switch_review(review) dispatches <review>'s threads from now on
    (the watcher follows the checked-out branch); hold_for_branch(branch) puts
    a note on the review's waiting threads saying to check <branch> out (the
    watcher moves away from it, and no folder has it); warn_tampered(thread_ids)
    tells the run in progress that the stored review was changed outside
    difftate."""
    poll: Callable[[Callable[[], None]], None]
    busy: Callable[[], bool]
    recover_runs: Callable[[Any], None]
    stop: Callable[[bool], None]
    switch_review: Callable[[Any], None]
    hold_for_branch: Callable[[str], None]
    warn_tampered: Callable[[Sequence[str]], None]


@dataclass(frozen=True)
class Wiring:
    """The adapters, for the command line.

    viewers: name -> open(url, root), whether it could be reached (--open).
    difftate_home: the difftate folder of the machine (~/.difftate): the
        watcher's running files, token, lock and log, and the review history.
    difftate_folder(cwd): the checked-out folder <cwd> is in, as (the
        repository's difftate folder, shared by its worktrees: the reviews; its
        top folder), or None outside one.
    running_watcher(home), ask_running_watcher(home, method, path, payload):
        the one watcher serving the review API from <home>: its pid, or None;
        and a call to it: (status, JSON or text).
    start_watcher(args): start the watcher in the background with its options
        <args>; returns a function that says whether it is still alive.
    reply_in_run(run_dir, thread, body): leave a run's answer in its folder
        <run_dir> (the reply channel); the thread's full id. Raises ReplyRefused,
        or OSError.
    coding_agent(cwd, folder): the coding agent whose runs work in <cwd> and
        may not write the review's <folder>: its name and start(prompt, threads),
        which chooses the agent when a run starts (the review's own choice, else
        the repository's, else the machine's default, from the agent list as it
        is then; loop() tells it which review) and raises the
        core's CouldNotStart with no agent list, for an agent that isn't listed
        or whose command isn't found.
    agent_choice(cwd, override): the agent that replies in the repository of
        <cwd>, or <override> ("" for none), a review's own choice: an object
        with name, source ("review", "repository" or "machine"), names (the
        list's) and path (the list's file); raises the core's NotFound.
    check_agent(name): <name> is an agent a run can start; raises the core's
        NotFound, naming the list, when it isn't.
    set_agent(cwd, name): set the repository's agent; raises the core's
        NotFound for a name not in the list or a command not found.
    base(cwd, given): the review's base; raises the core's NotFound.
    need_view(cwd, view): <view>, once it is a view; raises NotFound.
    review_branch(cwd, base): what the review is of, or None with no commit.
    open_review(folder, cwd, branch, base, on_tamper): one review, its use
        cases bound; raises the core's CouldNotRead, or OSError.
    shown_view(view, check, on_switch): the view viewers show of a review.
    review_api(folders, home, on_stop): the review API (not started), with its
        running files and token in <home>, serving what folders(folder, base)
        gives; on_stop() runs when a request stops the watcher.
    loop(review, coding_agent): the Loop on a new Dispatch of <review>.
    done_status(folder, cwd, branch, base): whether the review of <branch>
        against <base> kept in <folder> is Done (a core DoneStatus), read
        without starting or changing anything; raises the core's NotFound
        for a branch with no commit and no review, or CouldNotRead."""
    viewers: Mapping[str, Callable[[str, str], bool]]
    difftate_home: str
    difftate_folder: Callable[[str], Optional[Any]]
    running_watcher: Callable[[str], Optional[int]]
    ask_running_watcher: Callable[..., Tuple[int, Any]]
    start_watcher: Callable[[Sequence[str]], Callable[[], bool]]
    reply_in_run: Callable[[str, str, str], str]
    coding_agent: Callable[[str, str], Any]
    agent_choice: Callable[..., Any]  # (cwd, override="")
    check_agent: Callable[[str], None]
    set_agent: Callable[[str, str], None]
    base: Callable[[str, str], str]
    need_view: Callable[[str, Any], str]
    review_branch: Callable[[str, str], Optional[str]]
    open_review: Callable[..., Any]
    shown_view: Callable[..., Any]
    review_api: Callable[..., Any]
    loop: Callable[[Any, Any], Loop]
    done_status: Callable[[str, str, str, str], Any]
