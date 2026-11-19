"""The prompt for one run: the review's commit messages, the threads it
answers, every other thread of the review, and the rules. How the review's
state reads (the commit messages, a thread in full) is the review's, shared
with an export (core/review/rendering.py); the sections and the rules are the
run's.

The other threads are context only, each with its thread status: a question
in one informs the answer in another, and a resolved or dismissed one holds a
fix, a preference or a rejected suggestion the run must not undo or make again.
The coding agent answers with its reply command (the reply channel's dt-reply,
ForAskingTheCodingAgent.reply_command), and nothing in the prompt names the
store.
"""
from __future__ import annotations

from typing import Collection, Sequence

from ..review.model import Thread
from ..review.rendering import commits_part, conversation, render_full

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


def threads_part(threads: Sequence[Thread], ids: Collection[str], new_ids: Collection[str]) -> str:
    ids, new_ids = set(ids), set(new_ids)
    mine = [t for t in threads if t.id in ids]
    others = [render_full(t, new_ids=(), with_status=True) for t in threads if t.id not in ids and conversation(t)]
    out = [f"## Reply to these threads ({len(mine)})", ""]
    out += ["\n\n".join(render_full(t, new_ids) for t in mine)]
    if others:
        out += ["", f"## Other threads ({len(others)}) — context only", "", "\n\n".join(others)]
    return "\n".join(out)
