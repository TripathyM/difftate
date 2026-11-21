"""The Review's model: threads, comments and anchors, the events that change
them, and the Review that checks the rules (ADR 0004).

The Review is the aggregate root. A method such as open_thread checks the
rules and returns events: facts in the past tense. apply() is the only place
the Review's state changes, so a Review rebuilt from its events is the same
Review. There is one event type for each line type the local store keeps
("opened", "comment", "note", "status", "moved", "outdated", "run",
"run-ended", "viewed", "done", "undone", "done-cleared", "mode", "agent", "submitted").

The rules:
  1. Only a reviewer opens a thread or changes its thread status, and only
     a reviewer's comment or status change has a reviewer name.
  2. Each author writes only their own kind: the coding agent writes only replies.
  3. Only difftate writes notes, and only notes can be edited. A final note
     doesn't change again.
  4. One rule gives the thread state (Review.state).
  5. Only a reviewer marks the review Done or undoes it. It is Done at one
     commit: a new commit on the branch clears it, and a thread, a comment or
     a status change doesn't.
  6. Only a reviewer changes the review mode, chooses the agent of the review
     or submits. A review is live, with no agent of its own, until a reviewer
     changes it.
A thread moves with its code, or is outdated, only as difftate finds it
(move_with_code). A file stays viewed until its diff in the changeset
changes. While another branch is checked out, nothing that reads the code
changes the review.
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, replace
from typing import Collection, Dict, List, NamedTuple, Optional, Set, Tuple, Union

from ..changes.model import Moved, Outdated, Snapshot, same_code

REVIEWER = "reviewer"
CODING_AGENT = "agent"
DIFFTATE = "difftate"
# Who writes each kind of comment (rule 2: the coding agent writes only replies;
# rule 3: only difftate writes notes)
AUTHOR_OF = {"comment": REVIEWER, "reply": CODING_AGENT, "queued": DIFFTATE, "progress": DIFFTATE}
NOTE_KINDS = ("queued", "progress")
LIVE, BATCHED = "live", "batched"
MODES = (LIVE, BATCHED)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    """The time something is written, as the local store keeps it today."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ── Errors ───────────────────────────────────────────────────────────────────
# The core says what went wrong in its own words. An inbound adapter turns
# them into its technology's words (the review API: into HTTP status codes).
class ReviewError(Exception):
    """Something the core refused or could not do."""


class NotAllowed(ReviewError):
    """The rules don't let this author do this."""


class NotFound(ReviewError):
    """No such thread."""


class Conflict(ReviewError):
    """Not now: the review isn't in a state to take this change."""


class CouldNotRead(ReviewError):
    """A driven port could not do what the core asked: read the code, or keep
    the review (a store that can't write or restore its events, say). The
    review API answers 502 for it: the fault is outside the core."""


# ── Threads and comments ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class Comment:
    """A message in a thread: a reviewer's comment, the coding agent's reply or
    difftate's note. <author> is who wrote it ("reviewer"), <kind> what it is
    ("comment"), and <seq> its place in the review: a thread's comments are in
    seq order, so a note kept only when its run ends keeps the place where it
    was written. <by> is the reviewer name, what the reviewer said they are
    ("security-bot"): None for a reply, a note, or a comment with no name."""
    id: str
    author: str
    kind: str
    body: str
    time: str
    seq: int
    by: Optional[str] = None


@dataclass(frozen=True)
class Anchor:
    """Where a thread is attached: a file, a side ("old" or "new"), a line
    range, and the code on those lines when the thread was opened.

    view         the view the thread was written in ("" for all changes): the
                 thread moves with its code there
    snapshot_id  the file as it was then (Snapshot.id). A viewer may give the
                 version it showed (Changeset.versions); the Review writes the
                 thread on it when it has the viewer's code on those lines, else
                 on the file when the thread is opened
    commit       the commit checked out then; None until the Review opens the thread
    """
    file: str
    side: str
    start_line: int
    end_line: int
    code: Optional[str] = None
    view: str = ""
    snapshot_id: Optional[str] = None
    commit: Optional[str] = None


