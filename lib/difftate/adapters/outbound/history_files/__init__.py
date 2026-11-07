"""The review history files: one JSON-lines file per month in
~/.difftate/history/. They plug into the core's port for recording review
history (files.py)."""
from .files import HistoryFiles, history_folder

__all__ = ["HistoryFiles", "history_folder"]
