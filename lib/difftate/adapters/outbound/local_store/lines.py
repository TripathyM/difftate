"""Today's events.jsonl lines, read as the core's events and written from them.

Each line type is one event type (the lines the old local.py wrote, which
existing reviews hold):
  opened → ThreadOpened      comment → CommentAdded     note → NoteWritten (final)
  status → ThreadStatusChanged   moved → ThreadMoved    outdated → ThreadOutdated
  run → RunStarted           run-ended → RunEnded       viewed → FileViewed
A "note" line is a note's final body: notes are stored only once final. A
note given to the store before it is final (the core gives none: lasting)
keeps "final": false in its line, so it reads back as it was given; no such
line was ever written before the core.

A line is written with its keys in the order local.py wrote them, so the
same events give the same bytes as the old LocalStore
(tests/fixtures/todays-review). A comment or status line with a reviewer
name has "by" too, after "author" or "status"; a line with none has no "by",
as no line had before reviewer names.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ....core.review.model import (
    Anchor, Comment, CommentAdded, Event, FileViewed, NoteWritten, RunEnded, RunStarted, ThreadMoved,
    ThreadOpened, ThreadOutdated, ThreadStatusChanged,
)


def _anchor(line: Optional[Dict[str, Any]]) -> Optional[Anchor]:
    if line is None:
        return None
    # An anchor from before views has no "view": it was written in all changes
    return Anchor(line["file"], line["side"], line["startLine"], line["endLine"], line.get("code"),
                  line.get("view", ""), line.get("snapshot"), line.get("commit"))


def _comment(line: Dict[str, Any]) -> Comment:
    return Comment(line["id"], line["author"], line["kind"], line["body"], line["time"], line["seq"],
                   line.get("by"))


def event_from_line(line: Dict[str, Any]) -> Event:
    """The event one line holds. Raises KeyError (or TypeError) for a line
    that holds none."""
    kind = line["type"]
    if kind == "opened":
        return ThreadOpened(line["thread"], _anchor(line.get("anchor")), line["time"])
    if kind == "comment":
        return CommentAdded(line["thread"], _comment(line))
    if kind == "note":
        return NoteWritten(line["thread"], _comment(line), final=line.get("final", True) is not False)
    if kind == "status":
        return ThreadStatusChanged(line["thread"], line["status"], line["time"], line.get("by"))
    if kind == "moved":
        return ThreadMoved(line["thread"], line["startLine"], line["endLine"], line["snapshot"], line["time"])
    if kind == "outdated":
        return ThreadOutdated(line["thread"], line["time"])
    if kind == "run":
        return RunStarted(line["run"], tuple(line["threads"]), tuple(line["sent"]),
                          {tid: tuple(ids) for tid, ids in line["repliesBefore"].items()}, line["time"])
    if kind == "run-ended":
        return RunEnded(line["run"], line["outcome"], line["time"])
    if kind == "viewed":
        return FileViewed(line["file"], line["diffHash"], line["time"])
    raise KeyError(f"no event in a {kind!r} line")


def read_events(text: str) -> List[Event]:
    """The events in an events.jsonl file's text, oldest first. A line that
    holds no event (cut short, say) is skipped, as local.py skipped it."""
    events = []
    for raw in text.splitlines():
        try:
            events.append(event_from_line(json.loads(raw)))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return events


def _anchor_line(anchor: Optional[Anchor]) -> Optional[Dict[str, Any]]:
    if anchor is None:
        return None
    return {"file": anchor.file, "side": anchor.side, "startLine": anchor.start_line, "endLine": anchor.end_line,
            "code": anchor.code, "snapshot": anchor.snapshot_id, "view": anchor.view, "commit": anchor.commit}


def _by(by: Optional[str]) -> Dict[str, Any]:
    """The "by" key of a line with a reviewer name; none without one."""
    return {} if by is None else {"by": by}


def _comment_line(kind: str, thread_id: str, comment: Comment) -> Dict[str, Any]:
    return {"id": comment.id, "author": comment.author, **_by(comment.by), "kind": comment.kind,
            "body": comment.body, "time": comment.time, "seq": comment.seq, "type": kind, "thread": thread_id}


def line_from_event(event: Event) -> Dict[str, Any]:
    """The line that holds <event>."""
    if isinstance(event, ThreadOpened):
        return {"type": "opened", "thread": event.thread_id, "anchor": _anchor_line(event.anchor),
                "time": event.time}
    if isinstance(event, CommentAdded):
        return _comment_line("comment", event.thread_id, event.comment)
    if isinstance(event, NoteWritten):
        line = _comment_line("note", event.thread_id, event.comment)
        return line if event.final else dict(line, final=False)
    if isinstance(event, ThreadStatusChanged):
        return {"type": "status", "thread": event.thread_id, "status": event.status, **_by(event.by),
                "time": event.time}
    if isinstance(event, ThreadMoved):
        return {"type": "moved", "thread": event.thread_id, "startLine": event.start_line,
                "endLine": event.end_line, "snapshot": event.snapshot_id, "time": event.time}
    if isinstance(event, ThreadOutdated):
        return {"type": "outdated", "thread": event.thread_id, "time": event.time}
    if isinstance(event, RunStarted):
        return {"type": "run", "run": event.run_id, "threads": list(event.threads), "sent": list(event.sent),
                "repliesBefore": {tid: list(ids) for tid, ids in event.replies_before.items()},
                "time": event.time}
    if isinstance(event, RunEnded):
        return {"type": "run-ended", "run": event.run_id, "outcome": event.outcome, "time": event.time}
    if isinstance(event, FileViewed):
        return {"type": "viewed", "file": event.file, "diffHash": event.diff_hash, "time": event.time}
    raise TypeError(f"no line for {event!r}")


def lines_text(events: List[Event], added: Optional[Dict[str, Any]] = None) -> str:
    """The lines that hold <events>, as local.py wrote them, each with the
    keys in <added> after its own (the review history adds the review)."""
    return "".join(json.dumps(dict(line_from_event(e), **(added or {})), ensure_ascii=False,
                              separators=(",", ":")) + "\n" for e in events)
