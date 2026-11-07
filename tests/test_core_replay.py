"""Seam: a review written before the new core, read through it (ADR 0004).

tests/fixtures/todays-review/ holds a review the old LocalStore (local.py)
wrote: threads, comments, replies, notes kept when final, statuses, moves,
outdated threads, runs, an interrupted run, a run that never ended, and
viewed marks. read-today.json is what the old LocalStore and Review read back
from it. Through the local store, the new core and the review API's thread
format, the same file gives the same threads, runs, viewed marks and thread
states: existing reviews load unchanged.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.inbound.review_api.json_format import thread_json  # noqa: E402
from difftate.adapters.outbound.local_store import LocalStore  # noqa: E402
from difftate.adapters.outbound.local_store.lines import read_events  # noqa: E402
from difftate.core.review.model import ListedThread, NotesInProgress, Review  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.recover_runs import recover_runs  # noqa: E402

TODAYS_REVIEW = os.path.join(ROOT, "tests", "fixtures", "todays-review")


def read_today():
    """What the old LocalStore and Review read back from the review."""
    with open(os.path.join(TODAYS_REVIEW, "read-today.json"), encoding="utf-8") as f:
        return json.load(f)


def copy_of_todays_review(test):
    """The review's folder, copied to a temporary folder the test removes."""
    tmp = tempfile.mkdtemp(prefix="difftate-replay-test-")
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    folder = os.path.join(tmp, "review")
    os.makedirs(folder)
    shutil.copy(os.path.join(TODAYS_REVIEW, "events.jsonl"), folder)
    return folder


def as_stored(thread):
    """A thread in difftate's thread format, as a store kept it: no thread state."""
    return {k: v for k, v in thread.items() if k != "state"}


def run_as_today(run):
    return {"id": run.id, "threads": list(run.threads), "sent": list(run.sent),
            "repliesBefore": {tid: list(ids) for tid, ids in run.replies_before.items()}, "outcome": run.outcome}


class TodaysEventsThroughTheNewCore(unittest.TestCase):
    def setUp(self):
        self.store = LocalStore(copy_of_todays_review(self))
        self.review = Review.from_events(self.store.load())
        self.today = read_today()
        self.code = FakeCode({})  # on the review's branch

    def test_the_same_threads_in_difftates_thread_format(self):
        listed = list_threads(self.store, NotesInProgress(), self.code)

        self.assertEqual([as_stored(thread_json(t)) for t in listed], self.today["threads"])
        moved = self.review.thread(self.today["thread_ids"]["moved"])
        self.assertEqual([c.kind for c in moved.comments], ["comment", "progress", "reply", "comment"])
        self.assertEqual(moved.comments[1].body, "✅ **Done** in 3s")

    def test_the_same_runs_with_the_interrupted_one_and_the_one_that_never_ended(self):
        self.assertEqual([run_as_today(r) for r in self.review.runs()], self.today["runs"])
        self.assertEqual([r.outcome for r in self.review.runs()], ["done", "interrupted", None])

    def test_the_same_viewed_marks(self):
        self.assertEqual(self.review.viewed(), self.today["viewed"])
        self.assertEqual(self.review.viewed(), {"app.py": "0" * 40, "README.md": "f" * 40})

    def test_the_same_thread_states_once_the_run_that_never_ended_is_recovered(self):
        failed = recover_runs(self.store, NotesInProgress(), FakeHistory())

        recovered = self.today["after_recovering_runs"]
        self.assertEqual([t.id for t in failed], recovered["failed"])
        self.assertEqual({t.thread.id: t.state for t in list_threads(self.store, NotesInProgress(), self.code)},
                         recovered["states"])


class AnAnchorFromBeforeViewsAndSnapshots(unittest.TestCase):
    def test_it_loads_written_in_all_changes_with_no_snapshot(self):
        line = ('{"type":"opened","thread":"t1","anchor":{"file":"app.py","side":"new","startLine":2,'
                '"endLine":2,"code":"x = 1","commit":"c1"},"time":"2026-01-01T00:00:00.000Z"}\n')

        [opened] = read_events(line)
        anchor = thread_json(ListedThread(Review.from_events([opened]).thread("t1"), "waiting"))["anchor"]

        # The old API left the two keys out; both viewers read a missing view as ""
        self.assertEqual((anchor["view"], anchor["snapshot"], anchor["commit"]), ("", None, "c1"))


if __name__ == "__main__":
    unittest.main()
