"""The prompt for one run: the threads it answers in full, a summary of the other
open threads, and the rules.

An outdated thread says so, and shows the code it was written on: that code
is no longer on its lines.

Notes are left out: they cost tokens on every run and say nothing about the code.
Each comment names its reviewer, by reviewer name when it has one.
The coding agent answers with its reply command (the reply channel's dt-reply,
ForAskingTheCodingAgent.reply_command), and nothing in the prompt names the
store. Threads are the core's (core/review/model.py, Thread).
"""
from __future__ import annotations

from typing import Collection, List, Optional, Sequence

from ..review.model import Comment, Thread
from .model import short

ANCHOR_MAX_LINES = 20
SUMMARY_MAX = 200  # chars per comment in the "other open threads" section

PROMPT = """New review comments. Everything you need is below.

{threads}

Rules:
- Reply to EVERY thread under 'Reply to these threads', with: {dt_reply} <thread> "<answer>"
  <thread> is the 8 characters after 'Thread'. Write only the answer: difftate marks it as your reply.
  For an answer with quotes or several lines, pass it on stdin: {dt_reply} <thread> <<'EOF' … EOF
- 'Other open threads' are context only, to spot related comments. Reply there only if what you do in this run also addresses it.
- Lines starting 'reviewer' are reviewers' comments, with the reviewer's name when it has one ('reviewer security-bot:'). Those marked '(new)' are the comments to answer now. Lines starting 'you:' are your earlier replies.
- Change code ONLY when the reviewer explicitly asks ('fix this', 'rename X to Y', 'add X'). Then reply with what you changed (file:line).
- Questions: answer. Suggestions, 'should we…?', nits: give your take and ask before changing anything. Unclear: ask for clarification. Never skip a thread silently.
- NEVER resolve or dismiss threads, and never edit or delete comments.
- A thread marked 'outdated' was written on code that changed since: its code block is the code then, not the file now.
- Read files as needed for context.
- Write replies in ASD-STE100 Simplified Technical English.
Summarize briefly what you handled."""


def build(open_threads: Sequence[Thread], ids: Collection[str], new_ids: Collection[str], reply_command: str) -> str:
    """The prompt for a run on the threads <ids>, among the <open_threads>.
    <new_ids> holds the ids of the comments the run is sent: no run had them.
    <reply_command> is how the coding agent answers, ready for its shell."""
    return PROMPT.format(threads=threads_part(open_threads, ids, new_ids), dt_reply=reply_command)


def location(t: Thread) -> str:
    a = t.anchor
    if a is None:
        return "general thread (not tied to a line)"
    start, end = a.start_line, a.end_line
    loc = f"{a.file}:{start}" + (f"-{end}" if end != start else "")
    return loc + (" (old side, before the change)" if a.side == "old" else "")


def _conversation(t: Thread) -> List[Comment]:
    """The thread's comments and replies, without notes."""
    return [c for c in t.comments if c.kind in ("comment", "reply")]


def _speaker(c: Comment, new_ids: Collection[str] = ()) -> str:
    """Who wrote <c>: you (the coding agent), or the reviewer, with their
    reviewer name when it has one."""
    if c.kind == "reply":
        return "you"
    reviewer = "reviewer" if c.by is None else f"reviewer {c.by}"
    return f"{reviewer} (new)" if c.id in new_ids else reviewer


OUTDATED_MARK = " — outdated: its code changed after the thread was written"


def render_full(t: Thread, new_ids: Collection[str]) -> str:
    outdated = t.outdated
    lines = [f"### Thread {t.id[:8]} — {location(t)}{OUTDATED_MARK if outdated else ''}"]
    code = ((t.anchor and t.anchor.code) or "").rstrip("\n")
    if code:
        code_lines = code.split("\n")
        if len(code_lines) > ANCHOR_MAX_LINES:
            code_lines = code_lines[:ANCHOR_MAX_LINES] + [f"… ({len(code_lines) - ANCHOR_MAX_LINES} more lines)"]
        lines += ["Code when the thread was written:" if outdated else "Code:", "```", *code_lines, "```"]
    lines += [f"{_speaker(c, new_ids)}: {c.body.strip()}" for c in _conversation(t)]
    return "\n".join(lines)


def render_summary(t: Thread) -> Optional[str]:
    comments = _conversation(t)
    if not comments:
        return None
    shown = [comments[0]] + ([comments[-1]] if len(comments) > 1 else [])
    parts = []
    for i, c in enumerate(shown):
        if i == 1 and len(comments) > 2:
            parts.append(f"  … {len(comments) - 2} more")
        parts.append(f"  {_speaker(c)}: {short(c.body, SUMMARY_MAX)}")
    return "\n".join([f"- {t.id[:8]} — {location(t)}{' (outdated)' if t.outdated else ''}", *parts])


def threads_part(threads: Sequence[Thread], ids: Collection[str], new_ids: Collection[str]) -> str:
    ids, new_ids = set(ids), set(new_ids)
    mine = [t for t in threads if t.id in ids]
    others = [s for s in (render_summary(t) for t in threads if t.id not in ids) if s]
    out = [f"## Reply to these threads ({len(mine)})", ""]
    out += ["\n\n".join(render_full(t, new_ids) for t in mine)]
    if others:
        out += ["", f"## Other open threads ({len(others)}) — context only", "", *others]
    return "\n".join(out)
