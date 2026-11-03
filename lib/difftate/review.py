"""The Review: threads, comments, replies and notes, and the rules for them.

Every change to the review goes through here, so the rules hold whatever the
store or the caller (a viewer through the API, or Dispatch):
  1. Only a reviewer opens a thread or changes its thread status.
  2. The coding agent writes only replies.
  3. Only difftate writes notes, and only notes can be edited.
  4. One rule gives the thread state (thread_state below).

Dispatch records which comments each run was sent: in the watcher's memory,
and as a run in the store. When the watcher starts, it reads the runs back. A
store that can't keep runs (diffity) has them recovered from the progress notes
instead (a run's progress note comes after every comment the run was sent).
"""
import threading
import uuid

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
      replied   the coding agent spoke last, and every reviewer comment was sent to a run
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
        self._run_id = None  # the run in progress
        self._replies_before = {}  # thread id: ids of its replies when its last run started
        self._final = set()  # ids of the notes that won't change again
        self._notes_lock = threading.Lock()  # one note edit at a time, so a final one is last
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
        """A reviewer's comment, the coding agent's reply, or difftate's note: <kind> says which."""
        return self.store.add_comment(thread_id, need_kind(kind, KINDS), need_text(body))

    def edit_note(self, note_id, kind, body, final=False):
        """<final> when the note won't change again: Dispatch says so when a run ends."""
        need_kind(kind, NOTE_KINDS)
        need_text(body)
        with self._notes_lock:
            found = next((c for t in self.store.threads() for c in t["comments"] if c["id"] == note_id), None)
            if found is None:
                raise StoreError(404, f"no note {note_id}")
            if found["kind"] not in NOTE_KINDS:
                raise StoreError(403, f"{note_id} is not a note: only notes can be edited")
            # A late edit (a formatter stopped mid-request) can't undo a run's final line
            if note_id in self._final and not final:
                raise StoreError(409, f"the note {note_id} is final")
            edited = self.store.edit_note(note_id, kind, body, final)
            if final:
                self._final.add(note_id)
            return edited

    def set_status(self, thread_id, status, author=REVIEWER):
        if author != REVIEWER:
            raise StoreError(403, "only a reviewer changes a thread's status")
        return self.store.set_status(thread_id, need_status(status))

    # ── Runs (Dispatch) ──────────────────────────────────────────────────────
    def start_run(self, threads):
        """A run starts on <threads>: every reviewer comment in them is sent to it.
        The store keeps the run (StoreError when it can't)."""
        with self._lock:
            sent = [cid for t in threads for cid in _unsent(t, self._sent)]
            self._sent.update(sent)
            for t in threads:
                self._replies_before[t["id"]] = _replies(t)
            self._running = frozenset(t["id"] for t in threads)
            self._run_id = str(uuid.uuid4())
            run = {"id": self._run_id, "threads": [t["id"] for t in threads], "sent": sent,
                   "repliesBefore": {t["id"]: sorted(self._replies_before[t["id"]]) for t in threads}}
        self.store.record_run(run)

    def end_run(self, outcome="done"):
        """The run ended (<outcome>: done, failed or stopped). Returns the open
        threads it left failed: no reply to them."""
        with self._lock:
            ran, self._running = self._running, frozenset()
            run_id, self._run_id = self._run_id, None
        if run_id:
            try:
                self.store.record_run_end(run_id, outcome)
            except StoreError:
                pass
        return [t for t in self.threads("open") if t["id"] in ran and t["state"] == "failed"]

    def recover_runs(self):
        """At start: the comments earlier runs were sent, from the store's runs.
        A run that never ended (its watcher was killed) ends as interrupted.
        Returns the open threads such a run left failed."""
        runs = self.store.runs()
        if runs is None:
            self._recover_from_notes()
            return []
        sent, replies_before, interrupted = set(), {}, []
        for r in runs:
            sent.update(r["sent"])
            replies_before.update((tid, set(ids)) for tid, ids in r["repliesBefore"].items())
            if r["outcome"] is None:
                interrupted.append(r)
        with self._lock:
            self._sent |= sent
            self._replies_before.update(replies_before)
        for r in interrupted:
            self.store.record_run_end(r["id"], "interrupted")
        ran = {tid for r in interrupted for tid in r["threads"]}
        return [t for t in self.threads("open") if t["id"] in ran and t["state"] == "failed"]

    def _recover_from_notes(self):
        """A reviewer comment followed by a progress note was sent to a run, even
        one this watcher didn't record (an earlier watcher), and that run started
        where its progress note is."""
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
