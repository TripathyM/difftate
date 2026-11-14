"""Opening a thread: a reviewer writes the first comment, on an anchor or on
the changeset as a whole."""
from __future__ import annotations

from typing import Optional, Tuple, Union

from ...changes.model import Moved, Outdated, Snapshot, moved_or_outdated
from ...changes.ports import ForReadingTheCode
from ..model import Anchor, CouldNotRead, ListedThread, NotesInProgress, Review, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def open_thread(store: ForKeepingTheReview, notes: NotesInProgress, code: ForReadingTheCode,
                history: ForRecordingReviewHistory, author: str, body: str,
                anchor: Optional[Anchor] = None, by: Optional[str] = None) -> ListedThread:
    """A thread on <anchor> (None: a general thread), with <author>'s comment
    <body> by the reviewer named <by>, and its thread state now. Raises
    NotAllowed for anyone but a reviewer, Conflict while another branch is
    checked out, and CouldNotRead when the code can't be read; nothing is
    kept then."""
    review = Review.from_events(store.load() + notes.events())  # notes too: a comment's seq comes after them
    on_branch = code.on_branch()
    snapshot, shown, since = None, None, None
    if anchor is not None and on_branch:  # off the branch, the files on disk aren't this review's
        snapshot = code.snapshot(anchor.file, anchor.side, anchor.view, anchor.start_line, anchor.end_line)
        if anchor.snapshot_id is not None and anchor.snapshot_id != snapshot.id:
            shown, since = _since_shown(code, anchor, snapshot)
    events = review.open_thread(author, body, anchor, snapshot, on_branch, shown, since, by)
    store.append(lasting(events))
    history.record(lasting(events))
    if snapshot is not None:
        try:
            code.keep(review.snapshots())  # so git gc can't take it
        except CouldNotRead:
            pass  # the thread is kept: the next poll keeps its snapshot (move_with_code)
    thread_id = events[0].thread_id  # events[0] is the ThreadOpened
    return ListedThread(review.thread(thread_id), review.state(thread_id))


def _since_shown(code: ForReadingTheCode, anchor: Anchor,
                 now: Snapshot) -> Tuple[Optional[Snapshot], Union[None, Moved, Outdated]]:
    """The version of the file the viewer showed (the anchor's snapshot_id),
    with the code on the anchor's lines in it, and how those lines changed
    from it to the file <now>. (None, None) when the code reader can't read
    that version: the thread is written on the file now, as with no version."""
    shown_id = anchor.snapshot_id
    try:
        shown_code = code.code_on_lines(shown_id, anchor.start_line, anchor.end_line)
        if shown_code is None:
            return None, None
        hunks = None if now.id is None else code.hunks(shown_id, now.id)
    except CouldNotRead:
        return None, None
    return (Snapshot(shown_id, now.commit, shown_code),
            moved_or_outdated(anchor.start_line, anchor.end_line, shown_id, now.id, hunks))
