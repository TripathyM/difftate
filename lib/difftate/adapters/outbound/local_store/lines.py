"""Reading today's events.jsonl lines as the core's events.

Each line type is one event type (local.py lists the lines):
  opened → ThreadOpened      comment → CommentAdded     note → NoteWritten (final)
  status → ThreadStatusChanged   moved → ThreadMoved    outdated → ThreadOutdated
  run → RunStarted           run-ended → RunEnded       viewed → FileViewed
A "note" line is a note's final body: notes are stored only once final.
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
    return Comment(line["id"], line["author"], line["kind"], line["body"], line["time"], line["seq"])


def event_from_line(line: Dict[str, Any]) -> Event:
    """The event one line holds. Raises KeyError (or TypeError) for a line
    that holds none."""
    kind = line["type"]
    if kind == "opened":
        return ThreadOpened(line["thread"], _anchor(line.get("anchor")), line["time"])
    if kind == "comment":
        return CommentAdded(line["thread"], _comment(line))
    if kind == "note":
        return NoteWritten(line["thread"], _comment(line), final=True)
    if kind == "status":
        return ThreadStatusChanged(line["thread"], line["status"], line["time"])
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
    holds no event (cut short, say) is skipped, as local.py skips it."""
    events = []
    for raw in text.splitlines():
        try:
            events.append(event_from_line(json.loads(raw)))
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    return events
