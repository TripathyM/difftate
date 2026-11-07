"""The Changes context's driven port: reading the code.

Only the parts the Review's use cases need are here so far: a snapshot, the
diff hashes for viewed files, and whether the review's branch is checked out.
The rest (file versions and hunks, the checked-out branch's name, the
changeset for a view) comes with the use cases that need it.
"""
from __future__ import annotations

from typing import Dict, Protocol

from .model import Snapshot


class ForReadingTheCode(Protocol):
    def snapshot(self, file: str, side: str, view: str, start_line: int, end_line: int) -> Snapshot:
        """<file> on <side> ("old" or "new") of <view> ("" for all changes) as it
        is now, kept so a thread can move with its code later, and the code on
        lines <start_line>..<end_line> in it. Raises the core's CouldNotRead
        when the code can't be read."""
        ...

    def diff_hashes(self) -> Dict[str, str]:
        """{file: the hash of its diff in the changeset (all changes) now}, for
        every file in it. A commit doesn't change a file's diff hash; any edit
        to the file does. Raises the core's CouldNotRead when the changeset
        can't be read."""
        ...

    def on_branch(self) -> bool:
        """Whether the review's branch is checked out now. When it isn't, the
        files on disk are another branch's."""
        ...
