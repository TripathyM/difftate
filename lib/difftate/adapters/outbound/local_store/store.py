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
from .lines import lines_text, read_events

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
        self._expected = self._read() or b""  # the events file as this store wrote it
        self._stat = self._stat_now()
        self._events = read_events(self._expected.decode("utf-8", errors="replace"))

    @classmethod
    def open(cls, difftate_folder: str, branch: str, base: str,
             on_tamper: Optional[Callable[[List[str]], None]] = None) -> LocalStore:
        """The store of the review of <branch> against <base>, in
        <difftate_folder>/reviews/ (<git dir>/difftate): started now, or reused."""
        rid = review_id(branch, base)
        folder = os.path.join(difftate_folder, "reviews", rid)
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

    @staticmethod
    def review_ids(difftate_folder: str) -> List[str]:
        """The ids of the reviews kept in <difftate_folder>/reviews/: one per
        folder there."""
        reviews = os.path.join(difftate_folder, "reviews")
        try:
            return [r for r in os.listdir(reviews) if os.path.isdir(os.path.join(reviews, r))]
        except FileNotFoundError:
            return []

    def review(self) -> Dict[str, Optional[str]]:
        """The review this store keeps: its id, branch and base."""
        return {k: self.info.get(k) for k in ("id", "branch", "base")}

    # ── The port for keeping the review ──────────────────────────────────────
    def load(self) -> List[Event]:
        with self._lock:
            self._restore_if_changed()
            return list(self._events)

    def append(self, events: List[Event]) -> None:
        if not events:
            return
        data = lines_text(events).encode("utf-8")
        with self._lock:
            self._restore_if_changed()
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

    def _read(self) -> Optional[bytes]:
        """The events file as it is now; None when there is none."""
        try:
            with open(self.events_file, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def _restore_if_changed(self) -> None:
        """Put the events file back as this store wrote it if it changed in a
        way this store didn't make, and report the threads the changed lines
        name."""
        if self._stat_now() == self._stat:
            return
        found = self._read()
        if found == self._expected:
            self._stat = self._stat_now()
            return
        ours = set(self._expected.splitlines())
        theirs = set((found or b"").splitlines())
        thread_ids: Set[str] = set()
        for raw in ours ^ theirs:
            try:
                line = json.loads(raw)
                named = [line.get("thread")] + list(line.get("threads") or [])
            except (ValueError, AttributeError, TypeError):
                continue
            thread_ids.update(t for t in named if isinstance(t, str))
        tmp = f"{self.events_file}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(self._expected)
            os.replace(tmp, self.events_file)
        except OSError as e:
            raise CouldNotRead(f"could not restore the review: {e}") from e
        self._stat = self._stat_now()
        self.on_tamper(sorted(thread_ids))
