"""The Changes context's driven port: reading the code.

A code reader hands back plain data and decides nothing: whether a thread
moved with its code or is outdated is decided in model.py. The git adapter
(adapters/outbound/git) plugs git in; tests use a fake code reader. Both run
one contract (tests/test_code_reader_contract.py).

A file is named by an id: where the code reader keeps that version of it
(the git adapter: its blob). The same file with the same text has the same
id, so a file that is its snapshot has the snapshot's id.
"""
from __future__ import annotations

from typing import Collection, Dict, List, Optional, Protocol, Sequence

from .model import Changeset, FileInView, Hunk, Snapshot


class ForReadingTheCode(Protocol):
    # ── For a new thread ─────────────────────────────────────────────────────
    def snapshot(self, file: str, side: str, view: str, start_line: int, end_line: int) -> Snapshot:
        """<file> on <side> ("old" or "new") of <view> ("" for all changes) as it
        is now, kept so a thread can move with its code later, and the code on
        lines <start_line>..<end_line> in it. Raises the core's CouldNotRead
        when the code can't be read."""
        ...

    def keep(self, file_ids: Collection[str]) -> None:
        """Keep the files <file_ids> for as long as the review lasts: every
        snapshot its threads had. Only ever adds: a file it was asked to keep
        before stays kept, asked for again or not. Raises the core's
        CouldNotRead when they can't be kept."""
        ...

    # ── For moving threads with their code ───────────────────────────────────
    def versions(self, files: Sequence[FileInView]) -> Dict[FileInView, Optional[str]]:
        """{each of <files>: its id now, or None when it isn't there}. A file
        that can't be read now is left out, so nothing is decided on it."""
        ...

    def hunks(self, from_id: str, to_id: str) -> Optional[List[Hunk]]:
        """The diff from one file to another, with no context lines, in order.
        None when <from_id> is gone (a snapshot lost to git gc, say). Raises
        the core's CouldNotRead when the diff can't be read."""
        ...

    def code_on_lines(self, file_id: str, start_line: int, end_line: int) -> Optional[str]:
        """The code on lines <start_line>..<end_line> of a file; None when it
        has no such lines (or there is no such file)."""
        ...

    # ── The checked-out branch ───────────────────────────────────────────────
    def on_branch(self) -> bool:
        """Whether the review's branch is checked out now. When it isn't, the
        files on disk are another branch's."""
        ...

    def checked_out_branch(self) -> Optional[str]:
        """What a review of the checkout now would be of: the checked-out
        branch, or the commit standing in for it. None when it can't be said."""
        ...

    # ── The changeset ────────────────────────────────────────────────────────
    def changeset(self, view: str) -> Changeset:
        """The review's changeset in <view> ("" for all changes). Raises the
        core's NotFound when <view> is no view (it names no commit), and
        CouldNotRead when the changeset can't be read."""
        ...

    def diff_hashes(self) -> Dict[str, str]:
        """{file: the hash of its diff in the changeset (all changes) now}, for
        every file in it. A commit doesn't change a file's diff hash; any edit
        to the file does. Raises the core's CouldNotRead when the changeset
        can't be read."""
        ...
