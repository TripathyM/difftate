"""The prompt for one run: the threads it answers in full, a summary of the other
open threads, and the rules.

Notes are left out: they cost tokens on every run and say nothing about the code.
(lib/threads.py builds the same prompt for the bash watcher, from diffity's JSON.)
"""
ANCHOR_MAX_LINES = 20
SUMMARY_MAX = 200  # chars per comment in the "other open threads" section

PROMPT = """New review comments. Everything you need is below.

{threads}

Rules:
- {reply}
- 'Other open threads' are context only, to spot related comments. Reply there only if what you do in this run also addresses it.
- Lines starting 'reviewer (new):' are the comments to answer now. Lines starting 'you:' are your earlier replies.
- Change code ONLY when the reviewer explicitly asks ('fix this', 'rename X to Y', 'add X'). Then reply with what you changed (file:line).
- Questions: answer. Suggestions, 'should we…?', nits: give your take and ask before changing anything. Unclear: ask for clarification. Never skip a thread silently.
- NEVER resolve or dismiss threads, and never edit or delete comments.
- Read files as needed for context.
- Write replies in ASD-STE100 Simplified Technical English.
Summarize briefly what you handled."""


def build(open_threads, ids, new_ids, reply):
    """The prompt for a run on the threads <ids>. <new_ids> holds the ids of the
    comments no run has been sent yet; <reply> says how the agent replies."""
    return PROMPT.format(threads=threads_part(open_threads, ids, new_ids), reply=reply)


def location(t):
    a = t["anchor"]
    if a is None:
        return "general thread (not tied to a line)"
    start, end = a["startLine"], a["endLine"]
    loc = f"{a['file']}:{start}" + (f"-{end}" if end != start else "")
    return loc + (" (old side, before the change)" if a["side"] == "old" else "")


def _conversation(t):
    """The thread's comments and replies, without notes."""
    return [c for c in t["comments"] if c["kind"] in ("comment", "reply")]


def _speaker(c, new_ids=()):
    if c["kind"] == "reply":
        return "you"
    return "reviewer (new)" if c["id"] in new_ids else "reviewer"


def short(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_full(t, new_ids):
    lines = [f"### Thread {t['id'][:8]} — {location(t)}"]
    code = ((t["anchor"] or {}).get("code") or "").rstrip("\n")
    if code:
        code = code.split("\n")
        if len(code) > ANCHOR_MAX_LINES:
            code = code[:ANCHOR_MAX_LINES] + [f"… ({len(code) - ANCHOR_MAX_LINES} more lines)"]
        lines += ["Code:", "```", *code, "```"]
    lines += [f"{_speaker(c, new_ids)}: {c['body'].strip()}" for c in _conversation(t)]
    return "\n".join(lines)


def render_summary(t):
    comments = _conversation(t)
    if not comments:
        return None
    shown = [comments[0]] + ([comments[-1]] if len(comments) > 1 else [])
    parts = []
    for i, c in enumerate(shown):
        if i == 1 and len(comments) > 2:
            parts.append(f"  … {len(comments) - 2} more")
        parts.append(f"  {_speaker(c)}: {short(c['body'], SUMMARY_MAX)}")
    return "\n".join([f"- {t['id'][:8]} — {location(t)}", *parts])


def threads_part(threads, ids, new_ids):
    ids, new_ids = set(ids), set(new_ids)
    mine = [t for t in threads if t["id"] in ids]
    others = [s for s in (render_summary(t) for t in threads if t["id"] not in ids) if s]
    out = [f"## Reply to these threads ({len(mine)})", ""]
    out += ["\n\n".join(render_full(t, new_ids) for t in mine)]
    if others:
        out += ["", f"## Other open threads ({len(others)}) — context only", "", *others]
    return "\n".join(out)