@dataclass(frozen=True)
class Thread:
    """A conversation about one anchor, or about the changeset as a whole (a
    general thread: no anchor). <status_by> is the reviewer name of the last
    thread status change (None for none, or one with no name)."""
    id: str
    anchor: Optional[Anchor]
    status: str = "open"
    outdated: bool = False
    comments: Tuple[Comment, ...] = ()
    status_by: Optional[str] = None


class ListedThread(NamedTuple):
    """A thread as a viewer lists it, with its thread state (None unless it is
    open). In a view, its anchor's lines are where its code is in that view.
    <in_view> False: the view doesn't show its code, so it is listed but not
    placed on a line, and keeps the lines of the view it was written in."""
    thread: Thread
    state: Optional[str]
    in_view: bool = True


@dataclass(frozen=True)
class Run:
    """One time the coding agent works on a set of threads.

    sent            the ids of the comments it was sent
    replies_before  {thread id: the ids of its replies when the run started}
    outcome         how it ended: done, failed, stopped or interrupted (the
                    watcher was killed during it, and the next one ended it);
                    None while it runs
    """
    id: str
    threads: Tuple[str, ...]
    sent: Tuple[str, ...]
    replies_before: Dict[str, Tuple[str, ...]]
    outcome: Optional[str] = None


@dataclass(frozen=True)
class DoneMark:
    """One mark in the review's Done history: <kind> is "done" (a reviewer
    marked it at <commit>), "undone" (a reviewer undid it; <commit> is the one
    it was Done at) or "cleared" (a new commit, <commit>, cleared it)."""
    kind: str
    time: str
    commit: str


@dataclass(frozen=True)
class DoneStatus:
    """Whether the review is Done now, for a viewer or a script.

    done          Done at the head commit, with <mark> (kind "done") saying when and where
    last_mark     the last mark: done, undone, or cleared by a commit (None for none ever).
                  A review Done at an older commit than <head> is not done: its last mark
                  is then the clearing by <head>, whether or not it has been kept yet
    head          the commit the review's branch is at now (None: the repository has no such branch)
    open_threads  how many threads are open
    in_flight     how many of them have a run queued or working
    """
    done: bool
    mark: Optional[DoneMark]
    last_mark: Optional[DoneMark]
    head: Optional[str]
    open_threads: int
    in_flight: int


@dataclass(frozen=True)
class ModeStatus:
    """The review mode, for a viewer or a reviewing agent.

    mode       live or batched
    held       the ids of the held threads, oldest first
    submitted  the ids of the threads a submit (or a change to live) just
               sent to the coding agent: they wait for a run now. () when
               it sent none, or nothing was submitted
    """
    mode: str
    held: Tuple[str, ...]
    submitted: Tuple[str, ...] = ()


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
class NoteWritten:
    """difftate wrote a note, or changed one (the "note" line). Only a final
    note is kept for good: one that isn't final yet lasts only as long as the
    process, held by NotesInProgress (see lasting)."""
    thread_id: str
    comment: Comment
    final: bool


@dataclass(frozen=True)
class ThreadStatusChanged:
    """A reviewer opened, resolved or dismissed a thread (the "status" line).
    <by>: the reviewer name, as on a Comment."""
    thread_id: str
    status: str
    time: str
    by: Optional[str] = None


@dataclass(frozen=True)
class ThreadMoved:
    """Only the line numbers of the thread's code changed: its anchor moved to
    <start_line>..<end_line> in the file as it is now (<snapshot_id>) (the
    "moved" line)."""
    thread_id: str
    start_line: int
    end_line: int
    snapshot_id: Optional[str]
    time: str


@dataclass(frozen=True)
class ThreadOutdated:
    """A thread's code changed after it was written (the "outdated" line)."""
    thread_id: str
    time: str


