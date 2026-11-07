"""The Changes model: views, snapshots, and the decision that moves a thread
with its code or makes it outdated.

The code reader (ports.py) hands back plain data: a Snapshot, the id of a
file now, the hunks of a diff, the code on some lines. It makes no decision.
The decision is here, in pure functions:

  moved_or_outdated          a thread with a snapshot: its lines mapped
                             through the diff from the snapshot to the file now
  moved_or_outdated_by_code  a thread written before snapshots existed: its
                             code compared with the code on its lines now
  lines_in_view              where a thread's lines are in a view

Nothing is found by its text, so the same code twice in a file can't move a
thread to the wrong copy. same_code is how the core tells whether a thread's
code changed: the Review uses it when a thread is opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Optional, Sequence, Tuple, Union

NAMED_VIEWS = ("staged", "unstaged")


@dataclass(frozen=True)
class View:
    """The part of the review's changes the reviewer looks at (GLOSSARY.md):

    ""        all changes (the default): from where the branch left the base
              to the files on disk
    <commit>  the commits after it, and the files on disk: HEAD~2 is the last
              two commits; HEAD is the uncommitted changes
    staged    what is staged
    unstaged  what isn't staged yet

    A thread written in any view belongs to the review.
    """
    given: str = ""

    @property
    def is_all_changes(self) -> bool:
        return self.given == ""

    @property
    def name(self) -> str:
        """How the terminal names the view."""
        if self.is_all_changes:
            return "all changes"
        if self.given == "HEAD":
            return "uncommitted changes"
        if self.given in NAMED_VIEWS:
            return f"{self.given} changes"
        return f"the commits after {self.given}"


@dataclass(frozen=True)
class Changeset:
    """The review's changeset in a view.

    view    the view ("" for all changes)
    base    the review's base
    commit  where the branch left the base
    diff    the changes, as a unified diff (new untracked files included)
    """
    view: str
    base: str
    commit: str
    diff: str


@dataclass(frozen=True)
class Snapshot:
    """A file on one side of a view, kept as it was when a thread was written
    on it, so the thread can move with its code later.

    id      where the code reader keeps the file (the git adapter: its blob); None when
            there is no such file
    commit  the commit checked out when the snapshot was taken
    code    the code on the thread's lines in the file; None when the file
            has no such lines
    """
    id: Optional[str]
    commit: str
    code: Optional[str]


class FileInView(NamedTuple):
    """A file on one <side> ("old" or "new") of a <view> ("" for all changes)."""
    file: str
    side: str
    view: str = ""


class Hunk(NamedTuple):
    """One change in a diff with no context lines. A count of 0 means lines
    added after (old) or removed after (new) the start line."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True)
class Moved:
    """Only the line numbers of a thread's code changed: it is on
    <start_line>..<end_line> of the file now, kept as <snapshot_id>."""
    start_line: int
    end_line: int
    snapshot_id: str


@dataclass(frozen=True)
class Outdated:
    """A thread's code changed after it was written, or is gone."""


OUTDATED = Outdated()


def map_lines(hunks: Sequence[Hunk], start: int, end: int) -> Optional[Tuple[int, int]]:
    """Lines <start>..<end> of a file, mapped through a diff's <hunks> (in
    order): the lines they are now, or None when the diff changed any of them
    (or added a line between them)."""
    shift = 0
    for old_start, old_count, new_start, new_count in hunks:
        if old_count == 0:  # lines added after line old_start
            if old_start >= end:
                break
            if old_start >= start:
                return None
            shift += new_count
            continue
        if old_start > end:
            break
        if old_start + old_count - 1 >= start:
            return None
        shift += new_count - old_count
    return start + shift, end + shift


def moved_or_outdated(start_line: int, end_line: int, snapshot_id: str, now_id: Optional[str],
                      hunks: Optional[Sequence[Hunk]]) -> Union[None, Moved, Outdated]:
    """Where the code on lines <start_line>..<end_line> of a thread's snapshot
    is in the file now (<now_id>; None when there is no such file). <hunks>
    are the diff from the snapshot to the file now, needed only when the file
    changed; None when there is nothing to diff (the snapshot is lost).

    None when its code is still on its lines, Moved when only their numbers
    changed, OUTDATED when the code changed or is gone.
    """
    if now_id == snapshot_id:
        return None
    lines = None if now_id is None or hunks is None else map_lines(hunks, start_line, end_line)
    if lines is None:
        return OUTDATED
    if lines == (start_line, end_line):
        return None
    return Moved(lines[0], lines[1], now_id)


def moved_or_outdated_by_code(start_line: int, end_line: int, code: Optional[str], now_id: Optional[str],
                              code_now: Optional[str]) -> Union[None, Moved, Outdated]:
    """A thread written before snapshots existed has no snapshot to diff. If
    its <code> is still on its lines in the file now (<code_now>), it starts
    moving with its code from the file now (<now_id>); else it is outdated.
    None when there is no such file now: nothing to start from."""
    if now_id is None:
        return None
    if code is not None and code_now is not None and same_code(code, code_now):
        return Moved(start_line, end_line, now_id)
    return OUTDATED


def lines_in_view(start_line: int, end_line: int, snapshot_id: str, there_id: Optional[str],
                  hunks: Optional[Sequence[Hunk]]) -> Optional[Tuple[int, int]]:
    """Where a thread's lines are in a view: the file on its side there is
    <there_id> (None when it isn't there), and <hunks> the diff from the
    snapshot to it, needed only when it isn't the snapshot. None when its code
    isn't in the view, or changed there."""
    if there_id == snapshot_id:
        return start_line, end_line
    if there_id is None or hunks is None:
        return None
    return map_lines(hunks, start_line, end_line)


def same_code(a: str, b: str) -> bool:
    """The same lines, whatever the line endings."""
    def lines(s: str) -> list:
        return [line.rstrip("\r") for line in s.rstrip("\r\n").split("\n")]
    return lines(a) == lines(b)
