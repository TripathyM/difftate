"""The git adapter: it plugs git into the core's port for reading the code
(ForReadingTheCode).

repository.py runs git on the repository: its difftate folder, the base, the
checked-out branch, the views and the changeset. diff_hashes.py reads a
unified diff, one hash per file. code.py is the code reader: snapshots and the files now in git's object
database, and the hunks between them, with the caches that keep a watcher's
polls cheap. It keeps a review's snapshots reachable from refs/difftate/<review
id>, so git gc can't prune them.
"""
from .code import GitCodeReader, forget_kept_snapshots
from .diff_hashes import diff_hashes
from .repository import base, changeset, difftate_folder, git, head, need_view, remote_url, review_branch, user_name

__all__ = ["GitCodeReader", "base", "changeset", "diff_hashes", "difftate_folder", "forget_kept_snapshots", "git",
           "head", "need_view", "remote_url", "review_branch", "user_name"]
