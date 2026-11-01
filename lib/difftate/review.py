"""The Review: threads, comments, replies and notes, and the rules for them.

Every change to the review goes through here, so the rules hold whatever the
store or the caller (a viewer through the API, or Dispatch):
  1. Only a reviewer opens a thread or changes its thread status.
  2. The agent writes only replies.
  3. Only difftate writes notes, and only notes can be edited.
  4. One rule gives the thread state (thread_state below).

Dispatch records which comments each run was sent. That record lives in the
watcher's memory; when the watcher starts, it is recovered from the progress
notes (a run's progress note comes after every comment the run was sent).
"""
import threading

from .store import AUTHOR_OF, KINDS, NOTE_KINDS, StoreError, need_anchor, need_kind, need_status, need_text

REVIEWER = AUTHOR_OF["comment"]


def _unsent(thread, sent):
    return [c["id"] for c in thread["comments"] if c["author"] == REVIEWER and c["id"] not in sent]


def _replies(thread):
    return {c["id"] for c in thread["comments"] if c["kind"] == "reply"}


def thread_state(thread, sent, running, replies_before):
    """Where an open thread stands in the loop (None for a resolved or dismissed one).

      waiting   it has a reviewer's comment that no run has been sent yet
      queued    waiting while a run handles other threads
      working   the run in progress has it
      replied   the agent spoke last, and every reviewer comment was sent to a run
      failed    its run ended with no reply to it

    <sent> holds the ids of comments sent to a run; <running> the ids of the
    threads the run in progress has (empty when no run is in progress);
    <replies_before> the ids of the replies the thread had when its last run started.
    """
    if thread["status"] != "open":
        return None
    if thread["id"] in running:
        return "working"
    if _unsent(thread, sent):
        return "queued" if running else "waiting"
    # A reply to an earlier comment doesn't answer a later one: only a reply
    # written since the last run started does
    return "replied" if _replies(thread) - replies_before.get(thread["id"], set()) else "failed"


class Review:
    def __init__(self, store):
        self.store = store
        self._sent = set()  # ids of the comments sent to a run
        self._running = frozenset()  # ids of the threads in the run in progress
        self._replies_before = {}  # thread id: ids of its replies when its last run started
        self._lock = threading.Lock()

    # ── Reading ──────────────────────────────────────────────────────────────
    def review(self):
        return self.store.review()

    def threads(self, status=None):
        """The threads, each with its thread state."""
        if status is not None:
            need_status(status)
        threads = self.store.threads(status)
        for t in threads:
            self._with_state(t)
        return threads

    def unsent(self, thread):
        """The ids of the thread's reviewer comments that no run has been sent yet."""
        with self._lock:
            return _unsent(thread, self._sent)

    # ── Changing the review (rules 1–3) ──────────────────────────────────────
    def open_thread(self, anchor, body, author=REVIEWER):
        if author != REVIEWER:
            raise StoreError(403, "only a reviewer opens a thread")
        thread = self.store.open_thread(need_anchor(anchor), need_text(body))
        return self._with_state(thread)

    def add_comment(self, thread_id, kind, body):
        """A reviewer's comment, the agent's reply, or difftate's note: <kind> says which."""
        return self.store.add_comment(thread_id, need_kind(kind, KINDS), need_text(body))

    def edit_note(self, note_id, kind, body):
        need_kind(kind, NOTE_KINDS)
        need_text(body)
        found = next((c for t in self.store.threads() for c in t["comments"] if c["id"] == note_id), None)
        if found is None:
            raise StoreError(404, f"no note {note_id}")
        if found["kind"] not in NOTE_KINDS:
            raise StoreError(403, f"{note_id} is not a note: only notes can be edited")
        return self.store.edit_note(note_id, kind, body)

    def set_status(self, thread_id, status, author=REVIEWER):
        if author != REVIEWER:
            raise StoreError(403, "only a reviewer changes a thread's status")
        return self.store.set_status(thread_id, need_status(status))

    # ── Runs (Dispatch) ──────────────────────────────────────────────────────
    def start_run(self, threads):
        """A run starts on <threads>: every reviewer comment in them is sent to it."""
        with self._lock:
            for t in threads:
                self._sent.update(_unsent(t, self._sent))
                self._replies_before[t["id"]] = _replies(t)
            self._running = frozenset(t["id"] for t in threads)

    def end_run(self):
        """The run ended. Returns the open threads it left failed: no reply to them."""
        with self._lock:
            ran, self._running = self._running, frozenset()
        return [t for t in self.threads("open") if t["id"] in ran and t["state"] == "failed"]

    def recover_runs(self):
        """At start: a reviewer comment followed by a progress note was sent to a
        run, even one this watcher didn't record (an earlier watcher, or the bash
        one), and that run started where its progress note is."""
        sent, replies_before = set(), {}
        for t in self.store.threads():
            seen, replies = [], set()
            for c in t["comments"]:
                if c["author"] == REVIEWER:
                    seen.append(c["id"])
                elif c["kind"] == "reply":
                    replies.add(c["id"])
                elif c["kind"] == "progress":
                    sent.update(seen)
                    replies_before[t["id"]] = set(replies)
        with self._lock:
            self._sent |= sent
            self._replies_before.update(replies_before)

    def _with_state(self, thread):
        with self._lock:
            thread["state"] = thread_state(thread, self._sent, self._running, self._replies_before)
        return thread
