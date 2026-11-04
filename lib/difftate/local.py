"""The local store: difftate's own, in the repository's git folder.

Each review (one branch against its base) has a folder in `<git dir>/difftate/
reviews/<review id>/` (shared by worktrees, never committed):
  review.json    {"id", "branch", "base", "started"}
  events.jsonl   one JSON line per event, only ever appended:
    {"type": "opened",  "thread", "anchor", "time"}
    {"type": "comment", "thread", "id", "author", "kind", "body", "time", "seq"}
                        a reviewer's comment or the coding agent's reply
    {"type": "note",    the same fields: a note's final body (a later line for
                        the same id replaces it)}
    {"type": "status",  "thread", "status", "time"}
    {"type": "run",     "run", "threads", "sent", "repliesBefore", "time"}
                        a run starts: the comments it was sent, and the replies
                        its threads had then
    {"type": "run-ended", "run", "outcome", "time"}
The current state comes from reading the lines in order. "seq" is a comment's
place in its thread, so a note stored when its run ends keeps the place where
it was posted.

Notes change while a run works (a progress note shows the run's steps live).
They stay in this process's memory until they are final (edit_note(..., final=True)); only
then are they stored. Nothing depends on them: the run lines say what each run
was sent, even when the watcher is killed during one.

Every stored line is also appended to the review history: one JSON-lines file
per month in `~/.difftate/history/`, with the repository, branch, base and
review added.

Only the watcher writes the store, and it knows every line it wrote. When the
events file changes in a way it didn't make (the coding agent with the sandbox
off, say), the store restores it and calls on_tamper with the threads that the
changed lines name.
"""
import copy
import datetime
import json
import os
import threading
import uuid

from . import changes
from .store import AUTHOR_OF, NOTE_KINDS, StoreError, now

REVIEW_FILE = "review.json"
EVENTS_FILE = "events.jsonl"


def history_folder():
    return os.path.join(os.path.expanduser("~"), ".difftate", "history")


