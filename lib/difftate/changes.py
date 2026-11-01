"""Changes: the working tree's state, and which files changed between two states.

A snapshot is a git tree of the whole working tree (tracked and untracked files,
less the ignored ones), written through a temporary copy of the index so the
real index and the reviewer's staging are never touched. Comparing two
snapshots gives the files that changed between them, whoever changed them.
"""
import os
import shutil
import subprocess
import tempfile


def _git(cwd, *args, env=None):
    r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    return r.stdout if r.returncode == 0 else None


def snapshot(cwd):
    """The working tree's state now (a tree id), or None when git can't tell."""
    index = _git(cwd, "rev-parse", "--git-path", "index")
    if index is None:
        return None
    index = os.path.join(cwd, index.strip())  # relative to <cwd> unless absolute
    with tempfile.TemporaryDirectory(prefix="difftate-") as tmp:
        temp_index = os.path.join(tmp, "index")
        # Start from the real index, so git only rehashes files whose stat changed
        try:
            shutil.copyfile(index, temp_index)
        except OSError:
            pass  # no index yet: git starts an empty one
        env = dict(os.environ, GIT_INDEX_FILE=temp_index)
        if _git(cwd, "add", "-A", env=env) is None:
            return None
        tree = _git(cwd, "write-tree", env=env)
    return tree.strip() if tree else None


def changed_files(cwd, before, after):
    """The files that differ between two snapshots, sorted ([] when either is unknown)."""
    if not before or not after or before == after:
        return []
    out = _git(cwd, "diff-tree", "-r", "--name-only", "-z", "--no-renames", before, after)
    return sorted(p for p in (out or "").split("\0") if p)
