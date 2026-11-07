"""Moving threads with their code: when only the line numbers of a thread's
code changed, its anchor moves with it; when the code itself changed, the
thread is outdated (GLOSSARY.md, Anchor)."""
from __future__ import annotations

from typing import Dict, List, Union

from ...changes.model import FileInView, Moved, Outdated, moved_or_outdated, moved_or_outdated_by_code
from ...changes.ports import ForReadingTheCode
from ..model import Anchor, CouldNotRead, Review, ThreadOutdated, lasting
from ..ports import ForKeepingTheReview, ForRecordingReviewHistory


def move_with_code(store: ForKeepingTheReview, code: ForReadingTheCode,
                   history: ForRecordingReviewHistory) -> List[str]:
    """Each thread that isn't outdated moves with its code, or is outdated;
    the moves are kept and recorded. Returns the ids of the threads that
    became outdated.

    A thread only moves on a sure answer: nothing moves while another branch
    is checked out (or when one was checked out while the code was read), and
    a thread whose code can't be read now stays as it is. The anchor keeps its
    view, so a thread on the old side of HEAD~1 moves with its code there."""
    review = Review.from_events(store.load())
    anchored: Dict[str, Anchor] = {t.id: t.anchor for t in review.threads()
                                   if t.anchor is not None and not t.outdated}
    if not anchored or not code.on_branch():
        return []
    files = {tid: FileInView(a.file, a.side, a.view) for tid, a in anchored.items()}
    now = code.versions(list(dict.fromkeys(files.values())))
    found: Dict[str, Union[Moved, Outdated]] = {}
    for tid, a in anchored.items():
        if files[tid] not in now:
            continue  # it can't be read now
        now_id = now[files[tid]]
        if now_id == a.snapshot_id:
            continue
        try:
            if a.snapshot_id is None:  # written before snapshots existed
                code_now = None if now_id is None else code.code_on_lines(now_id, a.start_line, a.end_line)
                decided = moved_or_outdated_by_code(a.start_line, a.end_line, a.code, now_id, code_now)
            else:
                hunks = None if now_id is None else code.hunks(a.snapshot_id, now_id)
                decided = moved_or_outdated(a.start_line, a.end_line, a.snapshot_id, now_id, hunks)
        except CouldNotRead:
            continue
        if decided is not None:
            found[tid] = decided
    # A checkout while the code was read: what it found may be the other branch's
    if not found or not code.on_branch():
        return []
    events = review.move_with_code(found)
    store.append(lasting(events))
    history.record(lasting(events))
    return [e.thread_id for e in events if isinstance(e, ThreadOutdated)]
