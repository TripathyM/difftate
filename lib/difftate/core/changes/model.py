"""The Changes model: a snapshot of a file, and whether two pieces of code are
the same.

The code reader (ports.py) hands back plain data such as a Snapshot, and
makes no decision. same_code is how the core tells whether a thread's code
changed: the Review uses it when a thread is opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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


def same_code(a: str, b: str) -> bool:
    """The same lines, whatever the line endings."""
    def lines(s: str) -> list:
        return [line.rstrip("\r") for line in s.rstrip("\r\n").split("\n")]
    return lines(a) == lines(b)
