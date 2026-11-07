"""Seam: the open_thread use case, with a fake at every driven port.

The memory store keeps the review, a fake code reader stands in for git, and
a fake history keeps what it was asked to record.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import Anchor, Conflict, CouldNotRead, NotAllowed, Review  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402

APP = "def greet(name):\n    return f'hello {name}'\n"
# Line 2 of app.py, as the viewer showed it: the same as the file, or changed since
SHOWN = Anchor("app.py", "new", 2, 2, code="    return f'hello {name}'")
CHANGED_SINCE = Anchor("app.py", "new", 2, 2, code="    return 'hello ' + name")


class OpeningAThread(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({"app.py": APP})
        self.history = FakeHistory()

    def open_a_thread(self, *args):
        return open_thread(self.store, self.code, self.history, *args)

    def test_a_review_rebuilt_from_the_store_holds_the_thread_that_was_opened(self):
        thread = self.open_a_thread("reviewer", "Why an f-string?", SHOWN)

        rebuilt = Review.from_events(self.store.load())

        self.assertEqual(rebuilt.thread(thread.id), thread)
        self.assertEqual(thread.anchor.snapshot_id, "app.py@commit-1")
        self.assertFalse(thread.outdated)

    def test_the_history_records_exactly_the_events_the_store_kept(self):
        self.open_a_thread("reviewer", "Is this ready?")
        self.open_a_thread("reviewer", "Why an f-string?", Anchor("app.py", "new", 2, 2))

        self.assertEqual(len(self.store.load()), 4)
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_thread_whose_code_changed_since_the_viewer_showed_it_is_outdated_at_once(self):
        thread = self.open_a_thread("reviewer", "Why an f-string?", CHANGED_SINCE)

        self.assertTrue(thread.outdated)
        self.assertTrue(Review.from_events(self.store.load()).thread(thread.id).outdated)

    def test_a_general_thread_opens_with_no_anchor(self):
        thread = self.open_a_thread("reviewer", "Is this ready?")

        self.assertIsNone(thread.anchor)
        self.assertFalse(thread.outdated)
        self.assertEqual([c.body for c in thread.comments], ["Is this ready?"])

    def test_anyone_but_a_reviewer_is_not_allowed_and_nothing_is_kept(self):
        with self.assertRaises(NotAllowed):
            self.open_a_thread("agent", "I opened this myself")

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])

    def test_code_that_cannot_be_read_keeps_nothing(self):
        with self.assertRaises(CouldNotRead):
            open_thread(self.store, UnreadableCode(), self.history, "reviewer", "Why?", Anchor("app.py", "new", 2, 2))

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])

    def test_while_another_branch_is_checked_out_it_conflicts_without_reading_the_code(self):
        self.code.checked_out = False

        with self.assertRaises(Conflict):
            self.open_a_thread("reviewer", "Why an f-string?", SHOWN)

        self.assertEqual(self.code.reads, 0)
        self.assertEqual(self.store.load(), [])


if __name__ == "__main__":
    unittest.main()
