"""Listing threads, each with its thread state, and in a view where its code
is there."""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from ...changes.model import FileInView, lines_in_view
from ...changes.ports import ForReadingTheCode
from ..model import Anchor, CouldNotRead, ListedThread, NotesInProgress, Review
from ..ports import ForKeepingTheReview


def list_threads(store: ForKeepingTheReview, notes: NotesInProgress, code: ForReadingTheCode,
                 status: Optional[str] = None, view: Optional[str] = None) -> List[ListedThread]:
    """The threads, oldest first, with the notes that aren't final yet, each
    with its thread state. With a <status>, only those with it. With a <view>
    ("" for all changes), each thread is placed where its code is in that
    view, or listed not in the view.

    While another branch is checked out, the code on disk is that branch's:
    no thread with an anchor is placed in it, whatever the view."""
    review = Review.from_events(store.load() + notes.events())
    listed = [ListedThread(t, review.state(t.id)) for t in review.threads(status)]
    if not code.on_branch():
        return [t._replace(in_view=False) if t.thread.anchor else t for t in listed]
    if view is None:
        return listed
    return _placed(code, listed, view)


def _placed(code: ForReadingTheCode, listed: List[ListedThread], view: str) -> List[ListedThread]:
    """Each thread on the lines its code has in <view>: its snapshot diffed
    against the file there. An outdated thread keeps its lines, as it never
    sits next to code; so does a thread whose file can't be read now."""
    placeable: Dict[str, Tuple[Anchor, str]] = {}  # thread id: its anchor and snapshot
    for t in listed:
        a = t.thread.anchor
        if a is not None and not t.thread.outdated and a.snapshot_id:
            placeable[t.thread.id] = (a, a.snapshot_id)
    files = {tid: FileInView(a.file, a.side, view) for tid, (a, _) in placeable.items()}
    there = code.versions(list(dict.fromkeys(files.values()))) if files else {}
    placed = []
    for t in listed:
        if t.thread.id not in placeable or files[t.thread.id] not in there:
            placed.append(t)
            continue
        (anchor, snapshot), there_id = placeable[t.thread.id], there[files[t.thread.id]]
        try:
            hunks = None if there_id is None or there_id == snapshot else code.hunks(snapshot, there_id)
        except CouldNotRead:
            placed.append(t)
            continue
        lines = lines_in_view(anchor.start_line, anchor.end_line, snapshot, there_id, hunks)
        if lines is None:
            placed.append(t._replace(in_view=False))
        else:
            moved = replace(anchor, start_line=lines[0], end_line=lines[1])
            placed.append(t._replace(thread=replace(t.thread, anchor=moved)))
    return placed
