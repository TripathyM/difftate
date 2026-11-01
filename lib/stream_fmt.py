#!/usr/bin/env python3
"""Turn an agent's JSON event stream into live progress for the watcher.

Usage: <agent> ... | python3 -u lib/stream_fmt.py <claude|opencode>

claude:   `claude -p --output-format stream-json --verbose`
opencode: `opencode run --format json`

Progress goes to two places:
  - the terminal, one line per event
  - the review, as one progress note per thread that is edited in place
    (a live checklist) and ends as one "✅ Done" line. Enabled when
    DT_THREAD_IDS (comma-separated) is set, and either:
      DT_API + DT_TOKEN_FILE   the review API (the Python watcher)
      DT_PORT                  diffity's own API (the bash watcher)
    A thread's queued note becomes its progress note: DT_QUEUED_NOTES
    ({thread id: note id}) gives them for the review API; for diffity,
    DT_THREADS_JSON shows the threads that end in the "🕒 Queued" note.

Non-JSON lines are passed through unchanged so errors stay visible.
"""
import json
import os
import sys
import threading
import time
import urllib.request

TOOL = sys.argv[1] if len(sys.argv) > 1 else "claude"
START = time.time()
TEXT_MAX = 300
MAX_STEPS_SHOWN = 8
STATUS_REFRESH_S = 3  # re-render while idle so the elapsed timer keeps moving
COMPACT_WARN_PCT = 70  # suggest /compact at or above this share of the context window


