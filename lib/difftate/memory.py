"""The memory store: the review in this process's memory, for tests."""
import copy
import threading
import uuid

from .store import AUTHOR_OF, StoreError, now


class MemoryStore:
    def __init__(self, commit=None):
        self.commit = commit
        self.review_id = str(uuid.uuid4())
        self._threads = []
        self._runs = []
        self._viewed = {}
        self._lock = threading.Lock()

    def review(self):
        return {"id": self.review_id}

    def threads(self, status=None):
        with self._lock:
            return copy.deepcopy([t for t in self._threads if status is None or t["status"] == status])

    def open_thread(self, anchor, body):
        thread = {"id": str(uuid.uuid4()), "anchor": None if anchor is None else dict(anchor, commit=self.commit),
                  "outdated": False, "status": "open", "comments": [self._comment("comment", body)]}
        with self._lock:
            self._threads.append(thread)
            return copy.deepcopy(thread)

    def add_comment(self, thread_id, kind, body):
        comment = self._comment(kind, body)
        with self._lock:
            self._find(thread_id)["comments"].append(comment)
            return dict(comment)

    def edit_note(self, note_id, kind, body, final=False):
        with self._lock:
            for t in self._threads:
                for c in t["comments"]:
                    if c["id"] == note_id:
                        c.update(kind=kind, body=body)
                        return dict(c)
        raise StoreError(404, f"no note {note_id}")

    def set_status(self, thread_id, status):
        with self._lock:
            self._find(thread_id)["status"] = status
        return {"id": thread_id, "status": status}

    def move_thread(self, thread_id, start, end, snapshot):
        with self._lock:
            self._find(thread_id)["anchor"].update(startLine=start, endLine=end, snapshot=snapshot)

    def mark_outdated(self, thread_id):
        with self._lock:
            self._find(thread_id)["outdated"] = True

    def record_run(self, run):
        with self._lock:
            self._runs.append(dict(copy.deepcopy(run), outcome=None))

    def record_run_end(self, run_id, outcome):
        with self._lock:
            for r in self._runs:
                if r["id"] == run_id:
                    r["outcome"] = outcome

    def runs(self):
        with self._lock:
            return copy.deepcopy(self._runs)

    def viewed(self):
        with self._lock:
            return dict(self._viewed)

    def mark_viewed(self, file, diff_hash):
        with self._lock:
            if diff_hash is None:
                self._viewed.pop(file, None)
            else:
                self._viewed[file] = diff_hash

    def _find(self, thread_id):
        for t in self._threads:
            if t["id"] == thread_id:
                return t
        raise StoreError(404, f"no thread {thread_id}")

    @staticmethod
    def _comment(kind, body):
        return {"id": str(uuid.uuid4()), "author": AUTHOR_OF[kind], "kind": kind, "body": body, "time": now()}
