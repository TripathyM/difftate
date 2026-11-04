"""Changes: the base, the review's branch, and the changeset, from git.

A review is one branch against its base, like a pull request. The base is the
repository's default branch (origin/HEAD) unless --base gives another; without
an origin/HEAD, a local main or master stands in. With a detached HEAD, or on
the base branch itself, the current commit stands in for the branch.

The changeset is every change from where the branch left the base (their merge
base, as in a pull request) to the files on disk, new untracked files included.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile


class ChangesError(Exception):
    pass


def _git(cwd, *args, env=None):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    return r.stdout.strip() if r.returncode == 0 else None


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


def head(cwd):
    """The commit checked out, or None in a repository with no commit yet."""
    return _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD")


def _on_base(cwd, branch, base):
    full = _git(cwd, "rev-parse", "--symbolic-full-name", base) or ""
    if full == f"refs/heads/{branch}":
        return True
    # A remote's copy of the branch: origin/main is the base when main is checked out
    parts = full.split("/", 3)
    return full.startswith("refs/remotes/") and len(parts) == 4 and parts[3] == branch


def review_branch(cwd, base):
    """What the review is of: the checked-out branch, or the current commit on a
    detached HEAD or on the base branch itself."""
    branch = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch and not _on_base(cwd, branch, base):
        return branch
    commit = head(cwd)
    if not commit:
        raise ChangesError("Error: the repository has no commit yet")
    return commit


def review_id(branch, base):
    """A review's id: readable, and different for every branch and base."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch)[:40].strip("-.") or "review"
    digest = hashlib.sha1(f"{branch}\0{base}".encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def remote_url(cwd):
    return _git(cwd, "remote", "get-url", "origin")


def changeset(cwd, base):
    """The review's changeset: {"base", "commit" (where the branch left the base),
    "diff" (a unified diff, new untracked files included)}."""
    if base is None:
        raise ChangesError("no base: pass --base <branch>")
    commit = _git(cwd, "merge-base", base, "HEAD") or head(cwd)
    if not commit:
        raise ChangesError("the repository has no commit yet")
    # Untracked files show as new files: add them, intent only, to a copy of the index
    git_dir = _git(cwd, "rev-parse", "--absolute-git-dir")
    tmp = tempfile.mkdtemp(prefix="difftate-index-")
    try:
        index = os.path.join(tmp, "index")
        if git_dir and os.path.exists(os.path.join(git_dir, "index")):
            shutil.copy(os.path.join(git_dir, "index"), index)
        env = dict(os.environ, GIT_INDEX_FILE=index)
        top = _git(cwd, "rev-parse", "--show-toplevel") or cwd
        subprocess.run(["git", "-C", top, "add", "--intent-to-add", "--all"], capture_output=True, env=env)
        r = subprocess.run(["git", "-C", top, "diff", "--no-color", "--no-ext-diff", commit],
                           capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise ChangesError(f"git diff failed: {r.stderr.strip()}")
    return {"base": base, "commit": commit, "diff": r.stdout}
