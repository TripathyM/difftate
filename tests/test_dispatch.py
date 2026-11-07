"""Seam: Dispatch on the review's use cases, bound as the watcher binds them,
over the memory store and a fake code reader: what test_watcher.py can't make
happen, such as a store that fails for a while. No coding agent runs.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import CouldNotRead, Review, RunEnded  # noqa: E402
from difftate.dispatch import Dispatch  # noqa: E402
from difftate.watcher import bind_review  # noqa: E402


class StoreThatCannotKeepARunsEnd(MemoryStore):
    """A store that can't write for a while (a full disk, say): the first
    <fails> times it is given a run's end."""

    def __init__(self, fails=1):
        super().__init__()
        self.fails = fails

    def append(self, events):
        if self.fails and any(isinstance(e, RunEnded) for e in events):
            self.fails -= 1
            raise CouldNotRead("could not write the review")
        super().append(events)


class EndingARun(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp(prefix="difftate-dispatch-test-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.store = StoreThatCannotKeepARunsEnd()
        self.review = bind_review(self.store, FakeCode({}), FakeHistory(),
                                  {"id": "r", "branch": "feature", "base": "main"})
        self.dispatch = Dispatch(self.review, agent=None, cwd=folder, review_folder=folder, interval=0.01, api=None,
                                 between_runs=lambda: None)
        # A run on one thread, which the coding agent didn't reply to
        self.tid = self.review.open_thread("reviewer", "Is this ready?").thread.id
        self.review.start_run([t.thread for t in self.review.list_threads()])
        self.dispatch.started = time.time()

    def states(self):
        return [t.state for t in self.review.list_threads()]

    def test_an_end_the_store_could_not_keep_is_kept_before_the_next_run_starts(self):
        out = StringIO()
        with redirect_stdout(out):
            self.dispatch.end_run()
            self.assertEqual(self.states(), ["working"], "the run is still in progress in the review")

            self.dispatch.once()

        self.assertEqual(self.states(), ["failed"])
        self.assertEqual([r.outcome for r in Review.from_events(self.store.load()).runs()], ["done"])
        self.assertIn("could not record the end of the run (could not write the review)", out.getvalue())
        self.assertIn(f"No reply to thread {self.tid[:8]}", out.getvalue())

    def test_a_store_that_keeps_failing_is_warned_about_once(self):
        self.store.fails = 3
        out = StringIO()
        with redirect_stdout(out):
            self.dispatch.end_run()
            self.dispatch.once()
            self.dispatch.once()

        self.assertEqual(out.getvalue().count("could not record the end of the run"), 1)
        self.assertEqual(self.states(), ["working"])


if __name__ == "__main__":
    unittest.main()
