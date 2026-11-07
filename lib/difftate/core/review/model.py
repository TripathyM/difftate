"""The Review's model: threads, comments and anchors, the events that change
them, and the Review that checks the rules (ADR 0004).

The Review is the aggregate root. A method such as open_thread checks the
rules and returns events: facts in the past tense. apply() is the only place
the Review's state changes, so a Review rebuilt from its events is the same
Review. The events mirror the lines of today's events.jsonl ("opened",
"comment", "outdated").
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple, Union

from ..changes.model import Snapshot, same_code

REVIEWER = "reviewer"


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    """The time something is written, as today's events.jsonl has it."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── Errors ───────────────────────────────────────────────────────────────────
# The core says what went wrong in its own words. An inbound adapter turns
# them into its technology's words: the review API into 403, 404, 409 and 502.
class ReviewError(Exception):
    """Something the core refused or could not do."""


class NotAllowed(ReviewError):
    """The rules don't let this author do this."""


class NotFound(ReviewError):
    """No such thread."""


class Conflict(ReviewError):
    """Not now: the review isn't in a state to take this change."""


class CouldNotRead(ReviewError):
    """A driven port could not read what the core asked for (the code, say)."""


# ── Threads and comments ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Comment:
    """A message in a thread. <author> is who wrote it (a reviewer), <kind> what
    it is (a reviewer's comment)."""
    id: str
    author: str
    kind: str
    body: str
    time: str


@dataclass(frozen=True)
class Anchor:
    """Where a thread is attached: a file, a side ("old" or "new"), a line
    range, and the code on those lines when the thread was opened.

    view      the view the thread was written in ("" for all changes): the
              thread moves with its code there
    snapshot  the file as it was then (Snapshot.id); None until the Review
              opens the thread
    commit    the commit checked out then; None until the Review opens the thread
    """
    file: str
    side: str
    start_line: int
    end_line: int
    code: Optional[str] = None
    view: str = ""
    snapshot: Optional[str] = None
    commit: Optional[str] = None


@dataclass(frozen=True)
class Thread:
    """A conversation about one anchor, or about the changeset as a whole (a
    general thread: no anchor)."""
    id: str
    anchor: Optional[Anchor]
    status: str = "open"
    outdated: bool = False
    comments: Tuple[Comment, ...] = ()


# ── Events ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ThreadOpened:
    """A thread was opened (the "opened" line)."""
    thread_id: str
    anchor: Optional[Anchor]
    time: str


@dataclass(frozen=True)
class CommentAdded:
    """A comment was added at the end of a thread (the "comment" line)."""
    thread_id: str
    comment: Comment


@dataclass(frozen=True)
class ThreadOutdated:
    """A thread's code changed after it was written (the "outdated" line)."""
    thread_id: str
    time: str


Event = Union[ThreadOpened, CommentAdded, ThreadOutdated]


# ── The Review ───────────────────────────────────────────────────────────────
class Review:
    def __init__(self) -> None:
        self._threads: Dict[str, Thread] = {}  # id: thread, in the order they were opened

    @classmethod
    def from_events(cls, events: List[Event]) -> Review:
        """The Review as its events left it, applied in order."""
        review = cls()
        for event in events:
            review.apply(event)
        return review

    def thread(self, thread_id: str) -> Thread:
        if thread_id not in self._threads:
            raise NotFound(f"no thread {thread_id}")
        return self._threads[thread_id]

    def open_thread(self, author: str, body: str, anchor: Optional[Anchor] = None,
                    snapshot: Optional[Snapshot] = None) -> List[Event]:
        """A thread on <anchor>, or a general thread (no anchor), with <author>'s
        first comment. <snapshot> is the anchor's file now, from the code reader."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer opens a thread")
        thread_id, time = _new_id(), _now()
        outdated = False
        if anchor is not None:
            # With no code from the viewer, the thread is written on the code there now
            code = snapshot.code if anchor.code is None else anchor.code
            anchor = replace(anchor, code=code, snapshot=snapshot.id, commit=snapshot.commit)
            # A thread is written on the code the viewer showed. If the file no
            # longer has that code there, it changed since: outdated at once
            outdated = snapshot.code is None or not same_code(anchor.code, snapshot.code)
        events: List[Event] = [
            ThreadOpened(thread_id, anchor, time),
            CommentAdded(thread_id, Comment(_new_id(), author, "comment", body, time)),
        ]
        if outdated:
            events.append(ThreadOutdated(thread_id, time))
        for event in events:
            self.apply(event)
        return events

    def apply(self, event: Event) -> None:
        """The one place the Review's state changes."""
        if isinstance(event, ThreadOpened):
            self._threads[event.thread_id] = Thread(event.thread_id, event.anchor)
        elif isinstance(event, CommentAdded):
            thread = self._threads[event.thread_id]
            self._threads[thread.id] = replace(thread, comments=thread.comments + (event.comment,))
        elif isinstance(event, ThreadOutdated):
            self._threads[event.thread_id] = replace(self._threads[event.thread_id], outdated=True)
