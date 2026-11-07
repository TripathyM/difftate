"""Seam: today's events.jsonl, rebuilt through the new core (ADR 0004).

A review is written with today's LocalStore: threads, comments, replies,
notes, statuses, moves, outdated threads, runs, an interrupted run and viewed
marks. Its events.jsonl, read back by the local store's line reader and
rebuilt as a Review, gives the same threads, runs and viewed marks as today's
LocalStore reading the same file, and the same thread states as today's Review.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate import review as old_review  # noqa: E402
from difftate.adapters.outbound.local_store.lines import read_events  # noqa: E402
from difftate.core.review.model import Review  # noqa: E402
from difftate.local import History, LocalStore  # noqa: E402

ANCHOR = {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2, "code": "    return f'hello {name}'",
          "snapshot": "a" * 40, "view": "HEAD~1"}
OTHER = {"file": "lib.py", "side": "old", "startLine": 1, "endLine": 3, "code": "import os\n\nX = 1",
         "snapshot": "b" * 40, "view": ""}


class OnTheBranch:
    """Today's code reader, as much of it as today's Review needs to list
    threads and recover runs: the review's branch is checked out."""

    def on_branch(self):
        return True


def write_a_review(store):
    """Every kind of line today's LocalStore writes. Returns the thread ids."""
    moved = store.open_thread(dict(ANCHOR), "Why an f-string?")["id"]
    general = store.open_thread(None, "Is this ready?")["id"]
    outdated = store.open_thread(dict(OTHER), "Why X?")["id"]
    store.move_thread(moved, 5, 5, "c" * 40)
    store.mark_outdated(outdated)
    first = {t["id"]: t["comments"][0]["id"] for t in store.threads()}

    # A run on two threads: one reply, a progress note on each, kept when final
    store.record_run({"id": "run-1", "threads": [moved, general], "sent": [first[moved], first[general]],
                      "repliesBefore": {moved: [], general: []}})
    queued = store.add_comment(outdated, "queued", "⏳ Queued")["id"]  # never final: never stored
    note_moved = store.add_comment(moved, "progress", "Thinking…")["id"]
    note_general = store.add_comment(general, "progress", "Thinking…")["id"]
    store.edit_note(note_moved, "progress", "Read app.py")
    reply = store.add_comment(moved, "reply", "It reads well.")["id"]
    store.edit_note(queued, "queued", "Picked up by the next run")
    store.edit_note(note_moved, "progress", "✅ **Done** in 3s", final=True)
    store.edit_note(note_general, "progress", "❌ **Failed** after 3s — no reply", final=True)
    store.record_run_end("run-1", "done")
    store.set_status(general, "resolved")

    # A run an earlier watcher ended as interrupted
    later = store.add_comment(moved, "comment", "And the tests?")["id"]
    store.record_run({"id": "run-2", "threads": [moved], "sent": [later], "repliesBefore": {moved: [reply]}})
    store.record_run_end("run-2", "interrupted")

    # A run whose watcher was killed: it never ended
    store.set_status(outdated, "dismissed")
    store.set_status(outdated, "open")
    again = store.add_comment(outdated, "comment", "Still?")["id"]
    store.record_run({"id": "run-3", "threads": [outdated], "sent": [first[outdated], again],
                      "repliesBefore": {outdated: []}})

    store.mark_viewed("app.py", "d" * 40)
    store.mark_viewed("lib.py", "e" * 40)
    store.mark_viewed("lib.py", None)
    store.mark_viewed("README.md", "f" * 40)
    store.mark_viewed("app.py", "0" * 40)
    return moved, general, outdated


def as_today(thread):
    """A new-core Thread in today's thread format."""
    anchor = thread.anchor and {"file": thread.anchor.file, "side": thread.anchor.side,
                                "startLine": thread.anchor.start_line, "endLine": thread.anchor.end_line,
                                "code": thread.anchor.code, "snapshot": thread.anchor.snapshot_id,
                                "view": thread.anchor.view, "commit": thread.anchor.commit}
    return {"id": thread.id, "anchor": anchor, "outdated": thread.outdated, "status": thread.status,
            "comments": [{"id": c.id, "author": c.author, "kind": c.kind, "body": c.body, "time": c.time}
                         for c in thread.comments]}


def run_as_today(run):
    return {"id": run.id, "threads": list(run.threads), "sent": list(run.sent),
            "repliesBefore": {tid: list(ids) for tid, ids in run.replies_before.items()}, "outcome": run.outcome}


class TodaysEventsThroughTheNewCore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="difftate-replay-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.folder = os.path.join(tmp, "review")
        self.history = os.path.join(tmp, "history")
        os.makedirs(self.folder)
        self.threads = write_a_review(self.open_today())
        with open(os.path.join(self.folder, "events.jsonl"), encoding="utf-8") as f:
            self.review = Review.from_events(read_events(f.read()))
        self.today = self.open_today()

    def open_today(self):
        """Today's LocalStore over the review's folder, as a restarted watcher
        opens it (with no git: the commit is given)."""
        about = {"repo": {"path": "/repo", "remote": None}, "branch": "feature", "base": "main", "review": "r"}
        store = LocalStore(self.folder, {"id": "r", "branch": "feature", "base": "main"},
                           History(self.history, about), lambda ids: None, lambda: "commit-1")
        store._load()  # what LocalStore.open does after finding the folder
        return store

    def test_the_same_threads_with_their_comments_replies_and_final_notes(self):
        self.assertEqual([as_today(t) for t in self.review.threads()], self.today.threads())
        moved, general, outdated = self.threads
        kinds = [c.kind for c in self.review.thread(moved).comments]
        self.assertEqual(kinds, ["comment", "progress", "reply", "comment"])
        self.assertEqual(self.review.thread(moved).comments[1].body, "✅ **Done** in 3s")
        self.assertEqual([c.kind for c in self.review.thread(outdated).comments], ["comment", "comment"])

    def test_the_same_runs_with_the_interrupted_one_and_the_one_that_never_ended(self):
        self.assertEqual([run_as_today(r) for r in self.review.runs()], self.today.runs())
        self.assertEqual([r.outcome for r in self.review.runs()], ["done", "interrupted", None])

    def test_the_same_viewed_marks(self):
        self.assertEqual(self.review.viewed(), self.today.viewed())
        self.assertEqual(self.review.viewed(), {"app.py": "0" * 40, "README.md": "f" * 40})

    def test_the_same_thread_states_once_the_run_that_never_ended_is_recovered(self):
        today = old_review.Review(self.today, OnTheBranch(), lambda: {})

        today_failed = [t["id"] for t in today.recover_runs()]
        self.review.recover_runs()

        self.assertEqual({t.id: self.review.state(t.id) for t in self.review.threads()},
                         {t["id"]: t["state"] for t in today.threads()})
        moved, general, outdated = self.threads
        self.assertEqual(today_failed, [outdated])
        self.assertEqual([self.review.state(t) for t in self.threads], ["failed", None, "failed"])


if __name__ == "__main__":
    unittest.main()