@dataclass(frozen=True)
class RunStarted:
    """A run started on <threads> (the "run" line): see Run."""
    run_id: str
    threads: Tuple[str, ...]
    sent: Tuple[str, ...]
    replies_before: Dict[str, Tuple[str, ...]]
    time: str


@dataclass(frozen=True)
class RunEnded:
    """A run ended, with its <outcome> (the "run-ended" line)."""
    run_id: str
    outcome: str
    time: str


@dataclass(frozen=True)
class FileViewed:
    """The reviewer marked <file> viewed when its diff in the changeset had
    <diff_hash>, or unmarked it (<diff_hash> None) (the "viewed" line)."""
    file: str
    diff_hash: Optional[str]
    time: str


@dataclass(frozen=True)
class DoneMarked:
    """A reviewer marked the review Done at <commit> (the "done" line)."""
    commit: str
    time: str


@dataclass(frozen=True)
class DoneUndone:
    """A reviewer undid Done, which it was at <commit> (the "undone" line)."""
    commit: str
    time: str


@dataclass(frozen=True)
class DoneCleared:
    """The branch got a new commit, <commit>: the review is no longer Done
    (the "done-cleared" line)."""
    commit: str
    time: str


@dataclass(frozen=True)
class ModeChanged:
    """A reviewer changed the review mode to <mode>, live or batched (the
    "mode" line)."""
    mode: str
    time: str


@dataclass(frozen=True)
class AgentOverridden:
    """A reviewer chose <agent> to reply in this review, whatever the repository
    says, or cleared the choice with "" (the "agent" line). The name is the
    machine's agent list's: the core doesn't know the list."""
    agent: str
    time: str


@dataclass(frozen=True)
class ReviewSubmitted:
    """A reviewer submitted the review: its held <threads> wait for a run now
    (the "submitted" line). A change from batched to live with threads held
    submits them first."""
    threads: Tuple[str, ...]
    time: str


def submitted(events: List[Event]) -> Tuple[str, ...]:
    """The ids of the threads <events> submitted: () when they hold no submit."""
    return next((e.threads for e in events if isinstance(e, ReviewSubmitted)), ())


Event = Union[ThreadOpened, CommentAdded, NoteWritten, ThreadStatusChanged, ThreadMoved, ThreadOutdated,
              RunStarted, RunEnded, FileViewed, DoneMarked, DoneUndone, DoneCleared, ModeChanged,
              AgentOverridden, ReviewSubmitted]


def lasting(events: List[Event]) -> List[Event]:
    """The events kept for good, in the store and the review history: all but a
    note that isn't final yet. A progress note changes with every step of its
    run, so only its final body is kept (ADR 0004); until then NotesInProgress
    holds it. The core decides this, so a store keeps every event it is given."""
    return [e for e in events if not (isinstance(e, NoteWritten) and not e.final)]


class NotesInProgress:
    """The notes that aren't final yet, in this process's memory: each one's
    last write. They are lost when the process ends, as they always were.
    A use case rebuilds the Review from the store's events and these, so a
    note shows, and keeps its place, while its run works."""

    def __init__(self) -> None:
        self._written: Dict[str, NoteWritten] = {}  # note id: its last write, in the order first written

    def events(self) -> List[Event]:
        return list(self._written.values())

    def hold(self, events: List[Event]) -> None:
        """Hold each note in <events> that isn't final yet; let go of one that is."""
        for event in events:
            if isinstance(event, NoteWritten):
                if event.final:
                    self._written.pop(event.comment.id, None)
                else:
                    self._written[event.comment.id] = event


def _need_branch(on_branch: bool) -> None:
    """While another branch is checked out (the watcher moves to its review
    after the run in progress), the files on disk aren't this review's: nothing
    that reads them changes the review."""
    if not on_branch:
        raise Conflict("another branch is checked out: the watcher moves to its review "
                       "once the run in progress ends")


def _replies(thread: Thread) -> Set[str]:
    return {c.id for c in thread.comments if c.kind == "reply"}