def _line(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"


class History:
    """The review history: every stored line, from every review on this machine."""

    def __init__(self, folder, about):
        self.folder = folder
        self.about = about  # {"repo": {"path", "remote"}, "branch", "base", "review"}

    def append(self, events):
        month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
        try:
            os.makedirs(self.folder, mode=0o700, exist_ok=True)
            with open(os.path.join(self.folder, f"{month}.jsonl"), "a", encoding="utf-8") as f:
                f.write("".join(_line(dict(e, **self.about)) for e in events))
        except OSError as e:
            print(f"Warning: could not write the review history ({e})")


class LocalStore:
    def __init__(self, folder, info, history, on_tamper, commit):
        self.folder = folder
        self.info = info
        self.history = history
        self.on_tamper = on_tamper  # (thread ids) -> None
        self.commit = commit  # () -> the commit an anchor is written on
        self.events_file = os.path.join(folder, EVENTS_FILE)
        self._threads = {}  # id: thread, in the order they were opened
        self._runs = {}  # id: run, in the order they started
        self._seq = 0
        self._expected = b""  # the events file as this store wrote it
        self._stat = None
        self._lock = threading.Lock()

    @classmethod
    def open(cls, review_folder, cwd, branch, base, history=None, on_tamper=None):
        """Start the review of <branch> against <base>, or reuse it."""
        rid = changes.review_id(branch, base)
        folder = os.path.join(review_folder, "reviews", rid)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        review_file = os.path.join(folder, REVIEW_FILE)
        try:
            with open(review_file, encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            info = {"id": rid, "branch": branch, "base": base, "started": now()}
            with open(review_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(info, indent=2) + "\n")
        repo = {"path": os.path.realpath(cwd), "remote": changes.remote_url(cwd)}
        about = {"repo": repo, "branch": branch, "base": base, "review": rid}
        store = cls(folder, info, History(history or history_folder(), about), on_tamper or (lambda ids: None),
                    lambda: changes.head(cwd))
        store._load()
        return store

    # ── Reading the events ───────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.events_file, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = b""
        self._expected = data
        self._stat = self._stat_now()
        for raw in data.decode("utf-8", errors="replace").splitlines():
            try:
                self._apply(json.loads(raw))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue

    def _apply(self, e):
        kind = e["type"]
        if kind == "run":
            self._runs[e["run"]] = {"id": e["run"], "threads": list(e["threads"]), "sent": list(e["sent"]),
                                    "repliesBefore": dict(e["repliesBefore"]), "outcome": None}
            return
        if kind == "run-ended":
            self._runs[e["run"]]["outcome"] = e["outcome"]
            return
        if kind == "opened":
            self._threads[e["thread"]] = self._new_thread(e["thread"], e.get("anchor"))
            return
        thread = self._threads[e["thread"]]
        if kind == "status":
            thread["status"] = e["status"]
        elif kind in ("comment", "note"):
            comment = {k: e[k] for k in ("id", "author", "kind", "body", "time", "seq")}
            comment["stored"] = True
            found = next((c for c in thread["comments"] if c["id"] == comment["id"]), None)
            if found:
                found.update(comment)
            else:
                thread["comments"].append(comment)
                thread["comments"].sort(key=lambda c: c["seq"])
            self._seq = max(self._seq, comment["seq"])

    # ── Writing the events ───────────────────────────────────────────────────
    def _stat_now(self):
        try:
            st = os.stat(self.events_file)
            return st.st_size, st.st_mtime_ns
        except FileNotFoundError:
            return None

    def _append(self, events):
        data = "".join(_line(e) for e in events).encode("utf-8")
        try:
            with open(self.events_file, "ab") as f:
                f.write(data)
        except OSError as e:
            raise StoreError(502, f"could not write the review: {e}")
        self._expected += data
        self._stat = self._stat_now()
        self.history.append(events)

    def _check(self):
        """Restore the events file if it changed in a way this store didn't make."""
        if self._stat_now() == self._stat:
            return
        try:
            with open(self.events_file, "rb") as f:
                found = f.read()
        except FileNotFoundError:
            found = None
        if found == self._expected:
            self._stat = self._stat_now()
            return
        ours = set(self._expected.splitlines())
        theirs = set((found or b"").splitlines())
        tids = set()
        for raw in ours ^ theirs:
            try:
                event = json.loads(raw)
                named = [event.get("thread")] + list(event.get("threads") or [])
            except (ValueError, AttributeError, TypeError):
                continue
            tids.update(t for t in named if isinstance(t, str))
        tmp = f"{self.events_file}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(self._expected)
        os.replace(tmp, self.events_file)
        self._stat = self._stat_now()
        self.on_tamper(sorted(tids))

    def _comment(self, thread_id, kind, body):
        self._seq += 1
        return {"id": str(uuid.uuid4()), "author": AUTHOR_OF[kind], "kind": kind, "body": body, "time": now(),
                "seq": self._seq, "stored": kind not in NOTE_KINDS}

    @staticmethod
    def _new_thread(thread_id, anchor):
        return {"id": thread_id, "anchor": anchor, "outdated": False, "status": "open", "comments": []}

    @staticmethod
    def _public_comment(comment):
        return {k: v for k, v in comment.items() if k not in ("seq", "stored")}

    @staticmethod
    def _event(kind, thread_id, comment):
        return dict({k: v for k, v in comment.items() if k != "stored"}, type=kind, thread=thread_id)

    @staticmethod
    def _public(thread):
        return dict(copy.deepcopy(thread), comments=[LocalStore._public_comment(c) for c in thread["comments"]])

    def _find(self, thread_id):
        if thread_id not in self._threads:
            raise StoreError(404, f"no thread {thread_id}")
        return self._threads[thread_id]

    # ── The store port ───────────────────────────────────────────────────────
    def review(self):
        return {k: self.info.get(k) for k in ("id", "branch", "base")}

    def threads(self, status=None):
        with self._lock:
            self._check()
            return [self._public(t) for t in self._threads.values() if status is None or t["status"] == status]

    def open_thread(self, anchor, body):
        anchor = None if anchor is None else dict(anchor, commit=self.commit())
        with self._lock:
            self._check()
            tid = str(uuid.uuid4())
            comment = self._comment(tid, "comment", body)
            self._append([{"type": "opened", "thread": tid, "anchor": anchor, "time": comment["time"]},
                          self._event("comment", tid, comment)])
            self._threads[tid] = self._new_thread(tid, anchor)
            self._threads[tid]["comments"].append(comment)
            return self._public(self._threads[tid])

    def add_comment(self, thread_id, kind, body):
        with self._lock:
            self._check()
            thread = self._find(thread_id)
            comment = self._comment(thread_id, kind, body)
            if comment["stored"]:
                self._append([self._event("comment", thread_id, comment)])
            thread["comments"].append(comment)
            return self._public_comment(comment)

    def edit_note(self, note_id, kind, body, final=False):
        with self._lock:
            self._check()
            for t in self._threads.values():
                for c in t["comments"]:
                    if c["id"] == note_id:
                        c.update(kind=kind, body=body)
                        # A note is stored once it is final; a stored note keeps every edit
                        if final or c["stored"]:
                            c["stored"] = True
                            self._append([self._event("note", t["id"], c)])
                        return self._public_comment(c)
        raise StoreError(404, f"no note {note_id}")

    def record_run(self, run):
        with self._lock:
            self._check()
            self._append([{"type": "run", "run": run["id"], "threads": run["threads"], "sent": run["sent"],
                           "repliesBefore": run["repliesBefore"], "time": now()}])
            self._runs[run["id"]] = dict(copy.deepcopy(run), outcome=None)

    def record_run_end(self, run_id, outcome):
        with self._lock:
            self._check()
            if run_id not in self._runs:
                raise StoreError(404, f"no run {run_id}")
            self._append([{"type": "run-ended", "run": run_id, "outcome": outcome, "time": now()}])
            self._runs[run_id]["outcome"] = outcome

    def runs(self):
        with self._lock:
            self._check()
            return copy.deepcopy(list(self._runs.values()))

    def set_status(self, thread_id, status):
        with self._lock:
            self._check()
            self._find(thread_id)
            self._append([{"type": "status", "thread": thread_id, "status": status, "time": now()}])
            self._threads[thread_id]["status"] = status
        return {"id": thread_id, "status": status}
