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
    runs a killed watcher left on <review>; stop(say) stops the run in
    progress. dispatch is the Dispatch they run on (its review changes when
    the watcher follows the checked-out branch)."""
    dispatch: Any
    poll: Callable[[Callable[[], None]], None]
    recover_runs: Callable[[Any], None]
    stop: Callable[[bool], None]


@dataclass(frozen=True)
class Wiring:
    """The adapters, for the command line.

    coding_agents: the names --tool accepts.
    viewers: name -> open(url, root), whether it could be reached (--open).
    difftate_folder(cwd): (the repository's difftate folder, its top folder),
        or None outside a git repository.
    running_watcher(folder), ask_running_watcher(folder, method, path,
        payload): another watcher serving this repository's review API.
    coding_agent(tool, cmd, session, model, cwd, folder): the coding agent;
        raises the core's CouldNotStart when its command isn't found.
    base(cwd, given): the review's base; raises the core's NotFound.
    need_view(cwd, view): <view>, once it is a view; raises NotFound.
    review_branch(cwd, base): what the review is of, or None with no commit.
    open_review(folder, cwd, branch, base, on_tamper): one review, its use
        cases bound; raises the core's CouldNotRead, or OSError.
    review_api(review, folder, root, view, check, on_switch): the review API
        (not started), showing <view>.
    loop(review, agent): the Loop on a new Dispatch of <review>."""
    coding_agents: Sequence[str]
    viewers: Mapping[str, Callable[[str, str], bool]]
    difftate_folder: Callable[[str], Optional[Tuple[str, str]]]
    running_watcher: Callable[[str], Optional[int]]
    ask_running_watcher: Callable[..., Tuple[int, Any]]
    coding_agent: Callable[..., Any]
    base: Callable[[str, str], str]
    need_view: Callable[[str, Any], str]
    review_branch: Callable[[str, str], Optional[str]]
    open_review: Callable[..., Any]
    review_api: Callable[..., Any]
    loop: Callable[[Any, Any], Loop]
