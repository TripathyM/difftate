"""A review's state as text for a coding agent: its commit messages and its
threads in full. A run's prompt (core/dispatch/prompt.py) and an export
(use_cases/export_review.py) show the review the same way, and each keeps
only its own rules and sections on top.

The commit messages record the decisions behind the code: an agent session
starts fresh (ADR 0005, 0006), so they are how it knows why code it didn't
write is as it is. They are every commit from the base to the branch,
whatever the view; no section when there are none.

A thread is shown in full: a link in the middle of a long comment is not lost.
An outdated thread says so, and shows the code it was written on: that code
is no longer on its lines. Notes are left out: they cost tokens every time and
say nothing about the code. Each comment names its reviewer, by reviewer name
when it has one. Threads are the core's (model.py, Thread).
"""
from __future__ import annotations

from typing import Collection, List, Optional, Sequence

from .model import Comment, Thread

ANCHOR_MAX_LINES = 20
OUTDATED_MARK = " — outdated: its code changed after the thread was written"


def commits_part(messages: Sequence[str]) -> str:
    """The review's commit messages, each under a heading, and a blank line
    after them; "" when there are none."""
    if not messages:
        return ""
    out = [f"## The decisions behind the code: the review's commit messages ({len(messages)}), oldest first", "",
           "Each commit from the base to the branch. Read them to know why the code is as it is.", ""]
    for n, message in enumerate(messages, 1):
        out += [f"### Commit {n}", message, ""]
    return "\n".join(out) + "\n"


def location(t: Thread) -> str:
    a = t.anchor
    if a is None:
        return "general thread (not tied to a line)"
    start, end = a.start_line, a.end_line
    loc = f"{a.file}:{start}" + (f"-{end}" if end != start else "")
    return loc + (" (old side, before the change)" if a.side == "old" else "")


def conversation(t: Thread) -> List[Comment]:
    """The thread's comments and replies, without notes."""
    return [c for c in t.comments if c.kind in ("comment", "reply")]


def speaker(c: Comment, new_ids: Collection[str] = (), agent: str = "you") -> str:
    """Who wrote <c>: the coding agent (<agent>), or the reviewer, with their
    reviewer name when it has one."""
    if c.kind == "reply":
        return agent
    reviewer = "reviewer" if c.by is None else f"reviewer {c.by}"
    return f"{reviewer} (new)" if c.id in new_ids else reviewer


def render_full(t: Thread, new_ids: Collection[str], with_status: bool = False, state: Optional[str] = None,
                agent: str = "you") -> str:
    """<t> with its code and every comment and reply. <with_status> adds its
    thread status to the heading, and <state> its thread state by name (held,
    waiting, replied…), as an open thread has one. The coding agent's replies
    are <agent>'s lines."""
    outdated = t.outdated
    shown_state = f" ({state})" if state else ""
    lines = [f"### Thread {t.id[:8]} — {location(t)}{f' — {t.status}' if with_status else ''}{shown_state}"
             f"{OUTDATED_MARK if outdated else ''}"]
    code = ((t.anchor and t.anchor.code) or "").rstrip("\n")
    if code:
        code_lines = code.split("\n")
        if len(code_lines) > ANCHOR_MAX_LINES:
            code_lines = code_lines[:ANCHOR_MAX_LINES] + [f"… ({len(code_lines) - ANCHOR_MAX_LINES} more lines)"]
        lines += ["Code when the thread was written:" if outdated else "Code:", "```", *code_lines, "```"]
    lines += [f"{speaker(c, new_ids, agent)}: {c.body.strip()}" for c in conversation(t)]
    return "\n".join(lines)
