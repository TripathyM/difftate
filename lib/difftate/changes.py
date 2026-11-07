"""Changes: the base, the review's branch, and the changeset, from git.

A review is one branch against its base, like a pull request. The base is the
repository's default branch (origin/HEAD) unless --base gives another; without
an origin/HEAD, a local main or master stands in. With a detached HEAD, or on
the base branch itself, the current commit stands in for the branch.

The changeset is every change from where the branch left the base (their merge
base, as in a pull request) to the files on disk, new untracked files included.
A view shows part of it, as the same review (a thread written in any view belongs
to the review):
  ""          all changes (the default)
  <commit>    the commits after it, and the files on disk: HEAD~2 is the last two
              commits; HEAD is the uncommitted changes
  staged      what is staged (the index against HEAD)
  unstaged    what isn't staged yet (the files on disk against the index)

The git commands are in the git adapter (adapters/outbound/git), and whether
a thread moved with its code or is outdated is decided in the core
(core/changes/model.py). This module keeps the watcher's and the old Review's
names for them until the review API and Dispatch use the core (#66, #67).
"""
from .adapters.outbound import local_store
from .adapters.outbound import git as git_adapter
from .core.changes.model import (NAMED_VIEWS, OUTDATED as _OUTDATED, FileInView, Moved, View, lines_in_view,
                                 moved_or_outdated, moved_or_outdated_by_code, same_code)
from .core.review.model import CouldNotRead, NotFound

__all__ = ["NAMED_VIEWS", "OUTDATED", "ChangesError", "Code", "ViewError", "changeset", "diff_hashes", "head",
           "need_view", "remote_url", "resolve_base", "review_branch", "review_id", "same_code", "view_name"]


class ChangesError(Exception):
    pass


class ViewError(ChangesError):
    """A view that isn't one: no such commit."""


_git = git_adapter.git
head = git_adapter.head
diff_hashes = git_adapter.diff_hashes


def need_view(cwd, view):
    """<view> as given ("" for all changes), once it is known to be a view."""
    try:
        return git_adapter.need_view(cwd, view)
    except NotFound as e:
        raise ViewError(str(e))


def view_name(view):
    """How the terminal names a view."""
    return View(view or "").name


def resolve_base(cwd, given=""):
    """The review's base: <given>, else the repository's default branch."""
    if given:
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"{given}^{{commit}}") is None:
            raise ChangesError(f"Error: the base '{given}' is not a branch or commit in this repository")
        return given
    origin = _git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin and _git(cwd, "rev-parse", "--verify", "--quiet", f"{origin}^{{commit}}"):
        return origin
    for name in ("main", "master"):
        if _git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    raise ChangesError("Error: no default branch found (no origin/HEAD, main or master). "
                       "Pass --base <branch>, or run: git remote set-head origin --auto")


def review_branch(cwd, base):
    """What the review is of: the checked-out branch, or the current commit on a
    detached HEAD or on the base branch itself."""
    branch = git_adapter.review_branch(cwd, base)
    if not branch:
        raise ChangesError("Error: the repository has no commit yet")
    return branch


def review_id(branch, base):
    """A review's id: readable, and different for every branch and base. The
    local store names the review's folder with it."""
    return local_store.review_id(branch, base)


def remote_url(cwd):
    return _git(cwd, "remote", "get-url", "origin")


def changeset(cwd, base, view=""):
    """The review's changeset in <view>: {"view", "base", "commit" (where the branch
    left the base), "diff" (a unified diff, new untracked files included)}."""
    try:
        found = git_adapter.changeset(cwd, base, view)
    except NotFound as e:
        raise ViewError(str(e))
    except CouldNotRead as e:
        raise ChangesError(str(e))
    return {"view": found.view, "base": found.base, "commit": found.commit, "diff": found.diff}


# ── Where each thread's code is now ──────────────────────────────────────────
OUTDATED = ("outdated",)


