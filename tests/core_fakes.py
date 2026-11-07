"""Fakes at the core's driven ports, for the use-case tests.

The memory store (an adapter) keeps the review. These stand in for git and
the review history.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.core.changes.model import Snapshot  # noqa: E402
from difftate.core.review.model import CouldNotRead  # noqa: E402


class FakeCode:
    """The code reader, over files in memory: {file: text}, the same on every
    side and in every view. <diff_hashes> is each file's diff hash in the
    changeset; <on_branch> whether the review's branch is checked out."""

    def __init__(self, files, commit="commit-1", diff_hashes=None, on_branch=True):
        self.files = files
        self.commit = commit
        self.hashes = dict(diff_hashes or {})
        self.checked_out = on_branch
        self.reads = 0  # how many times the code was read

    def snapshot(self, file, side, view, start_line, end_line):
        self.reads += 1
        text = self.files.get(file)
        if text is None:
            return Snapshot(None, self.commit, None)
        lines = text.splitlines()
        code = "\n".join(lines[start_line - 1:end_line]) if end_line <= len(lines) else None
        return Snapshot(f"{file}@{self.commit}", self.commit, code)

    def diff_hashes(self):
        self.reads += 1
        return dict(self.hashes)

    def on_branch(self):
        return self.checked_out


class UnreadableCode:
    """A code reader that can't read the code (git failed, say)."""

    def snapshot(self, file, side, view, start_line, end_line):
        raise CouldNotRead(f"could not read {file}")

    def diff_hashes(self):
        raise CouldNotRead("could not read the changeset")

    def on_branch(self):
        return True


class FakeHistory:
    """The review history: keeps every event it is asked to record."""

    def __init__(self):
        self.recorded = []

    def record(self, events):
        self.recorded.extend(events)
