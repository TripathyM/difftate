"""Fakes at the core's driven ports, for the use-case tests.

The memory store (an adapter) keeps the review. These stand in for git and
the review history.
"""
import difflib
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.core.changes.model import Changeset, Hunk, Snapshot  # noqa: E402
from difftate.core.review.model import CouldNotRead, NotFound  # noqa: E402


class FakeCode:
    """The code reader, over files in memory, on the review of "feature"
    against "main". <files> are the files on disk ({file: text}): the new side
    of every view. <base> are the files where the branch left the base: the
    old side (default: <files> themselves, the same on every side). <views>
    give the new side of a view where it isn't the files on disk ({view: {file:
    text}}, as the staged view is the index); every other view shows all
    changes. A file's id is made from its name and text, so a file that is its
    snapshot has the snapshot's id.

    <diff_hashes> are each file's diff hash in the changeset (default: made
    from each file that differs from the base). <on_branch> is whether the
    review's branch is checked out ("other" is, when it isn't).
    """

    def __init__(self, files, commit="commit-1", diff_hashes=None, on_branch=True, base=None, views=None):
        self.files = files
        self.base = files if base is None else base
        self.views = views or {}
        self.commit = commit
        self.hashes = None if diff_hashes is None else dict(diff_hashes)
        self.checked_out = on_branch
        self.reads = 0  # how many times the code was read
        self._kept = {}  # id: text, for every id given out

    def _id(self, file, text):
        if text is None:
            return None
        file_id = f"{file}@{hashlib.sha1(text.encode()).hexdigest()[:8]}"
        self._kept[file_id] = text
        return file_id

    def _text(self, file, side, view=""):
        if side == "old":
            return self.base.get(file)
        return self.views.get(view, self.files).get(file)

    def snapshot(self, file, side, view, start_line, end_line):
        self.reads += 1
        file_id = self._id(file, self._text(file, side, view))
        if file_id is None:
            return Snapshot(None, self.commit, None)
        return Snapshot(file_id, self.commit, self.code_on_lines(file_id, start_line, end_line))

    def versions(self, files):
        self.reads += 1
        return {f: self._id(f.file, self._text(f.file, f.side, f.view)) for f in files}

    def hunks(self, from_id, to_id):
        if from_id not in self._kept:
            return None
        old, new = self._kept[from_id].splitlines(), self._kept[to_id].splitlines()
        found = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if op != "equal":  # as git numbers them: a count of 0 starts at the line before
                found.append(Hunk(i1 + (i2 > i1), i2 - i1, j1 + (j2 > j1), j2 - j1))
        return found

    def code_on_lines(self, file_id, start_line, end_line):
        lines = self._kept.get(file_id, "").splitlines()
        return "\n".join(lines[start_line - 1:end_line]) if end_line <= len(lines) else None

    def on_branch(self):
        return self.checked_out

    def checked_out_branch(self):
        return "feature" if self.checked_out else "other"

    def changeset(self, view):
        if view not in ("", "staged", "unstaged", "HEAD", self.commit):
            raise NotFound(f"no view '{view}'")
        diff = "".join(f"diff --git a/{f} b/{f}\n" + "".join(difflib.unified_diff(
            (self.base.get(f) or "").splitlines(True), (self.files.get(f) or "").splitlines(True),
            f"a/{f}", f"b/{f}")) for f in self._changed())
        return Changeset(view, "main", "base-commit", diff)

    def _changed(self):
        return sorted(f for f in set(self.base) | set(self.files) if self.base.get(f) != self.files.get(f))

    def diff_hashes(self):
        self.reads += 1
        if self.hashes is not None:
            return dict(self.hashes)
        return {f: hashlib.sha1(f"{self.base.get(f)}\0{self.files.get(f)}".encode()).hexdigest()
                for f in self._changed()}


class UnreadableCode:
    """A code reader that can't read the code (git failed, say)."""

    def snapshot(self, file, side, view, start_line, end_line):
        raise CouldNotRead(f"could not read {file}")

    def versions(self, files):
        return {}  # none can be read now

    def hunks(self, from_id, to_id):
        raise CouldNotRead("could not read the diff")

    def code_on_lines(self, file_id, start_line, end_line):
        return None

    def on_branch(self):
        return True

    def checked_out_branch(self):
        return None

    def changeset(self, view):
        raise CouldNotRead("could not read the changeset")

    def diff_hashes(self):
        raise CouldNotRead("could not read the changeset")


class FakeHistory:
    """The review history: keeps every event it is asked to record."""

    def __init__(self):
        self.recorded = []

    def record(self, events):
        self.recorded.extend(events)
