"""Changes: the base and the review's branch, from git, for the watcher.

A review is one branch against its base, like a pull request. The base is the
repository's default branch (origin/HEAD) unless --base gives another; without
an origin/HEAD, a local main or master stands in. With a detached HEAD, or on
the base branch itself, the current commit stands in for the branch.

The git commands for the code are in the git adapter (adapters/outbound/git),
and whether a thread moved with its code or is outdated is decided in the
core (core/changes/model.py). This module keeps what the watcher asks git
before it opens a review, until main.py is the composition root (#68).
"""
from .adapters.outbound import git as git_adapter
from .core.changes.model import View

__all__ = ["ChangesError", "remote_url", "resolve_base", "review_branch", "view_name"]


class ChangesError(Exception):
    pass


_git = git_adapter.git


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


def remote_url(cwd):
    """The repository's origin, for the review history; None without one."""
    return _git(cwd, "remote", "get-url", "origin")
