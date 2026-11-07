"""Dispatch's driven ports: asking the coding agent, and reporting.

Each is a typing.Protocol: any object with these methods plugs in. The
adapters in difftate/adapters/outbound/coding_agents/ and terminal/ do.
"""
from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from ..review.model import Comment, ListedThread, Run, Thread
from .model import News


class CodingAgentRun(Protocol):
    """One run of the coding agent."""

    pid: int  # the coding agent's process, as the terminal names it

    def news(self) -> List[News]:
        """What happened since the last call, oldest first: steps, replies,
        and the end of the run (Exited, always last). It doesn't wait."""
        ...

    def stop(self) -> None:
        """Stop the run, and everything it started. The next news() gives the
        replies it left, and Exited."""
        ...


class ForAskingTheCodingAgent(Protocol):
    """The coding agent: Claude Code or OpenCode."""

    name: str  # as the terminal names it ("claude")
    reply_command: str  # how the coding agent answers a thread, as the prompt names it

    def start(self, prompt: str, threads: Sequence[str]) -> CodingAgentRun:
        """A run with <prompt>, which may reply to the threads <threads> (ids).
        Raises model.CouldNotStart."""
        ...


class ForReporting(Protocol):
    """What Dispatch tells whoever watches it: the terminal's lines."""

    def dispatching(self, coding_agent: str) -> None:
        """A run starts on the waiting threads."""

    def model_chosen(self, model: str, source: str) -> None:
        """The run's model ("" for the coding agent's default)."""

    def agent_session_started(self, agent_session: str, model: str) -> None: ...

    def said(self, text: str) -> None:
        """Text the coding agent wrote."""

    def step(self, label: str, failed: bool) -> None: ...

    def coding_agent_failed(self, error: str) -> None:
        """The coding agent says it failed, and why."""

    def finished(self, ok: bool, secs: int, cost: Optional[float], context: str) -> None:
        """The coding agent finished (<ok>) or failed, after <secs>."""

    def output(self, line: str) -> None:
        """A line to show as it is."""

    def unparsed(self, reason: str) -> None: ...

    def outdated(self, thread_id: str) -> None:
        """The thread's code changed."""

    def queued(self, thread_id: str) -> None:
        """The thread got a queued note: a run is busy."""

    def no_reply(self, thread_id: str, watcher_stopped: bool) -> None:
        """The run ended with no reply to the thread. <watcher_stopped>: the
        watcher stopped during the run."""

    def stopping(self, pid: int) -> None:
        """The watcher stops the run in progress."""

    def warning(self, text: str) -> None: ...


class ReviewForDispatch(Protocol):
    """The review's use cases Dispatch calls, with their ports bound
    (watcher.bind_review). Not a driven port: the Review is in the core too."""

    def list_threads(self, status: Optional[str] = None) -> List[ListedThread]: ...

    def move_with_code(self) -> List[str]: ...

    def start_run(self, threads: Sequence[Thread]) -> Run: ...

    def add_comment(self, author: str, thread_id: str, kind: str, body: str) -> Comment: ...

    def edit_note(self, author: str, note_id: str, kind: str, body: str, final: bool = False) -> Comment: ...

    def end_run(self, outcome: str) -> List[Thread]: ...

    def recover_runs(self) -> List[Thread]: ...
