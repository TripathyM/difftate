"""What every store shares, whatever keeps the review.

A store keeps threads in difftate's own thread format (the published language,
see api.py), and applies no rules: the Review (review.py) checks who may do what
before it calls the store.

The store port:
  review()                              start or reuse the review: {"id"}
  threads(status=None)                  the review's threads, oldest first
  open_thread(anchor, body)             a thread with the reviewer's first comment
  add_comment(thread_id, kind, body)    a comment, reply or note at the end of a thread
  edit_note(note_id, kind, body, final=False)
                                        change a note's kind and body; final when
                                        the note won't change again (a store may
                                        keep only final notes: see local.py)
  set_status(thread_id, status)         open, resolved or dismissed
  move_thread(thread_id, start, end, snapshot)
                                        the thread's code moved to lines start..end
                                        (the file now is <snapshot>)
  mark_outdated(thread_id)              the thread's code changed: it stays outdated
                                        (diffity keeps neither: its threads never
                                        move and are never outdated)
  record_run(run)                       a run starts: {"id", "threads", "sent" (the ids
                                        of the comments it was sent), "repliesBefore"
                                        ({thread id: ids of its replies then})}
  record_run_end(run_id, outcome)       the run ended: done, failed, stopped or interrupted
  runs()                                the runs, oldest first, each with "outcome"
                                        (None while it runs); None from a store that
                                        can't keep runs (diffity)
  viewed()                              the files the reviewer marked viewed: {file:
                                        the hash of its diff when marked}
  mark_viewed(file, diff_hash)          the reviewer viewed <file> when its diff had
                                        that hash, or unmarked it (<diff_hash> None)

A thread:
  {"id", "anchor": {"file", "side", "startLine", "endLine", "code", "commit",
   "snapshot"} or None for a general thread, "outdated", "status", "comments": [{"id", "author", "kind",
   "body", "time"}]}
The Review adds "state" (thread state) before the API returns it.
"""

import datetime

NOTE_KINDS = ("queued", "progress")
# Who writes each kind of comment
AUTHOR_OF = {"comment": "reviewer", "reply": "agent", "queued": "difftate", "progress": "difftate"}
KINDS = tuple(AUTHOR_OF)
THREAD_STATUSES = ("open", "resolved", "dismissed")
# How a run ended. Interrupted: the watcher was killed during it, and the next one ended it
RUN_OUTCOMES = ("done", "failed", "stopped", "interrupted")  # what record_run_end takes
SIDES = ("old", "new")


def now():
    """The time a comment is written, as stores record it."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StoreError(Exception):
    """A request the store refused (status 4xx) or couldn't serve (502)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def need_text(value, name="body"):
    if not isinstance(value, str) or not value.strip():
        raise StoreError(400, f"need {name}")
    return value


def need_kind(kind, allowed=KINDS):
    if kind not in allowed:
        raise StoreError(400, f"kind must be one of {', '.join(allowed)}")
    return kind


def need_status(status):
    if status not in THREAD_STATUSES:
        raise StoreError(400, f"status must be one of {', '.join(THREAD_STATUSES)}")
    return status


def need_anchor(anchor):
    """An anchor as a store takes it: file, side, startLine, endLine, and the code
    (optional). None is a general thread."""
    if anchor is None:
        return None
    lines = [anchor.get(k) for k in ("startLine", "endLine")] if isinstance(anchor, dict) else []
    if not isinstance(anchor, dict) or not isinstance(anchor.get("file"), str) or not anchor["file"] \
            or anchor.get("side") not in SIDES \
            or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in lines) \
            or lines[0] > lines[1]:
        raise StoreError(400, "anchor needs file, side (old|new), startLine and endLine (1 ≤ start ≤ end)")
    code = anchor.get("code")
    if code is not None and not isinstance(code, str):
        raise StoreError(400, "anchor code must be text")
    return {"file": anchor["file"], "side": anchor["side"], "startLine": lines[0], "endLine": lines[1],
            "code": code}
