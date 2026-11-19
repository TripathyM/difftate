"""Exporting a review (GLOSSARY.md, Export): a copy of it for an agent session
the reviewer starts.

It holds the review's commit messages, every thread in full with its thread
status and thread state, which threads need an answer, and how to reply. It
holds no other rule: the reviewer says in the session what to do. It keeps and
records nothing, so it changes no thread.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from ...changes.ports import ForReadingTheCode
from ..model import ListedThread, NotesInProgress
from ..ports import ForKeepingTheReview
from ..rendering import commits_part, render_full
from .list_threads import list_threads

AGENT = "coding agent"  # who the export calls the replies' writer: the session reading it didn't write them all

INTRO = """# Review export

A copy of a code review as it stands now: its commit messages, then every thread in full. The reviewer tells you what to do with it.

Lines starting 'reviewer' are reviewers' comments, with the reviewer's name when it has one ('reviewer security-bot:'). Lines starting '{agent}:' are replies. A thread's heading names its thread status (open, resolved or dismissed) and, for an open one, its thread state in parentheses: held, waiting, queued, working, replied or failed. A thread marked 'outdated' was written on code that changed since: its code block is the code then, not the file now."""

HOW_TO_REPLY = """## How to reply

Reply to a thread with: {dt_reply} <thread> "<answer>"
<thread> is the 8 characters after 'Thread'. Write only the answer: difftate posts it as a reply. A reply changes no thread status.
For an answer with quotes or several lines, pass it on stdin: {dt_reply} <thread> <<'EOF' … EOF"""


def needs_an_answer(listed: ListedThread) -> bool:
    """Whether the thread is open and no reply answers its latest reviewer
    comment yet: held, waiting, queued, working or failed."""
    return listed.thread.status == "open" and listed.state != "replied"


def export_review(store: ForKeepingTheReview, notes: NotesInProgress, code: ForReadingTheCode,
                  reply_command: Callable[[Optional[str]], str], folder: Optional[str] = None) -> str:
    """The review as text. <reply_command>(folder) is how a session replies,
    ready for its shell: with the <folder> when one was given. Raises
    CouldNotRead when the commit messages can't be read: an export that left
    them out would look as if the review had none."""
    listed = list_threads(store, notes, code)
    messages = code.commit_messages()
    needing = [t for t in listed if needs_an_answer(t)]
    others = [t for t in listed if not needs_an_answer(t)]
    parts: List[str] = [INTRO.format(agent=AGENT), "", commits_part(messages).rstrip("\n")]
    parts += [section("Threads that need an answer", needing, "None."), section("Other threads", others, "None."),
              HOW_TO_REPLY.format(dt_reply=reply_command(folder))]
    return "\n\n".join(p for p in parts if p) + "\n"


def section(title: str, threads: List[ListedThread], when_none: str) -> str:
    out = f"## {title} ({len(threads)})\n\n"
    if not threads:
        return out + when_none
    return out + "\n\n".join(
        render_full(t.thread, new_ids=(), with_status=True, state=t.state, agent=AGENT) for t in threads)
