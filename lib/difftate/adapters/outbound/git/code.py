"""The code reader on git, for the review of a branch against its base.

When a thread is written, its anchor gets a snapshot: the whole file on that
side of the view it was written in, written to git's object database (in all
changes, the file on disk for the new side, uncommitted too; the file where
the branch left the base for the old side). A file's id is its blob. Later,
the core diffs the snapshot against that file now (hunks, with `git diff
-U0` on the two blobs) and decides whether the thread moved with its code or
is outdated (core/changes/model.py).

Nothing in git refers to a blob written that way, so git gc prunes it in time
(gc.pruneExpire, two weeks by default). The snapshots the core keeps stay
reachable from a ref of difftate's own, refs/difftate/<review id>: a tree
whose entries are the snapshot blobs, each named by its id. A tree, not a
commit, so there is nothing to sign and `git log --all` doesn't show it. A
plain `git push` sends only refs/heads and refs/tags, never this ref.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Collection, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from ....core.changes.model import Changeset, FileInView, Hunk, Snapshot
from ....core.review.model import CouldNotRead
from . import repository
from .diff_hashes import diff_hashes

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
KEPT = "refs/difftate/"  # + the review's id: the review's snapshots


def forget_kept_snapshots(cwd: str, reviews: Iterable[str]) -> None:
    """Drop the ref of every review that isn't one of <reviews> (their ids):
    the snapshots of a review that is gone can go."""
    names = repository.git(cwd, "for-each-ref", "--format=%(refname)", KEPT)
    still = {KEPT + r for r in reviews}
    for ref in (names or "").split():
        if ref not in still:
            repository.git(cwd, "update-ref", "-d", ref)


class GitCodeReader:
    """Reads the code of the review <review_id> of <branch> against <base>,
    in the repository at <cwd>. It plugs into ForReadingTheCode."""

    def __init__(self, cwd: str, base: str, branch: str, review_id: str) -> None:
        self.cwd = cwd
        self.base = base
        self.branch = branch
        self.top = repository.git(cwd, "rev-parse", "--show-toplevel") or cwd
        self.ref = KEPT + review_id
        self._kept: Optional[FrozenSet[str]] = None  # what this reader last wrote to the ref
        self._hashed: Dict[str, Tuple[tuple, str]] = {}  # path: (its stat, its blob)
        self._diffs: Dict[Tuple[str, str], Tuple[Hunk, ...]] = {}  # (blob, blob): hunks

    def _run(self, *args: str, given: Optional[str] = None) -> Tuple[int, str]:
        # Files in any encoding: only the line structure matters here
        r = subprocess.run(["git", "-C", self.top, *args], capture_output=True, text=True, errors="replace",
                           input=given)
        return r.returncode, r.stdout

    # ── Where each version of a file is ──────────────────────────────────────
    def _blob_on_disk(self, file: str) -> Optional[str]:
        """The file on disk, written to git's object database: its blob, or None
        when there is no such file. Raises CouldNotRead when git fails."""
        path = os.path.join(self.top, file)
        if not os.path.realpath(path).startswith(os.path.realpath(self.top) + os.sep):
            return None  # not a file of this repository
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        except OSError as e:
            raise CouldNotRead(str(e))
        key = (st.st_ino, st.st_size, st.st_mtime_ns)
        if self._hashed.get(path, (None,))[0] == key:
            return self._hashed[path][1]
        code, out = self._run("hash-object", "-w", "--", path)
        if code != 0:
            if not os.path.exists(path):
                return None
            raise CouldNotRead(f"could not read {file}")
        self._hashed[path] = (key, out.strip())
        return out.strip()

    def _branch_left_base(self) -> str:
        code, out = self._run("merge-base", self.base, "HEAD")
        if code != 0:
            raise CouldNotRead("no merge base")
        return out.strip()

    def _blob_at(self, commit: str, file: str) -> Optional[str]:
        """The file's blob in <commit> ("" for the index)."""
        code, out = self._run("rev-parse", "--verify", "--quiet", f"{commit}:{file}")
        return out.strip() if code == 0 else None

    def _in_view(self, file: str, side: str, view: str, left: Optional[str] = None) -> Optional[str]:
        """The file's blob on <side> of <view> (None when it isn't there): all
        changes compare where the branch left the base (<left>, found when not
        given) with the files on disk; a commit, that commit with them; staged,
        HEAD with the index; unstaged, the index with the files on disk."""
        if side == "new":
            return self._blob_at("", file) if view == "staged" else self._blob_on_disk(file)
        if not view:
            return self._blob_at(left or self._branch_left_base(), file)
        return self._blob_at({"staged": "HEAD", "unstaged": ""}.get(view, view), file)

    # ── The port ─────────────────────────────────────────────────────────────
    def snapshot(self, file: str, side: str, view: str, start_line: int, end_line: int) -> Snapshot:
        blob = self._in_view(file, side, view)
        commit = repository.head(self.cwd) or ""
        if blob is None:
            return Snapshot(None, commit, None)
        return Snapshot(blob, commit, self.code_on_lines(blob, start_line, end_line))

    def keep(self, file_ids: Collection[str]) -> None:
        wanted = frozenset(file_ids)
        if wanted == self._kept:
            return  # every poll asks: git runs only when the snapshots change
        code, out = self._run("cat-file", "--batch-check=%(objectname) %(objecttype)",
                              given="".join(f"{i}\n" for i in sorted(wanted)))
        if code != 0:
            raise CouldNotRead("could not keep the snapshots")
        # A snapshot already lost to git gc is left out: a tree may not name a missing blob
        blobs = [row.split()[0] for row in out.splitlines() if row.endswith(" blob")]
        if not blobs:
            code, _ = self._run("update-ref", "-d", self.ref)
        else:
            code, tree = self._run("mktree", given="".join(f"100644 blob {b}\t{b}\n" for b in blobs))
            if code == 0:
                code, _ = self._run("update-ref", self.ref, tree.strip())
        if code != 0:
            raise CouldNotRead("could not keep the snapshots")
        self._kept = wanted

    def versions(self, files: Sequence[FileInView]) -> Dict[FileInView, Optional[str]]:
        # Where the branch left the base, once for every file that needs it
        left = None
        if any(f.side == "old" and not f.view for f in files):
            try:
                left = self._branch_left_base()
            except CouldNotRead:
                pass
        found: Dict[FileInView, Optional[str]] = {}
        for f in files:
            if f.side == "old" and not f.view and left is None:
                continue
            try:
                found[f] = self._in_view(f.file, f.side, f.view, left)
            except CouldNotRead:
                continue
        return found

    def hunks(self, from_id: str, to_id: str) -> Optional[List[Hunk]]:
        if (from_id, to_id) not in self._diffs:
            code, out = self._run("diff", "--no-color", "--no-ext-diff", "-U0", from_id, to_id)
            if code != 0:
                if self._run("cat-file", "-e", from_id)[0] != 0:
                    return None  # the snapshot is gone (git gc): nothing to diff from
                raise CouldNotRead("git diff failed")
            self._diffs[(from_id, to_id)] = tuple(
                Hunk(int(m[1]), 1 if m[2] is None else int(m[2]), int(m[3]), 1 if m[4] is None else int(m[4]))
                for m in HUNK.finditer(out))
        return list(self._diffs[(from_id, to_id)])

    def code_on_lines(self, file_id: str, start_line: int, end_line: int) -> Optional[str]:
        code, out = self._run("cat-file", "blob", file_id)
        if code != 0:
            return None
        lines = out.split("\n")
        if out.endswith("\n"):
            lines.pop()
        return "\n".join(lines[start_line - 1:end_line]) if end_line <= len(lines) else None

    def on_branch(self) -> bool:
        return self.checked_out_branch() == self.branch

    def checked_out_branch(self) -> Optional[str]:
        return repository.review_branch(self.cwd, self.base)

    def changeset(self, view: str) -> Changeset:
        return repository.changeset(self.cwd, self.base, view)

    def diff_hashes(self) -> Dict[str, str]:
        return diff_hashes(repository.changeset(self.cwd, self.base).diff)