class Code:
    """Where each thread's code is now, for the review of <branch> against <base>,
    on the anchors as the old Review keeps them (dicts). The git adapter reads
    the code and the core decides (core/changes/model.py). The anchor keeps its
    view, so a thread on the old side of HEAD~1 moves with its code there, even
    where the base never had that code.
    """

    def __init__(self, cwd, base, branch):
        self.cwd = cwd
        self.base = base
        self.branch = branch
        self.reader = git_adapter.GitCodeReader(cwd, base, branch)

    def checked_out(self):
        """What a review of the checkout now would be of (review_branch), or None
        when git can't say."""
        return self.reader.checked_out_branch()

    def on_branch(self):
        """Whether the review's branch (or the commit standing in for it) is checked out."""
        return self.reader.on_branch()

    def snapshot(self, anchor, view=""):
        """The snapshot for a new anchor written in <view>, and the code on its lines
        in it: (blob, code), with None for what isn't there (no such file, or no such
        lines). Raises ChangesError when git fails."""
        try:
            found = self.reader.snapshot(anchor["file"], anchor["side"], view, anchor["startLine"], anchor["endLine"])
        except CouldNotRead as e:
            raise ChangesError(str(e))
        return found.id, found.code

    def follow(self, anchors):
        """Where the anchors ({thread id: anchor}) are now: {thread id: ("moved",
        start, end, snapshot) or OUTDATED}, for the ones that moved or became
        outdated. Nothing moves while another branch is checked out, nor a thread
        whose code can't be read: a thread only moves on a sure answer."""
        found = {}
        if not anchors or not self.on_branch():
            return found
        files = {tid: FileInView(a["file"], a["side"], a.get("view") or "") for tid, a in anchors.items()}
        now = self.reader.versions(list(dict.fromkeys(files.values())))
        for tid, a in anchors.items():
            if files[tid] not in now:
                continue  # it can't be read now
            now_id, snapshot = now[files[tid]], a.get("snapshot")
            if now_id == snapshot:
                continue
            start, end = a["startLine"], a["endLine"]
            try:
                if not snapshot:  # written before snapshots existed
                    decided = moved_or_outdated_by_code(start, end, a.get("code"), now_id,
                                                        self.reader.code_on_lines(now_id, start, end))
                else:
                    hunks = None if now_id is None else self.reader.hunks(snapshot, now_id)
                    decided = moved_or_outdated(start, end, snapshot, now_id, hunks)
            except CouldNotRead:
                continue
            if decided is _OUTDATED:
                found[tid] = OUTDATED
            elif isinstance(decided, Moved):
                found[tid] = ("moved", decided.start_line, decided.end_line, decided.snapshot_id)
        # A checkout while this ran: what it found may come from the other branch
        return found if not found or self.on_branch() else {}

    def place(self, threads, view):
        """Each thread's lines where its code is in <view>, in place: its snapshot
        diffed against the file in the view. A thread whose code isn't in the view
        (or changed in it) gets "inView": False and keeps its lines; an outdated
        thread keeps its lines, as it never sits next to code."""
        placed = [t for t in threads if t["anchor"] and not t["outdated"] and t["anchor"].get("snapshot")]
        files = [FileInView(t["anchor"]["file"], t["anchor"]["side"], view) for t in placed]
        there = self.reader.versions(list(dict.fromkeys(files))) if placed else {}
        for t, file in zip(placed, files):
            a = t["anchor"]
            if file not in there:
                continue  # it can't be read now
            there_id, snapshot = there[file], a["snapshot"]
            try:
                hunks = None if there_id in (None, snapshot) else self.reader.hunks(snapshot, there_id)
            except CouldNotRead:
                continue
            lines = lines_in_view(a["startLine"], a["endLine"], snapshot, there_id, hunks)
            if lines is None:
                t["inView"] = False
            else:
                a["startLine"], a["endLine"] = lines