def out(icon, msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {icon} {msg}", flush=True)


def short(s, n=120):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def describe(name, inp):
    """Pick the most useful argument to show for a tool call."""
    if not isinstance(inp, dict):
        return name
    for key in ("command", "file_path", "filePath", "path", "pattern", "url", "description"):
        if inp.get(key):
            return f"{name}  {short(inp[key])}"
    return name


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{n / 1000:.0f}k" if n >= 1000 else str(n)


class Context:
    """Session context size: tokens in the latest model call vs. the model's window."""

    def __init__(self):
        self.used = 0
        # Claude reports its window in the result event; others need DT_CONTEXT_WINDOW
        self.window = int(os.environ.get("DT_CONTEXT_WINDOW") or 0)

    def label(self):
        if not self.used:
            return ""
        if not self.window:
            return f"🧠 context {fmt_tokens(self.used)}"
        pct = 100 * self.used / self.window
        warn = " ⚠️ consider /compact" if pct >= COMPACT_WARN_PCT else ""
        return f"🧠 context {fmt_tokens(self.used)} / {fmt_tokens(self.window)} ({pct:.0f}%){warn}"


CONTEXT = Context()


# ── Progress notes ───────────────────────────────────────────────────────────
def _request(url, method, payload, headers=None):
    req = urllib.request.Request(
        url, method=method, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read() or b"null")
    except Exception:
        return None


class ReviewApiNotes:
    """Posts and edits progress notes through the review API (the Python watcher)."""

    def __init__(self, url, token_file):
        self.url = url.rstrip("/")
        with open(token_file) as f:
            self.headers = {"Authorization": f"Bearer {f.read().strip()}"}

    def post(self, tid, body):
        note = _request(f"{self.url}/api/threads/{tid}/comments", "POST",
                        {"kind": "progress", "body": body}, self.headers)
        return (note or {}).get("id")

    @staticmethod
    def queued_notes():
        """{thread id: queued note id}, from the watcher."""
        try:
            found = json.loads(os.environ.get("DT_QUEUED_NOTES") or "{}")
        except ValueError:
            return {}
        return found if isinstance(found, dict) else {}

    def edit(self, note_id, body):
        _request(f"{self.url}/api/notes/{note_id}", "PATCH", {"kind": "progress", "body": body}, self.headers)


class DiffityNotes:
    """Posts and edits progress notes in diffity directly (the bash watcher; goes with it)."""

    def __init__(self, port):
        self.url = f"http://localhost:{port}"
        self.marker = os.environ.get("DT_STATUS_MARKER", "[dt-status]")

    def post(self, tid, body):
        c = _request(f"{self.url}/api/threads/{tid}/reply", "POST",
                     {"body": f"{self.marker} {body}", "author": {"name": "Agent", "type": "agent"}})
        return (c or {}).get("id")

    def edit(self, note_id, body):
        _request(f"{self.url}/api/comments/{note_id}", "PATCH", {"body": f"{self.marker} {body}"})

    @staticmethod
    def queued_notes():
        """{thread id: comment id} for the threads whose last comment is the watcher's queued note."""
        marker = os.environ.get("DT_QUEUED_MARKER", "[dt-queued]")
        try:
            threads = json.loads(os.environ.get("DT_THREADS_JSON") or "[]")
        except ValueError:
            return {}
        found = {}
        for t in threads:
            comments = t.get("comments") or []
            if comments and (comments[-1].get("body") or "").startswith(marker):
                found[t["id"]] = comments[-1]["id"]
        return found


def notes_client():
    try:
        if os.environ.get("DT_API") and os.environ.get("DT_TOKEN_FILE"):
            return ReviewApiNotes(os.environ["DT_API"], os.environ["DT_TOKEN_FILE"])
    except OSError:
        return None
    if os.environ.get("DT_PORT"):
        return DiffityNotes(os.environ["DT_PORT"])
    return None


class Status:
    """One live checklist note per thread, edited in place."""

    def __init__(self):
        self.notes = notes_client()
        tids = [t for t in os.environ.get("DT_THREAD_IDS", "").split(",") if t]
        self.enabled = bool(self.notes and tids)
        self.steps = []  # [label, done]
        self.state = "thinking"  # thinking | working | done | failed
        self.note = ""
        self.lock = threading.Lock()
        self.note_ids = []
        if self.enabled:
            queued = self.notes.queued_notes()
            for tid in tids:
                if tid in queued:
                    # Reuse the watcher's "🕒 Queued" comment as the live checklist
                    self.note_ids.append(queued[tid])
                    continue
                note_id = self.notes.post(tid, self.render())
                if note_id:
                    self.note_ids.append(note_id)
            self.push()
            if not self.note_ids:
                out("⚠️", "could not post the progress note")
            threading.Thread(target=self._ticker, daemon=True).start()

    def render(self):
        secs = int(time.time() - START)
        head = {
            "thinking": f"⏳ **Thinking…** ({secs}s)",
            "working": f"⏳ **Working…** ({secs}s)",
            "done": f"✅ **Done** in {secs}s",
            "failed": f"❌ **Failed** after {secs}s",
        }[self.state]
        ctx = CONTEXT.label()
        lines = [head + (f" · {ctx}" if ctx else "")]
        if self.state == "done":
            # Finished: one line is enough, the agent's own reply has the details
            return lines[0]
        hidden = len(self.steps) - MAX_STEPS_SHOWN
        if hidden > 0:
            lines.append(f"- ✅ …{hidden} earlier steps")
        for label, done in self.steps[-MAX_STEPS_SHOWN:]:
            lines.append(f"- {'✅' if done else '⏳'} `{label}`")
        if self.note:
            lines.append(f"\n{self.note}")
        return "\n".join(lines)

    def push(self):
        if not self.note_ids:
            return
        with self.lock:
            body = self.render()
        for cid in self.note_ids:
            self.notes.edit(cid, body)

    def _ticker(self):
        while self.state in ("thinking", "working"):
            time.sleep(STATUS_REFRESH_S)
            self.push()

    def step(self, label):
        with self.lock:
            for s in self.steps:
                s[1] = True
            self.steps.append([short(label, 80), False])
            self.state = "working"
        self.push()

    def finish(self, ok, note=""):
        if self.state in ("done", "failed"):
            return
        with self.lock:
            for s in self.steps:
                s[1] = True
            self.state = "done" if ok else "failed"
            self.note = note
        self.push()


STATUS = Status()


def tool_call(desc, failed=False):
    out("❌" if failed else "🔧", desc)
    STATUS.step(desc)


def done(cost=None, ok=True, note=""):
    extra = f", ${cost:.4f}" if isinstance(cost, (int, float)) else ""
    ctx = CONTEXT.label()
    extra += f" · {ctx}" if ctx else ""
    out("✅" if ok else "❌", f"{'done' if ok else 'failed'} in {time.time() - START:.0f}s{extra}")
    STATUS.finish(ok, note)


# ── Tool adapters ────────────────────────────────────────────────────────────
def handle_claude(ev):
    t = ev.get("type")
    if t == "system" and ev.get("subtype") == "init":
        out("🚀", f"session {ev.get('session_id', '?')[:8]} started · model {ev.get('model', '?')}")
    elif t == "assistant":
        u = (ev.get("message") or {}).get("usage") or {}
        if u:
            CONTEXT.used = sum(u.get(k) or 0 for k in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"))
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                tool_call(describe(block.get("name", "?"), block.get("input")))
            elif block.get("type") == "text" and block.get("text", "").strip():
                out("💬", short(block["text"], TEXT_MAX))
    elif t == "result":
        windows = [m.get("contextWindow") or 0 for m in (ev.get("modelUsage") or {}).values()]
        CONTEXT.window = max(windows, default=0) or CONTEXT.window
        if ev.get("is_error"):
            msg = short(ev.get("result") or ev.get("subtype"), TEXT_MAX)
            out("❌", msg)
            done(ev.get("total_cost_usd"), ok=False, note=msg)
        else:
            done(ev.get("total_cost_usd"))


def handle_opencode(ev):
    t = ev.get("type")
    part = ev.get("part") or {}
    if t == "tool_use":
        state = part.get("state") or {}
        tool_call(describe(part.get("tool", "?"), state.get("input")), failed=state.get("status") == "error")
    elif t == "text" and part.get("text", "").strip():
        out("💬", short(part["text"], TEXT_MAX))
    elif t == "step_finish":
        handle_opencode.cost += part.get("cost") or 0
        tok = part.get("tokens") or {}
        cache = tok.get("cache") or {}
        used = sum(x or 0 for x in (tok.get("input"), tok.get("output"), cache.get("read"), cache.get("write")))
        if used:
            CONTEXT.used = used
        if part.get("reason") == "stop":
            done(handle_opencode.cost)
    elif t == "error":
        msg = short(ev.get("error") or ev, TEXT_MAX)
        out("❌", msg)
        done(handle_opencode.cost, ok=False, note=msg)


handle_opencode.cost = 0.0
HANDLERS = {"claude": handle_claude, "opencode": handle_opencode}

handler = HANDLERS.get(TOOL, handle_claude)
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line.strip():
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        print(line, flush=True)
        continue
    try:
        handler(ev)
    except Exception as e:  # never kill the agent's pipe over a formatting bug
        out("⚠️", f"unparsed event ({e})")

# Stream ended without a final event — the agent crashed or was killed
if STATUS.state not in ("done", "failed"):
    done(ok=False, note="Agent exited without finishing — check the watcher terminal.")
