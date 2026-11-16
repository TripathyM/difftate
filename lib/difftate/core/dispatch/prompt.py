"""The prompt for one run: the review's commit messages, the threads it answers,
every other thread of the review, and the rules.

The commit messages record the decisions behind the code: a run starts a
fresh agent session (ADR 0005), so they are how it knows why code it didn't
write is as it is. They are every commit from the base to the branch,
whatever the view; no section when there are none.

The other threads are context only, each with its thread status: a question
in one informs the answer in another, and a resolved or dismissed one holds a
fix, a preference or a rejected suggestion the run must not undo or make again.
They are shown in full, as the threads the run answers are: a link in the middle
of a long comment is not lost.

An outdated thread says so, and shows the code it was written on: that code
is no longer on its lines.

Notes are left out: they cost tokens on every run and say nothing about the code.
Each comment names its reviewer, by reviewer name when it has one.
The coding agent answers with its reply command (the reply channel's dt-reply,
ForAskingTheCodingAgent.reply_command), and nothing in the prompt names the
store. Threads are the core's (core/review/model.py, Thread).
"""
from __future__ import annotations

from typing import Collection, List, Sequence

from ..review.model import Comment, Thread

ANCHOR_MAX_LINES = 20

PROMPT = """New review comments. Everything you need is below.

{commits}{threads}

Rules:
- Reply to EVERY thread under 'Reply to these threads', with: {dt_reply} <thread> "<answer>"
  <thread> is the 8 characters after 'Thread'. Write only the answer: difftate marks it as your reply.
  For an answer with quotes or several lines, pass it on stdin: {dt_reply} <thread> <<'EOF' … EOF
- 'Other threads' are context only, each marked with its thread status. Read them for related comments, and do not undo a fix or make again a suggestion that a resolved or dismissed thread holds. Reply to an open one only if what you do in this run also addresses it; never reply to a resolved or dismissed one.
- Lines starting 'reviewer' are reviewers' comments, with the reviewer's name when it has one ('reviewer security-bot:'). Those marked '(new)' are the comments to answer now. Lines starting 'you:' are your earlier replies.
- Change code ONLY when the reviewer explicitly asks ('fix this', 'rename X to Y', 'add X'). Then reply with what you changed (file:line).
- Questions: answer. Suggestions, 'should we…?', nits: give your take and ask before changing anything. Unclear: ask for clarification. Never skip a thread silently.
- NEVER resolve or dismiss threads, and never edit or delete comments.
- A thread marked 'outdated' was written on code that changed since: its code block is the code then, not the file now.
- Read files as needed for context.
- Write replies in ASD-STE100 Simplified Technical English.
Summarize briefly what you handled."""


def build(threads: Sequence[Thread], ids: Collection[str], new_ids: Collection[str], reply_command: str,
          commit_messages: Sequence[str]) -> str:
    """The prompt for a run on the threads <ids>, among all the review's <threads>.
    <new_ids> holds the ids of the comments the run is sent: no run had them.
    <reply_command> is how the coding agent answers, ready for its shell.
    <commit_messages> are the review's, oldest first."""
    return PROMPT.format(commits=commits_part(commit_messages), threads=threads_part(threads, ids, new_ids),
                         dt_reply=reply_command)


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


def render_full(t: Thread, new_ids: Collection[str], with_status: bool = False) -> str:
    """<t> with its code and every comment and reply; <with_status> adds its
    thread status in the heading."""
    outdated = t.outdated
    lines = [f"### Thread {t.id[:8]} — {location(t)}{f' — {t.status}' if with_status else ''}"
             f"{OUTDATED_MARK if outdated else ''}"]
    code = ((t.anchor and t.anchor.code) or "").rstrip("\n")
    if code:
        code_lines = code.split("\n")
        if len(code_lines) > ANCHOR_MAX_LINES:
            code_lines = code_lines[:ANCHOR_MAX_LINES] + [f"… ({len(code_lines) - ANCHOR_MAX_LINES} more lines)"]
        lines += ["Code when the thread was written:" if outdated else "Code:", "```", *code_lines, "```"]
    lines += [f"{_speaker(c, new_ids)}: {c.body.strip()}" for c in _conversation(t)]
    return "\n".join(lines)


def threads_part(threads: Sequence[Thread], ids: Collection[str], new_ids: Collection[str]) -> str:
    ids, new_ids = set(ids), set(new_ids)
    mine = [t for t in threads if t.id in ids]
    others = [render_full(t, new_ids=(), with_status=True) for t in threads if t.id not in ids and _conversation(t)]
    out = [f"## Reply to these threads ({len(mine)})", ""]
    out += ["\n\n".join(render_full(t, new_ids) for t in mine)]
    if others:
        out += ["", f"## Other threads ({len(others)}) — context only", "", "\n\n".join(others)]
    return "\n".join(out)
