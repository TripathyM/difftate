#!/usr/bin/env python3
"""Thread helpers for difftate-watch.sh.

Reads `diffity agent list --status open --json` on stdin.

  lib/threads.py pending       JSON of the threads waiting on the agent
  lib/threads.py prompt <ids>  Prompt text: the full conversation of <ids>
                              (comma-separated), plus a short summary of every
                              other open thread so the agent can spot related ones

Watcher status comments (live checklist, "🕒 Queued") are left out of the
prompt: they cost tokens on every run and say nothing about the code.
"""
import json
import os
import sys

REPLY = os.environ.get("DT_REPLY_MARKER", "[dt-reply]")
STATUS = os.environ.get("DT_STATUS_MARKER", "[dt-status]")
QUEUED = os.environ.get("DT_QUEUED_MARKER", "[dt-queued]")
ANCHOR_MAX_LINES = 20
SUMMARY_MAX = 200  # chars per comment in the "other open threads" section


def body(c):
    return c.get("body") or ""


def is_status(c):
    b = body(c)
    return b.startswith(STATUS) or b.startswith(QUEUED)


def awaiting_agent(t):
    """The last real comment is the user's. "🕒 Queued" doesn't count: it
    marks a thread that still needs the agent."""
    comments = [c for c in t.get("comments") or [] if not body(c).startswith(QUEUED)]
    if not comments:
        return False
    last = body(comments[-1])
    return not (last.startswith(REPLY) or last.startswith(STATUS))


def location(t):
    path = t.get("filePath") or "?"
    if path == "__general__":
        return "general comment (not tied to a line)"
    start, end = t.get("startLine"), t.get("endLine")
    loc = f"{path}:{start}" + (f"-{end}" if end and end != start else "")
    return loc + (" (old side of the diff)" if t.get("side") == "old" else "")


def speaker(c):
    b = body(c)
    if b.startswith(REPLY):
        return "you", b[len(REPLY):].strip()
    name = (c.get("author") or {}).get("name") or "?"
    # Another agent (e.g. a separate reviewer) has no marker
    return ("user" if (c.get("author") or {}).get("type") != "agent" else name), b.strip()


def short(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_full(t):
    lines = [f"### Thread {t['id'][:8]} — {location(t)}"]
    anchor = (t.get("anchorContent") or "").rstrip("\n")
    if anchor:
        code = anchor.split("\n")
        if len(code) > ANCHOR_MAX_LINES:
            code = code[:ANCHOR_MAX_LINES] + [f"… ({len(code) - ANCHOR_MAX_LINES} more lines)"]
        lines += ["Code:", "```", *code, "```"]
    for c in t.get("comments") or []:
        if is_status(c):
            continue
        who, text = speaker(c)
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def render_summary(t):
    comments = [c for c in t.get("comments") or [] if not is_status(c)]
    if not comments:
        return None
    shown = [comments[0]] + ([comments[-1]] if len(comments) > 1 else [])
    parts = []
    for i, c in enumerate(shown):
        who, text = speaker(c)
        if i == 1 and len(comments) > 2:
            parts.append(f"  … {len(comments) - 2} more")
        parts.append(f"  {who}: {short(text, SUMMARY_MAX)}")
    return "\n".join([f"- {t['id'][:8]} — {location(t)}", *parts])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    threads = json.load(sys.stdin)
    if mode == "pending":
        print(json.dumps([t for t in threads if awaiting_agent(t)]))
    elif mode == "prompt":
        ids = set(i for i in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if i)
        mine = [t for t in threads if t.get("id") in ids]
        others = [s for s in (render_summary(t) for t in threads if t.get("id") not in ids) if s]
        out = [f"## Reply to these threads ({len(mine)})", ""]
        out += ["\n\n".join(render_full(t) for t in mine)]
        if others:
            out += ["", f"## Other open threads ({len(others)}) — context only", "", *others]
        print("\n".join(out))
    else:
        sys.exit(__doc__)


main()
