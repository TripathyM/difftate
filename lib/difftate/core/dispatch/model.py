"""Dispatch's model: the news a run gives, the notes Dispatch writes, the
progress note's text, and what Dispatch keeps between polls.

Dispatch sends the waiting threads to the coding agent as one run, one run at
a time (GLOSSARY.md, Dispatch). While a run works, a thread that becomes
waiting gets a queued note. Each thread of a run gets a progress note: its
steps while the run works, then one line that says it finished or failed.
A thread the run didn't reply to is failed ("no reply").

The coding agent's adapter turns what the coding agent does into news (ports.
ForAskingTheCodingAgent): steps, replies, and the end of the run. Dispatch
writes the progress notes from them, through the Review.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Collection, Dict, FrozenSet, List, Optional, Sequence, Set, Union

from ..review.model import ListedThread, Thread

if TYPE_CHECKING:
    from .ports import CodingAgentRun, ReviewForDispatch

QUEUED_NOTE = "🕒 **Queued** — agent is busy with another comment, will pick this up next."
PICKED_UP_NOTE = "🕒 **Queued** — picked up by the next run (below)."
THINKING_NOTE = "⏳ **Thinking…** (0s)"
TAMPERED = ("⚠️ The stored review was changed outside difftate during this run "
            "(only difftate may write it): difftate restored it.")
NOT_FINISHED = "Agent exited without finishing — check the watcher terminal."
WATCHER_STOPPED = " (the watcher stopped)"

MAX_STEPS_SHOWN = 8
STEP_MAX = 80  # characters of a step in the progress note
REFRESH_S = 3  # edit the progress notes this often while nothing happens, so the elapsed time moves
COMPACT_WARN_PCT = 70  # suggest /compact at or above this share of the context window


def short(text: str, n: int) -> str:
    """<text> on one line, cut to <n> characters."""
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ── News: what a run tells Dispatch ──────────────────────────────────────────
@dataclass(frozen=True)
class ModelChosen:
    """The model the run uses, and where that came from (the watcher's
    --model, or the agent session); model "" for the coding agent's default."""
    model: str
    source: str = ""


@dataclass(frozen=True)
class AgentSessionStarted:
    """The coding agent started its agent session (<agent_session>, its id)."""
    agent_session: str
    model: str


@dataclass(frozen=True)
class Said:
    """Text the coding agent wrote (not a reply)."""
    text: str


@dataclass(frozen=True)
class Step:
    """One action the coding agent took, such as reading a file. <failed> when
    it failed."""
    label: str
    failed: bool = False


@dataclass(frozen=True)
class ContextUsed:
    """The agent session's context: <tokens> in its latest model call, of a
    <window>. None: not known from this news."""
    tokens: Optional[int] = None
    window: Optional[int] = None


@dataclass(frozen=True)
class Reply:
    """The coding agent's answer to a thread."""
    thread_id: str
    body: str


@dataclass(frozen=True)
class Finished:
    """The coding agent says it finished: <ok>, or failed with <error>. <cost>
    in dollars, when it says."""
    ok: bool
    cost: Optional[float] = None
    error: str = ""


@dataclass(frozen=True)
class Output:
    """A line the coding agent wrote that isn't news, shown as it is."""
    line: str


@dataclass(frozen=True)
class Unparsed:
    """News the adapter could not read."""
    reason: str


@dataclass(frozen=True)
class Exited:
    """The run is over: the coding agent and everything it started stopped.
    Always the last news of a run. <code> is its exit code."""
    code: int


News = Union[ModelChosen, AgentSessionStarted, Said, Step, ContextUsed, Reply, Finished, Output, Unparsed, Exited]


class CouldNotStart(Exception):
    """The coding agent could not start (a prompt too long for the command
    line, or a command that can't run)."""


# ── The progress note ────────────────────────────────────────────────────────
def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


