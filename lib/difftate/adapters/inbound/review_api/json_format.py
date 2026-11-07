"""difftate's thread format, the review API's published language: the core's
types written as JSON, and the JSON a viewer sends read back into them.

The checks here are about the JSON itself (a missing key, a body that is
blank, an anchor with no file): a request that fails one gets 400 before the
core is asked. Who may do what is the core's to say.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ....core.changes.model import Changeset
from ....core.review.model import AUTHOR_OF, NOTE_KINDS, Anchor, Comment, ListedThread

KINDS = tuple(AUTHOR_OF)  # comment, reply, queued, progress
THREAD_STATUSES = ("open", "resolved", "dismissed")
SIDES = ("old", "new")
ANCHOR_NEEDS = "anchor needs file, side (old|new), startLine and endLine (1 ≤ start ≤ end)"


class BadRequest(Exception):
    """JSON the review API can't take (400)."""


# ── What a viewer sends ──────────────────────────────────────────────────────
def fields(payload: Any) -> Dict[str, Any]:
    """The request's JSON object ({} for none)."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise BadRequest("need a JSON object")
    return payload


def need(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict) or key not in payload:
        raise BadRequest(f"missing {key}")
    return payload[key]


def need_text(value: Any, name: str = "body") -> str:
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"need {name}")
    return value


def need_kind(kind: Any, allowed: tuple = KINDS) -> str:
    if kind not in allowed:
        raise BadRequest(f"kind must be one of {', '.join(allowed)}")
    return kind


def need_status(status: Any) -> str:
    if status not in THREAD_STATUSES:
        raise BadRequest(f"status must be one of {', '.join(THREAD_STATUSES)}")
    return status


def need_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise BadRequest(f"{name} must be true or false")
    return value


def anchor_from_json(anchor: Any, view: str) -> Optional[Anchor]:
    """The anchor a viewer sent, written in <view>: file, side, startLine,
    endLine and the code (optional). None is a general thread."""
    if anchor is None:
        return None
    if not isinstance(anchor, dict) or not isinstance(anchor.get("file"), str) or not anchor["file"] \
            or anchor.get("side") not in SIDES:
        raise BadRequest(ANCHOR_NEEDS)
    start, end = _line_number(anchor.get("startLine")), _line_number(anchor.get("endLine"))
    if start > end:
        raise BadRequest(ANCHOR_NEEDS)
    code = anchor.get("code")
    if code is not None and not isinstance(code, str):
        raise BadRequest("anchor code must be text")
    return Anchor(anchor["file"], anchor["side"], start, end, code, view=view)


def _line_number(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BadRequest(ANCHOR_NEEDS)
    return value


# ── What the review API answers ──────────────────────────────────────────────
def anchor_json(anchor: Anchor) -> Dict[str, Any]:
    return {"file": anchor.file, "side": anchor.side, "startLine": anchor.start_line,
            "endLine": anchor.end_line, "code": anchor.code, "snapshot": anchor.snapshot_id,
            "view": anchor.view, "commit": anchor.commit}


def comment_json(comment: Comment) -> Dict[str, Any]:
    return {"id": comment.id, "author": comment.author, "kind": comment.kind, "body": comment.body,
            "time": comment.time}


def thread_json(listed: ListedThread) -> Dict[str, Any]:
    """A thread with its thread state; "inView": false when the view doesn't
    show its code."""
    t = listed.thread
    found = {"id": t.id, "anchor": anchor_json(t.anchor) if t.anchor else None, "outdated": t.outdated,
             "status": t.status, "comments": [comment_json(c) for c in t.comments], "state": listed.state}
    if not listed.in_view:
        found["inView"] = False
    return found


def changeset_json(changeset: Changeset) -> Dict[str, Any]:
    return {"view": changeset.view, "base": changeset.base, "commit": changeset.commit, "diff": changeset.diff}
