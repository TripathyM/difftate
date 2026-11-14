"""The code reader on git, for the review of a branch against its base.

When a thread is written, its anchor gets a snapshot: the whole file on that
side of the view it was written in, written to git's object database (in all
changes, the file on disk for the new side, uncommitted too; the file where
the branch left the base for the old side). A file's id is its blob. Later,
the core diffs the snapshot against that file now (hunks, with `git diff
-U0` on the two blobs) and decides whether the thread moved with its code or
is outdated (core/changes/model.py).

The changeset names the versions a viewer shows: the blobs of its diff, each
one written to the object database, so a thread written on a version the
viewer showed moves with its code from there, even when the file changed
after the viewer showed it.

Nothing in git refers to a blob written that way, so git gc prunes it in time
(gc.pruneExpire, two weeks by default). The snapshots the core keeps stay
reachable from a ref of difftate's own, refs/difftate/<review id>: a tree
whose entries are the snapshot blobs, each named by its id. It only grows,
so every snapshot of the review stays for its review history; only a review
that is gone loses its ref (forget_kept_snapshots). A tree, not a commit, so
there is nothing to sign and `git log --all` doesn't show it. A plain `git
push` sends only refs/heads and refs/tags, never this ref.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import replace
from typing import Collection, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from ....core.changes.model import Changeset, FileInView, Hunk, Snapshot, Versions
from ....core.review.model import CouldNotRead
from . import repository
from .diff_hashes import blob_ids, diff_hashes

BLOB_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")  # a full object id (SHA-1 or SHA-256)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)
SNAPSHOT_REFS = "refs/difftate/"  # + a review's id: the ref that keeps its snapshots


def forget_kept_snapshots(cwd: str, reviews: Iterable[str]) -> None:
    """Drop the ref of every review that isn't one of <reviews> (their ids):
    the snapshots of a review that is gone can go. A ref git can't drop now
    is dropped next time."""
    names = repository.git(cwd, "for-each-ref", "--format=%(refname)", SNAPSHOT_REFS)
    still = {SNAPSHOT_REFS + r for r in reviews}
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
        self.ref = SNAPSHOT_REFS + review_id
        self._kept: Optional[Tuple[FrozenSet[str], str]] = None  # what it last kept, and the ref's tree then
        self._hashed: Dict[str, Tuple[tuple, str]] = {}  # path: (its stat, its blob)
        self._diffs: Dict[Tuple[str, str], Tuple[Hunk, ...]] = {}  # (blob, blob): hunks
        self._stored: Set[str] = set()  # blobs known to be in git's object database

    def _run(self, *args: str, stdin: Optional[str] = None) -> Tuple[int, str]:
        # Files in any encoding: only the line structure matters here
        r = subprocess.run(["git", "-C", self.top, *args], capture_output=True, text=True, errors="replace",
                           input=stdin)
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
        tree = self._ref_now()
        # Every poll asks: git writes only when there is a snapshot the ref may not hold
        if self._kept is not None and wanted <= self._kept[0] and tree == self._kept[1]:
            return
        kept = self._added(tree, wanted)
        if kept is None:
            raise CouldNotRead("could not keep the snapshots")
        self._kept = kept

    def _ref_now(self) -> str:
        """The tree the review's ref names now; "" when there is no ref."""
        return self._run("rev-parse", "--verify", "--quiet", self.ref)[1].strip()

    def _added(self, tree: str, file_ids: FrozenSet[str]) -> Optional[Tuple[FrozenSet[str], str]]:
        """Point the review's ref at a tree of the blobs in <tree> (the ref's
        now, "" for none) and <file_ids>: those blobs and the new tree ("" when
        there are none, and no ref), or None when git fails. A snapshot
        already lost to git gc is left out: a tree may not name a missing blob."""
        held = set()
        if tree:
            code, out = self._run("ls-tree", tree)  # <mode> <type> <id>\t<name>, a line each
            if code != 0:
                return None
            held = {row.split()[2] for row in out.splitlines()}
        new = sorted(file_ids - held)
        code, out = self._run("cat-file", "--batch-check=%(objectname) %(objecttype)",
                              stdin="".join(f"{i}\n" for i in new))
        if code != 0:
            return None
        blobs = held | {row.split()[0] for row in out.splitlines() if row.endswith(" blob")}
        if blobs == held:
            return frozenset(file_ids | held), tree
        code, made = self._run("mktree", stdin="".join(f"100644 blob {b}\t{b}\n" for b in sorted(blobs)))
        # Only over the tree read above: another writer's tree is read and added to next time
        if code != 0 or self._run("update-ref", self.ref, made.strip(), tree)[0] != 0:
            return None
        return frozenset(file_ids | blobs), made.strip()

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
        # An id may come from a viewer: anything but a blob id is no file, never an option to git
        if not (BLOB_ID.fullmatch(from_id) and BLOB_ID.fullmatch(to_id)):
            return None
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
        if not BLOB_ID.fullmatch(file_id):
            return None  # an id a viewer sent that is no blob id
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
        c = repository.changeset(self.cwd, self.base, view)
        return replace(c, versions=self._stored_versions(blob_ids(c.diff), on_disk=c.view != "staged"))

    def _stored_versions(self, blobs: Dict[str, Tuple[Optional[str], Optional[str]]],
                  on_disk: bool) -> Dict[str, Versions]:
        """The versions the diff names (<blobs>), each one in git's object
        database, so a thread written on it can be read later. git diff names
        a file on disk (the new side, <on_disk>) by the blob it would be, but
        doesn't write it: it is written here. A version that can't be (the
        file changed since the diff, or git failed) is None."""
        named = {b for pair in blobs.values() for b in pair if b and b not in self._stored}
        if named:
            code, out = self._run("cat-file", "--batch-check=%(objectname) %(objecttype)",
                                  stdin="".join(f"{b}\n" for b in sorted(named)))
            if code == 0:
                self._stored |= {row.split()[0] for row in out.splitlines() if row.endswith(" blob")}
        unwritten = sorted(f for f, (_, new) in blobs.items() if on_disk and new and new not in self._stored)
        if unwritten:
            code, out = self._run("hash-object", "-w", "--stdin-paths", stdin="".join(f"{f}\n" for f in unwritten))
            # One file git can't write (removed since the diff, say) fails them all: then one by one
            written = out.split() if code == 0 else [self._run("hash-object", "-w", "--", f)[1].strip()
                                                       for f in unwritten]
            # The blob the file on disk is now: the diff's when it didn't change since
            self._stored |= {w for f, w in zip(unwritten, written) if w == blobs[f][1]}
        return {f: Versions(*(b if b in self._stored else None for b in pair)) for f, pair in blobs.items()}

    def diff_hashes(self) -> Dict[str, str]:
        return diff_hashes(repository.changeset(self.cwd, self.base).diff)
