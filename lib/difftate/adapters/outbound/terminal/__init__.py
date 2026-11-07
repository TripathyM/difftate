"""The terminal: Dispatch reports here, as the watcher's lines (ForReporting).

Dispatch's own lines start with the time ("[12:00:00] ..."). The coding
agent's lines are indented under them ("  [12:00:01] 🔧 Read  app.py").
"""
from __future__ import annotations

import time
from typing import Optional

from ....core.dispatch.model import short

TEXT_MAX = 300  # characters of the coding agent's text shown


def now() -> str:
    return time.strftime("%H:%M:%S")


class Terminal:
    def _line(self, text: str) -> None:
        print(f"[{now()}] {text}", flush=True)

    def _agent(self, icon: str, text: str) -> None:
        print(f"  [{now()}] {icon} {text}", flush=True)

    def dispatching(self, agent: str) -> None:
        self._line(f"New/changed threads detected — dispatching to {agent}")

    def model_chosen(self, model: str, source: str) -> None:
        print(f"  Model: {model} (from {source})" if model else "  Model: CLI default", flush=True)

    def session_started(self, session: str, model: str) -> None:
        self._agent("🚀", f"session {session[:8]} started · model {model}")

    def said(self, text: str) -> None:
        self._agent("💬", short(text, TEXT_MAX))

    def step(self, label: str, failed: bool) -> None:
        self._agent("❌" if failed else "🔧", label)

    def agent_error(self, error: str) -> None:
        self._agent("❌", error)

    def finished(self, ok: bool, secs: int, cost: Optional[float], context: str) -> None:
        extra = f", ${cost:.4f}" if isinstance(cost, (int, float)) else ""
        extra += f" · {context}" if context else ""
        self._agent("✅" if ok else "❌", f"{'done' if ok else 'failed'} in {secs}s{extra}")

    def output(self, line: str) -> None:
        print(line, flush=True)

    def unparsed(self, reason: str) -> None:
        self._agent("⚠️", f"unparsed event ({reason})")

    def outdated(self, thread_id: str) -> None:
        self._line(f"Thread {thread_id[:8]} is outdated: its code changed")

    def queued(self, thread_id: str) -> None:
        self._line(f"Queued thread {thread_id[:8]} (agent busy)")

    def no_reply(self, thread_id: str, watcher_stopped: bool) -> None:
        why = "the watcher stopped during its run" if watcher_stopped else "it waits for your next comment"
        self._line(f"No reply to thread {thread_id[:8]} — {why}")

    def stopping(self, pid: int) -> None:
        print(f"Stopping running agent (pid {pid})...", flush=True)

    def warning(self, text: str) -> None:
        self._line(f"Warning: {text}")