# ── The Review ───────────────────────────────────────────────────────────────
class Review:
    def __init__(self) -> None:
        self._threads: Dict[str, Thread] = {}  # id: thread, in the order they were opened
        self._seq = 0  # the last comment's place in the review
        self._final: Set[str] = set()  # ids of the notes that won't change again
        self._runs: Dict[str, Run] = {}  # id: run, in the order they started
        self._viewed: Dict[str, str] = {}  # file: the hash of its diff when the reviewer marked it viewed
        self._snapshots: Set[str] = set()  # the id of every snapshot a thread had
        self._done: Optional[DoneMark] = None  # the mark that made the review Done, while it is
        self._last_mark: Optional[DoneMark] = None  # the last Done mark of any kind
        self._mode = LIVE  # a review with no mode event is live
        self._agent = ""  # the agent chosen for this review: "" for none
        self._submitted_at = 0  # the last comment's place in the review at the latest submit
        self._answered: Set[str] = set()  # ids of comments a reply on their held thread answered

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

    def threads(self, status: Optional[str] = None) -> List[Thread]:
        """The threads, oldest first; with a <status>, only those with it."""
        return [t for t in self._threads.values() if status is None or t.status == status]

    def snapshots(self) -> Set[str]:
        """The id of every snapshot the review's threads ever had: the one each
        was written on, and each it moved to. All of them are kept, the review
        history's too, outdated threads included."""
        return set(self._snapshots)

    def runs(self) -> List[Run]:
        """The runs, oldest first."""
        return list(self._runs.values())

    def in_progress(self) -> Set[str]:
        """The ids of the threads a run in progress has."""
        return {tid for run in self._runs.values() if run.outcome is None for tid in run.threads}

    def failed_among(self, thread_ids: Collection[str]) -> List[Thread]:
        """The open threads among <thread_ids> whose run ended with no reply to them."""
        return [t for t in self.threads("open") if t.id in thread_ids and self.state(t.id) == "failed"]

    def unsent(self, thread_id: str) -> List[str]:
        """The ids of the thread's reviewer comments that no run has been sent
        yet, and that no reply answered while their thread was held."""
        sent = {cid for run in self._runs.values() for cid in run.sent} | self._answered
        return [c.id for c in self.thread(thread_id).comments if c.author == REVIEWER and c.id not in sent]

    def state(self, thread_id: str) -> Optional[str]:
        """Rule 4: where an open thread stands in the loop (None for a resolved
        or dismissed one).

          held      the review is batched, and it has a reviewer's comment that
                    no run has been sent yet, written since the latest submit:
                    it waits for the reviewer to submit
          waiting   it has a reviewer's comment that no run has been sent yet
          queued    waiting while a run handles other threads
          working   the run in progress has it
          replied   the coding agent spoke last, and every reviewer comment was sent to a run
          failed    its run ended with no reply to it
        """
        thread = self.thread(thread_id)
        if thread.status != "open":
            return None
        running = self.in_progress()
        if thread.id in running:
            return "working"
        unsent = self.unsent(thread.id)
        if self._held(thread, unsent):
            return "held"
        if unsent:
            return "queued" if running else "waiting"
        # A reply to an earlier comment doesn't answer a later one: only a reply
        # written since the last run started does
        before: Tuple[str, ...] = ()
        for run in self._runs.values():
            before = run.replies_before.get(thread.id, before)
        return "replied" if _replies(thread) - set(before) else "failed"

    def _held(self, thread: Thread, unsent: List[str]) -> bool:
        """Whether the thread, with the <unsent> comments, is held: the review
        is batched, and its newest comment no run was sent came after the
        latest submit."""
        if self._mode != BATCHED or not unsent:
            return False
        newest = next(c for c in reversed(thread.comments) if c.id == unsent[-1])
        return newest.seq > self._submitted_at

    def open_thread(self, author: str, body: str, anchor: Optional[Anchor] = None,
                    snapshot: Optional[Snapshot] = None, on_branch: bool = True,
                    shown: Optional[Snapshot] = None, since: Union[None, Moved, Outdated] = None,
                    by: Optional[str] = None) -> List[Event]:
        """A thread on <anchor>, or a general thread (no anchor), with <author>'s
        first comment, written by the reviewer named <by>. <snapshot> is the
        anchor's file now, from the code reader: needed with an anchor.
        <on_branch>: whether the review's branch is checked out (see
        _need_branch).

        <shown> is the version of the file the viewer showed, when it said
        which (the anchor's snapshot_id) and it isn't the file now; <since> is
        how the anchor's lines changed from it to the file now (core/changes,
        moved_or_outdated)."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer opens a thread")
        _need_branch(on_branch)
        thread_id, time = _new_id(), _now()
        outdated, moved_since = False, None
        if anchor is not None:
            # The thread is written on the version the viewer showed, when it
            # has the viewer's code on those lines; else on the file now
            on_shown = shown is not None and shown.code is not None and (
                anchor.code is None or same_code(anchor.code, shown.code))
            written_on = shown if on_shown else snapshot
            # With no code from the viewer, the thread is written on the code there
            code = written_on.code if anchor.code is None else anchor.code
            anchor = replace(anchor, code=code, snapshot_id=written_on.id, commit=written_on.commit)
            if on_shown:
                # Since the viewer showed it, the code moved (it moves with it) or changed
                moved_since = since
            else:
                # A thread is written on the code the viewer showed. If the file no
                # longer has that code there, it changed since: outdated at once
                outdated = snapshot.code is None or not same_code(anchor.code, snapshot.code)
        events: List[Event] = [
            ThreadOpened(thread_id, anchor, time),
            CommentAdded(thread_id, Comment(_new_id(), author, "comment", body, time, self._seq + 1, by)),
        ]
        if outdated:
            events.append(ThreadOutdated(thread_id, time))
        for event in events:
            self.apply(event)
        if moved_since is not None:
            events += self.move_with_code({thread_id: moved_since})
        return events

    def add_comment(self, author: str, thread_id: str, kind: str, body: str,
                    by: Optional[str] = None) -> List[Event]:
        """<author>'s comment, reply or note (<kind> says which) at the end of the
        thread; <by>: the reviewer name of a reviewer's comment. Rule 2: each
        author writes only their own kind. Rule 1: only a reviewer has a
        reviewer name."""
        thread = self.thread(thread_id)
        if AUTHOR_OF.get(kind) != author:
            raise NotAllowed(f"{author} doesn't write a {kind}")
        if by is not None and author != REVIEWER:
            raise NotAllowed(f"{author} has no reviewer name: only a reviewer does")
        comment = Comment(_new_id(), author, kind, body, _now(), self._seq + 1, by)
        event: Event = (NoteWritten(thread.id, comment, final=False) if kind in NOTE_KINDS
                        else CommentAdded(thread.id, comment))
        self.apply(event)
        return [event]

    def edit_note(self, author: str, note_id: str, kind: str, body: str, final: bool = False) -> List[Event]:
        """difftate changes a note's kind and body; <final> when the note won't
        change again (Dispatch says so when a run ends). Rule 3: only difftate
        writes notes, and only notes can be edited. A final note doesn't change
        again, so a late edit can't undo a run's final line."""
        if author != DIFFTATE:
            raise NotAllowed("only difftate edits a note")
        found = next(((t, c) for t in self._threads.values() for c in t.comments if c.id == note_id), None)
        if found is None:
            raise NotFound(f"no note {note_id}")
        thread, note = found
        if note.kind not in NOTE_KINDS:
            raise NotAllowed(f"{note_id} is not a note: only notes can be edited")
        if kind not in NOTE_KINDS:
            raise NotAllowed("a note stays a note")
        if note_id in self._final:
            raise Conflict(f"the note {note_id} is final")
        event = NoteWritten(thread.id, replace(note, kind=kind, body=body), final)
        self.apply(event)
        return [event]

    def set_status(self, author: str, thread_id: str, status: str, by: Optional[str] = None) -> List[Event]:
        """<status>: open, resolved or dismissed, set by the reviewer named <by>.
        Rule 1: only a reviewer changes it."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer changes a thread's status")
        event = ThreadStatusChanged(self.thread(thread_id).id, status, _now(), by)
        self.apply(event)
        return [event]

    # ── Moving with the code ─────────────────────────────────────────────────
    def move_with_code(self, found: Dict[str, Union[Moved, Outdated]]) -> List[Event]:
        """Each thread in <found> moves with its code (Moved: only its line
        numbers changed) or is outdated (its code changed), as the code reader
        and core/changes found. Only difftate moves threads: no reviewer or
        coding agent can. An outdated thread stays outdated, keeps the lines
        it had and never moves again; a general thread has no code."""
        events: List[Event] = []
        for thread_id, decided in found.items():
            thread = self.thread(thread_id)
            if thread.anchor is None or thread.outdated:
                continue
            if isinstance(decided, Moved):
                events.append(ThreadMoved(thread_id, decided.start_line, decided.end_line, decided.snapshot_id,
                                          _now()))
            else:
                events.append(ThreadOutdated(thread_id, _now()))
        for event in events:
            self.apply(event)
        return events

    # ── Viewed files ─────────────────────────────────────────────────────────
    def viewed(self) -> Dict[str, str]:
        """The files marked viewed: {file: the hash of its diff when marked}."""
        return dict(self._viewed)

    def mark_viewed(self, file: str, viewed: bool, diff_hashes: Dict[str, str],
                    on_branch: bool = True) -> List[Event]:
        """The reviewer viewed <file> as its diff is now (or unmarked it,
        <viewed> False). <diff_hashes>: {file: the hash of its diff in the
        changeset now}, from the code reader."""
        _need_branch(on_branch)
        if viewed and file not in diff_hashes:
            raise NotFound(f"{file} is not in the changeset")
        event = FileViewed(file, diff_hashes[file] if viewed else None, _now())
        self.apply(event)
        return [event]

    def clear_changed_marks(self, diff_hashes: Dict[str, str]) -> List[Event]:
        """A file stays viewed until its diff in the changeset changes: then its
        mark is cleared, so undoing the change doesn't bring it back."""
        events: List[Event] = [FileViewed(f, None, _now()) for f, diff_hash in self._viewed.items()
                               if diff_hashes.get(f) != diff_hash]
        for event in events:
            self.apply(event)
        return events

    # ── Done ─────────────────────────────────────────────────────────────────
    def done(self) -> Optional[DoneMark]:
        """The mark that made the review Done (kind "done"), or None when it
        isn't, as the events left it: a new commit clears it only once
        clear_done says so."""
        return self._done

    def last_done_mark(self) -> Optional[DoneMark]:
        """The last mark of any kind: done, undone or cleared."""
        return self._last_mark

    def clear_done(self, head: Optional[str]) -> List[Event]:
        """Rule 5: the branch is at <head> now. A review Done at another commit
        is cleared by it. None for <head> (the branch is gone, after a merge
        and a delete) clears nothing."""
        if self._done is None or head is None or head == self._done.commit:
            return []
        event = DoneCleared(head, _now())
        self.apply(event)
        return [event]

    def mark_done(self, author: str, head: Optional[str], on_branch: bool = True) -> List[Event]:
        """<author> marks the review Done at <head>, the commit the branch is
        at. Rule 5: only a reviewer does. A review already Done at <head> is
        left as it is; one Done at an older commit is cleared first. Raises
        Conflict while another branch is checked out (_need_branch), and
        CouldNotRead with no <head>: there is no commit to be Done at."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer marks a review Done")
        _need_branch(on_branch)
        if head is None:
            raise CouldNotRead("could not read the commit the review's branch is at")
        events = self.clear_done(head)
        if self._done is None:
            event = DoneMarked(head, _now())
            self.apply(event)
            events.append(event)
        return events

    def undo_done(self, author: str, head: Optional[str]) -> List[Event]:
        """<author> undoes Done. Rule 5: only a reviewer does. Done at an
        older commit than <head> was cleared by it already: that is recorded,
        not an undo. Nothing when the review isn't Done."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer undoes Done")
        events = self.clear_done(head)
        if self._done is not None:
            event = DoneUndone(self._done.commit, _now())
            self.apply(event)
            events.append(event)
        return events

    def done_status(self, head: Optional[str]) -> DoneStatus:
        """Whether the review is Done with the branch at <head>, and the
        threads still open. A review Done at another commit is not: it shows
        the clearing a new commit makes, as clear_done would keep it, and
        changes nothing."""
        done, last = self._done, self._last_mark
        if done is not None and head is not None and head != done.commit:
            done, last = None, DoneMark("cleared", _now(), head)
        open_threads = self.threads("open")
        in_flight = [t for t in open_threads if self.state(t.id) in ("queued", "working")]
        return DoneStatus(done is not None, done, last, head, len(open_threads), len(in_flight))

    # ── Review mode ──────────────────────────────────────────────────────────
    def mode(self) -> str:
        """The review mode: live or batched."""
        return self._mode

    def held(self) -> List[Thread]:
        """The held threads, oldest first."""
        return [t for t in self.threads("open") if self.state(t.id) == "held"]

    def mode_status(self, events: Optional[List[Event]] = None) -> ModeStatus:
        """The review mode and its held threads, with the threads <events>
        (the ones a change just returned) submitted."""
        return ModeStatus(self._mode, tuple(t.id for t in self.held()), submitted(events or []))

    def submit(self, author: str) -> List[Event]:
        """<author> submits the review: its held threads wait for a run. Rule
        6: only a reviewer does. Nothing when no thread is held, so a submit
        with nothing to send leaves no mark."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer submits a review")
        held = self.held()
        if not held:
            return []
        event = ReviewSubmitted(tuple(t.id for t in held), _now())
        self.apply(event)
        return [event]

    def set_mode(self, author: str, mode: str) -> List[Event]:
        """<author> changes the review mode to <mode>. Rule 6: only a reviewer
        does. A change to live submits the held threads first. A change to
        batched leaves a run in progress alone, and holds every other thread
        with a comment no run has been sent yet, until the reviewer submits.
        Nothing when the review is in <mode> already; ValueError for a mode
        that isn't one."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer changes the review mode")
        if mode not in MODES:
            raise ValueError(f"no review mode {mode!r}: {LIVE} or {BATCHED}")
        if mode == self._mode:
            return []
        events = self.submit(author) if mode == LIVE else []
        event = ModeChanged(mode, _now())
        self.apply(event)
        return events + [event]

    # ── Agent override ───────────────────────────────────────────────────────
    def agent_override(self) -> str:
        """The agent a reviewer chose for this review: "" when none."""
        return self._agent

    def set_agent_override(self, author: str, agent: str) -> List[Event]:
        """<author> chooses <agent> to reply in this review, or "" to clear the
        choice. Rule 6: only a reviewer does. Nothing when it is chosen already."""
        if author != REVIEWER:
            raise NotAllowed("only a reviewer chooses the agent of a review")
        if agent == self._agent:
            return []
        event = AgentOverridden(agent, _now())
        self.apply(event)
        return [event]

    # ── Runs (Dispatch) ──────────────────────────────────────────────────────
    def start_run(self, thread_ids: List[str], in_prompt: Optional[Collection[str]] = None) -> List[Event]:
        """A run starts on the threads: every reviewer comment in them that no
        run was sent is sent to it. <in_prompt>: the ids of the comments the
        run's prompt shows, as Dispatch read the threads (None: all of them).
        A comment written since isn't in the prompt, so it isn't sent: it waits
        for the next run."""
        threads = [self.thread(tid) for tid in thread_ids]
        event = RunStarted(_new_id(), tuple(t.id for t in threads),
                           tuple(cid for t in threads for cid in self.unsent(t.id) if in_prompt is None or cid in in_prompt),
                           {t.id: tuple(sorted(_replies(t))) for t in threads}, _now())
        self.apply(event)
        return [event]

    def end_run(self, outcome: str) -> List[Event]:
        """The run in progress ended (<outcome>: done, failed or stopped). No
        events when no run is in progress."""
        running = [run for run in self._runs.values() if run.outcome is None]
        if not running:
            return []
        event = RunEnded(running[-1].id, outcome, _now())
        self.apply(event)
        return [event]

    def recover_runs(self) -> List[Event]:
        """At start: a run that never ended (its watcher was killed) ends as
        interrupted. Its threads with no reply are failed then."""
        events: List[Event] = [RunEnded(run.id, "interrupted", _now())
                               for run in self._runs.values() if run.outcome is None]
        for event in events:
            self.apply(event)
        return events

    def apply(self, event: Event) -> None:
        """The one place the Review's state changes."""
        if isinstance(event, ThreadOpened):
            self._threads[event.thread_id] = Thread(event.thread_id, event.anchor)
            if event.anchor is not None and event.anchor.snapshot_id:
                self._snapshots.add(event.anchor.snapshot_id)
        elif isinstance(event, (CommentAdded, NoteWritten)):
            thread, comment = self._threads[event.thread_id], event.comment
            if comment.kind == "reply" and self.state(thread.id) == "held":
                # A reply on a held thread answers it: a later submit doesn't send it
                self._answered.update(self.unsent(thread.id))
            # A note written again replaces itself, in its place
            others = tuple(c for c in thread.comments if c.id != comment.id)
            comments = tuple(sorted(others + (comment,), key=lambda c: c.seq))
            self._threads[thread.id] = replace(thread, comments=comments)
            self._seq = max(self._seq, comment.seq)
            if isinstance(event, NoteWritten) and event.final:
                self._final.add(comment.id)
        elif isinstance(event, ThreadStatusChanged):
            self._threads[event.thread_id] = replace(self._threads[event.thread_id], status=event.status,
                                                     status_by=event.by)
        elif isinstance(event, ThreadMoved):
            thread = self._threads[event.thread_id]
            anchor = replace(thread.anchor, start_line=event.start_line, end_line=event.end_line,
                             snapshot_id=event.snapshot_id)
            self._threads[thread.id] = replace(thread, anchor=anchor)
            self._snapshots.add(event.snapshot_id)
        elif isinstance(event, ThreadOutdated):
            self._threads[event.thread_id] = replace(self._threads[event.thread_id], outdated=True)
        elif isinstance(event, RunStarted):
            self._runs[event.run_id] = Run(event.run_id, event.threads, event.sent, event.replies_before)
        elif isinstance(event, RunEnded):
            self._runs[event.run_id] = replace(self._runs[event.run_id], outcome=event.outcome)
        elif isinstance(event, FileViewed):
            if event.diff_hash is None:
                self._viewed.pop(event.file, None)
            else:
                self._viewed[event.file] = event.diff_hash
        elif isinstance(event, (DoneMarked, DoneUndone, DoneCleared)):
            kind = {DoneMarked: "done", DoneUndone: "undone", DoneCleared: "cleared"}[type(event)]
            self._last_mark = DoneMark(kind, event.time, event.commit)
            self._done = self._last_mark if kind == "done" else None
        elif isinstance(event, AgentOverridden):
            self._agent = event.agent
        elif isinstance(event, ReviewSubmitted):
            self._submitted_at = self._seq
        elif isinstance(event, ModeChanged):
            self._mode = event.mode
            if event.mode == LIVE:  # a change to live submits
                self._submitted_at = self._seq
