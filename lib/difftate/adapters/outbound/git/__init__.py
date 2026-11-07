"""The git adapter: it plugs git into the core's port for reading the code
(ForReadingTheCode).

repository.py runs git on the repository: the checked-out branch, the views
and the changeset. diff_hashes.py reads a unified diff, one hash per file.
code.py is the code reader: snapshots and the files now in git's object
database, and the hunks between them, with the caches that keep a watcher's
polls cheap.
"""
from .code import GitCodeReader
from .diff_hashes import diff_hashes
from .repository import changeset, git, head, need_view, review_branch

__all__ = ["GitCodeReader", "changeset", "diff_hashes", "git", "head", "need_view", "review_branch"]
