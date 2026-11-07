"""git on the repository: its difftate folder, the base, the checked-out
branch, the views and the changeset.

The changeset is every change from where the branch left the base (their merge
base, as in a pull request) to the files on disk, new untracked files included.
A view shows part of it (core/changes/model.py, View).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple

from ....core.changes.model import NAMED_VIEWS, Changeset
from ....core.review.model import CouldNotRead, NotFound


def git(cwd: str, *args: str, env: Optional[dict] = None) -> Optional[str]:
    """git's output, stripped; None when it fails."""
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    return r.stdout.strip() if r.returncode == 0 else None


def difftate_folder(cwd: str) -> Optional[Tuple[str, str]]:
    """The repository's difftate folder, inside its git folder (shared by
    worktrees, never committed), and the repository's top folder. None when
    <cwd> is not in a git repository."""
    common = git(cwd, "rev-parse", "--git-common-dir")
    if common is None:
        return None
    top = git(cwd, "rev-parse", "--show-toplevel")
    return (os.path.realpath(os.path.join(cwd, common, "difftate")), os.path.realpath(top or cwd))


def base(cwd: str, given: str = "") -> str:
    """The review's base: <given>, else the repository's default branch
    (origin/HEAD; without it, a local main or master). Raises the core's
    NotFound when there is none."""
    if given:
        if git(cwd, "rev-parse", "--verify", "--quiet", f"{given}^{{commit}}") is None:
            raise NotFound(f"the base '{given}' is not a branch or commit in this repository")
        return given
    origin = git(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if origin and git(cwd, "rev-parse", "--verify", "--quiet", f"{origin}^{{commit}}"):
        return origin
    for name in ("main", "master"):
        if git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    raise NotFound("no default branch found (no origin/HEAD, main or master). "
                   "Pass --base <branch>, or run: git remote set-head origin --auto")


def remote_url(cwd: str) -> Optional[str]:
    """The repository's origin, for the review history; None without one."""
    return git(cwd, "remote", "get-url", "origin")


def need_view(cwd: str, view: object) -> str:
    """<view> as given ("" for all changes), once it is known to be a view.
    Raises the core's NotFound when it isn't one."""
    if view is None or view == "":
        return ""
    if not isinstance(view, str):
        raise NotFound("a view is text: \"\", a commit, staged or unstaged")
    if view in NAMED_VIEWS:
        return view
    if view.startswith("-") or git(cwd, "rev-parse", "--verify", "--quiet", f"{view}^{{commit}}") is None:
        raise NotFound(f"no view '{view}': give a commit (HEAD~2, HEAD), staged or unstaged, or nothing for all changes")
    return view


def head(cwd: str) -> Optional[str]:
    """The commit checked out, or None in a repository with no commit yet."""
    return git(cwd, "rev-parse", "--verify", "--quiet", "HEAD")


def _on_base(cwd: str, branch: str, base: str) -> bool:
    full = git(cwd, "rev-parse", "--symbolic-full-name", base) or ""
    if full == f"refs/heads/{branch}":
        return True
    # A remote's copy of the branch: origin/main is the base when main is checked out
    parts = full.split("/", 3)
    return full.startswith("refs/remotes/") and len(parts) == 4 and parts[3] == branch


def review_branch(cwd: str, base: str) -> Optional[str]:
    """What a review of the checkout is of: the checked-out branch, or the
    current commit on a detached HEAD or on the base branch itself. None in a
    repository with no commit yet."""
    branch = git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch and not _on_base(cwd, branch, base):
        return branch
    return head(cwd)


def changeset(cwd: str, base: str, view: str = "") -> Changeset:
    """The review's changeset in <view>. Raises the core's NotFound when <view>
    is no view, and CouldNotRead when git can't give it."""
    view = need_view(cwd, view)
    commit = git(cwd, "merge-base", base, "HEAD") or head(cwd)
    if not commit:
        raise CouldNotRead("the repository has no commit yet")
    if view == "staged":
        r = subprocess.run(["git", "-C", cwd, "diff", "--no-color", "--no-ext-diff", "--cached", "HEAD", "--"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise CouldNotRead(f"git diff failed: {r.stderr.strip()}")
        return Changeset(view, base, commit, r.stdout)
    against = [] if view == "unstaged" else [view or commit]
    # Untracked files show as new files: add them, intent only, to a copy of the index
    git_dir = git(cwd, "rev-parse", "--absolute-git-dir")
    tmp = tempfile.mkdtemp(prefix="difftate-index-")
    try:
        index = os.path.join(tmp, "index")
        if git_dir and os.path.exists(os.path.join(git_dir, "index")):
            shutil.copy(os.path.join(git_dir, "index"), index)
        env = dict(os.environ, GIT_INDEX_FILE=index)
        top = git(cwd, "rev-parse", "--show-toplevel") or cwd
        subprocess.run(["git", "-C", top, "add", "--intent-to-add", "--all"], capture_output=True, env=env)
        r = subprocess.run(["git", "-C", top, "diff", "--no-color", "--no-ext-diff", *against, "--"],
                           capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise CouldNotRead(f"git diff failed: {r.stderr.strip()}")
    return Changeset(view, base, commit, r.stdout)
