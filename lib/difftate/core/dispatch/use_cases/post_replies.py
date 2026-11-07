"""Posting the coding agent's replies."""
from __future__ import annotations

from ...review.model import CODING_AGENT, ReviewError
from ..model import Dispatch
from ..ports import ForReporting


def post_replies(dispatch: Dispatch, report: ForReporting, last_try: bool = False) -> None:
    """Post the replies the run in progress gave as the coding agent's.

    Only a thread that was open when the run started gets one: the coding
    agent can write anything into its reply channel. A reply the review
    refuses stays for the next try; after the last one it is reported, so it
    isn't lost."""
    run = dispatch.run
    if run is None:
        return
    left = []
    for reply in run.replies:
        if reply.thread_id not in run.reply_to:
            report.warning(f"dropped a reply to thread {reply.thread_id[:8]}: it isn't open in this run")
            continue
        try:
            dispatch.review.add_comment(CODING_AGENT, reply.thread_id, "reply", reply.body)
        except ReviewError as e:
            if last_try:
                report.warning(f"could not post the reply to thread {reply.thread_id[:8]} ({e}). The reply:")
                report.output(reply.body)
            else:
                left.append(reply)
    run.replies = left