@dataclass
class ProgressNote:
    """The progress note a run keeps on each of its threads: a live checklist
    of its steps, until the coding agent finishes."""
    state: str = "thinking"  # thinking | working | done | failed
    steps: List[str] = field(default_factory=list)
    error: str = ""
    tokens: int = 0
    window: int = 0

    def step(self, label: str) -> None:
        self.steps.append(short(label, STEP_MAX))
        self.state = "working"

    def use(self, context: ContextUsed) -> None:
        if context.tokens:
            self.tokens = context.tokens
        if context.window:
            self.window = context.window

    def finish(self, ok: bool, error: str = "") -> bool:
        """The coding agent finished. False when it had finished already: the
        note keeps the first end."""
        if self.finished:
            return False
        self.state = "done" if ok else "failed"
        self.error = error
        return True

    @property
    def finished(self) -> bool:
        return self.state in ("done", "failed")

    def context(self) -> str:
        """The agent session's context, as the note and the terminal show it."""
        if not self.tokens:
            return ""
        if not self.window:
            return f"🧠 context {fmt_tokens(self.tokens)}"
        pct = 100 * self.tokens / self.window
        warn = " ⚠️ consider /compact" if pct >= COMPACT_WARN_PCT else ""
        return f"🧠 context {fmt_tokens(self.tokens)} / {fmt_tokens(self.window)} ({pct:.0f}%){warn}"

    def render(self, secs: int) -> str:
        head = {
            "thinking": f"⏳ **Thinking…** ({secs}s)",
            "working": f"⏳ **Working…** ({secs}s)",
            "done": f"✅ **Done** in {secs}s",
            "failed": f"❌ **Failed** after {secs}s",
        }[self.state]
        ctx = self.context()
        lines = [head + (f" · {ctx}" if ctx else "")]
        if self.state == "done":
            # Finished: one line is enough, the coding agent's own reply has the details
            return lines[0]
        hidden = len(self.steps) - MAX_STEPS_SHOWN
        if hidden > 0:
            lines.append(f"- ✅ …{hidden} earlier steps")
        last = len(self.steps) - 1
        for i, label in enumerate(self.steps[-MAX_STEPS_SHOWN:], start=max(hidden, 0)):
            done = self.finished or i < last
            lines.append(f"- {'✅' if done else '⏳'} `{label}`")
        if self.error:
            lines.append(f"\n{self.error}")
        return "\n".join(lines)


def no_reply(secs: Optional[int], why: str = "") -> str:
    """The final line of a progress note on a thread the run didn't reply to.
    <secs> None: the run's length isn't known."""
    return f"❌ **Failed**{'' if secs is None else f' after {secs}s'} — no reply{why}"


def stopped(secs: int) -> str:
    return f"⏹ **Stopped** after {secs}s{WATCHER_STOPPED}"


# ── Which threads go into a run ──────────────────────────────────────────────
def waiting(listed: Sequence[ListedThread]) -> List[Thread]:
    """The threads a run is sent: the waiting ones."""
    return [t.thread for t in listed if t.state == "waiting"]


def queued(listed: Sequence[ListedThread]) -> List[Thread]:
    return [t.thread for t in listed if t.state == "queued"]


def reused_queued_notes(threads: Sequence[Thread], queued_notes: Dict[str, str]) -> Dict[str, str]:
    """The queued notes that become the progress notes of <threads>: a thread
    whose last comment is its queued note gets that note back ({thread id:
    note id}). A later comment pushed the others up the thread."""
    return {t.id: queued_notes[t.id] for t in threads
            if t.id in queued_notes and t.comments and t.comments[-1].id == queued_notes[t.id]}


# ── What Dispatch keeps between polls ────────────────────────────────────────
class NotStarted:
    """The run of a coding agent that hasn't started yet."""
    pid = 0

    def news(self) -> List[News]:
        return []

    def stop(self) -> None:
        pass


@dataclass
class RunInProgress:
    """The run Dispatch waits on.

    handle    the coding agent's run (ports.CodingAgentRun)
    reply_to  the threads it may reply to: the threads open when it started
    notes     {thread id: its progress note id}
    replies   replies not yet posted: the store refused them, so far
    tampered  threads whose stored lines were changed outside difftate meanwhile
    """
    handle: CodingAgentRun
    reply_to: FrozenSet[str]
    started: float
    notes: Dict[str, str] = field(default_factory=dict)
    progress: ProgressNote = field(default_factory=ProgressNote)
    replies: List[Reply] = field(default_factory=list)
    tampered: Set[str] = field(default_factory=set)
    ending_secs: Optional[int] = None  # how long the run took when the coding agent finished
    edited: float = 0.0  # when the progress notes were last edited
    changed: bool = False  # the progress note changed since then


@dataclass
class Dispatch:
    """What Dispatch keeps between polls of the loop.

    review    the review's use cases it works on (bound by the watcher); it
              changes only between runs
    run       the run in progress, or None
    queued    {thread id: its queued note}, for queued notes not yet picked up.
              Thread ids are unique across reviews, so it outlasts a review
              switch
    unended   a run whose end the store couldn't keep: () -> True once kept
    warned    the last warning about the store, so it isn't repeated every poll
    """
    review: ReviewForDispatch
    clock: Callable[[], float] = time.time
    run: Optional[RunInProgress] = None
    queued: Dict[str, str] = field(default_factory=dict)
    unended: Optional[Callable[[], bool]] = None
    warned: Optional[str] = None

    def should_warn(self, text: str) -> bool:
        """A failing store isn't warned about on every poll: True only when
        <text> isn't the last warning."""
        warn, self.warned = text != self.warned, text
        return warn

    def secs(self, started: float) -> int:
        return int(self.clock() - started)

    def warn_tampered(self, thread_ids: Collection[str]) -> None:
        """Stored lines were changed outside difftate (and restored): a run in
        progress says so in the final progress notes of the threads they name."""
        if self.run is not None:
            self.run.tampered.update(thread_ids)
