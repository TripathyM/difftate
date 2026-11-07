"""The local store: a review's events in its folder, in the repository's git
folder (`<git dir>/difftate/reviews/<review id>/`, shared by worktrees, never
committed). It plugs into the core's port for keeping the review.

  review.json    {"id", "branch", "base", "started"}
  events.jsonl   one line per event, only ever appended (lines.py)

The store holds no rules: it keeps every event it is given (ADR 0004).

Only the watcher writes the store, and it knows every line it wrote. When the
events file changes in a way it didn't make (the coding agent with the sandbox
off, say), the store puts it back as it wrote it and calls on_tamper with the
threads that the changed lines name.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple

from ....core.review.model import CouldNotRead, Event
from .lines import line_from_event, line_text, read_events

REVIEW_FILE = "review.json"
EVENTS_FILE = "events.jsonl"


def review_id(branch: str, base: str) -> str:
    """A review's id, its folder's name: readable, and different for every
    branch and base."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch)[:40].strip("-.") or "review"
    digest = hashlib.sha1(f"{branch}\0{base}".encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def _now() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LocalStore:
    def __init__(self, folder: str, info: Optional[Dict[str, str]] = None,
                 on_tamper: Optional[Callable[[List[str]], None]] = None) -> None:
        """The store over the review folder <folder>, which exists. <info> is
        its review.json; <on_tamper>: (the ids of the threads the changed
        lines name) -> None."""
        self.folder = folder
        self.info = dict(info or {})
        self.on_tamper = on_tamper or (lambda ids: None)
        self.events_file = os.path.join(folder, EVENTS_FILE)
        self._lock = threading.Lock()
        try:
            with open(self.events_file, "rb") as f:
                self._expected = f.read()  # the events file as this store wrote it
        except FileNotFoundError:
            self._expected = b""
        self._stat = self._stat_now()
        self._events = read_events(self._expected.decode("utf-8", errors="replace"))

    @classmethod
    def open(cls, review_folder: str, branch: str, base: str,
             on_tamper: Optional[Callable[[List[str]], None]] = None) -> LocalStore:
        """The store of the review of <branch> against <base>, in
        <review_folder>/reviews/: started now, or reused."""
        rid = review_id(branch, base)
        folder = os.path.join(review_folder, "reviews", rid)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        review_file = os.path.join(folder, REVIEW_FILE)
        try:
            with open(review_file, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {"id": rid, "branch": branch, "base": base, "started": _now()}
            with open(review_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(info, indent=2) + "\n")
        return cls(folder, info, on_tamper)

    def review(self) -> Dict[str, Optional[str]]:
        """The review this store keeps: its id, branch and base."""
        return {k: self.info.get(k) for k in ("id", "branch", "base")}

    # ── The port for keeping the review ──────────────────────────────────────
    def load(self) -> List[Event]:
        with self._lock:
            self._check()
            return list(self._events)

    def append(self, events: List[Event]) -> None:
        if not events:
            return
        data = "".join(line_text(line_from_event(e)) for e in events).encode("utf-8")
        with self._lock:
            self._check()
            try:
                with open(self.events_file, "ab") as f:
                    f.write(data)
            except OSError as e:
                raise CouldNotRead(f"could not write the review: {e}") from e
            self._expected += data
            self._stat = self._stat_now()
            self._events.extend(events)

    # ── The tamper check ─────────────────────────────────────────────────────
    def _stat_now(self) -> Optional[Tuple[int, int]]:
        try:
            st = os.stat(self.events_file)
            return st.st_size, st.st_mtime_ns
        except FileNotFoundError:
            return None

    def _check(self) -> None:
        """Restore the events file if it changed in a way this store didn't make."""
        if self._stat_now() == self._stat:
            return
        try:
            with open(self.events_file, "rb") as f:
                found: Optional[bytes] = f.read()
        except FileNotFoundError:
            found = None
        if found == self._expected:
            self._stat = self._stat_now()
            return
        ours = set(self._expected.splitlines())
        theirs = set((found or b"").splitlines())
        tids: Set[str] = set()
        for raw in ours ^ theirs:
            try:
                line = json.loads(raw)
                named = [line.get("thread")] + list(line.get("threads") or [])
            except (ValueError, AttributeError, TypeError):
                continue
            tids.update(t for t in named if isinstance(t, str))
        tmp = f"{self.events_file}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(self._expected)
        os.replace(tmp, self.events_file)
        self._stat = self._stat_now()
        self.on_tamper(sorted(tids))
