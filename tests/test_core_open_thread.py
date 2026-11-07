"""Seam: the open_thread use case, with a fake at every driven port.

The memory store keeps the review, a fake code reader stands in for git, and
a fake history keeps what it was asked to record.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.changes.model import Snapshot  # noqa: E402
from difftate.core.review.model import Anchor, CouldNotRead, NotAllowed, Review  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402

APP = "def greet(name):\n    return f'hello {name}'\n"


class FakeCode:
    """The code reader, over files in memory: {file: text}, the same on every
    side and in every view."""

    def __init__(self, files, commit="commit-1"):
        self.files = files
        self.commit = commit

    def snapshot(self, file, side, view, start_line, end_line):
        text = self.files.get(file)
        if text is None:
            return Snapshot(None, self.commit, None)
        lines = text.splitlines()
        code = "\n".join(lines[start_line - 1:end_line]) if end_line <= len(lines) else None
        return Snapshot(f"{file}@{self.commit}", self.commit, code)


class UnreadableCode:
    """A code reader that can't read the code (git failed, say)."""

    def snapshot(self, file, side, view, start_line, end_line):
        raise CouldNotRead(f"could not read {file}")


class FakeHistory:
    """The review history: keeps every event it is asked to record."""

    def __init__(self):
        self.recorded = []

    def record(self, events):
        self.recorded.extend(events)


class OpeningAThread(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({"app.py": APP})
        self.history = FakeHistory()

    def open(self, *args, **kwargs):
        return open_thread(self.store, self.code, self.history, *args, **kwargs)

    def test_a_review_rebuilt_from_the_store_holds_the_thread_that_was_opened(self):
        thread = self.open("Why an f-string?", Anchor("app.py", "new", 2, 2, code="    return f'hello {name}'"))

        rebuilt = Review.from_events(self.store.load())

        self.assertEqual(rebuilt.thread(thread.id), thread)
        self.assertEqual(thread.anchor.snapshot, "app.py@commit-1")
        self.assertFalse(thread.outdated)

    def test_the_history_records_exactly_the_events_the_store_kept(self):
        self.open("Is this ready?")
        self.open("Why an f-string?", Anchor("app.py", "new", 2, 2))

        self.assertEqual(len(self.store.load()), 4)
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_thread_whose_code_changed_since_the_viewer_showed_it_is_outdated_at_once(self):
        thread = self.open("Why an f-string?", Anchor("app.py", "new", 2, 2, code="    return 'hello ' + name"))

        self.assertTrue(thread.outdated)
        self.assertTrue(Review.from_events(self.store.load()).thread(thread.id).outdated)

    def test_a_general_thread_opens_with_no_anchor(self):
        thread = self.open("Is this ready?")

        self.assertIsNone(thread.anchor)
        self.assertFalse(thread.outdated)
        self.assertEqual([c.body for c in thread.comments], ["Is this ready?"])

    def test_anyone_but_a_reviewer_is_not_allowed_and_nothing_is_kept(self):
        with self.assertRaises(NotAllowed):
            self.open("I opened this myself", author="agent")

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])

    def test_code_that_cannot_be_read_keeps_nothing(self):
        with self.assertRaises(CouldNotRead):
            open_thread(self.store, UnreadableCode(), self.history, "Why?", Anchor("app.py", "new", 2, 2))

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])


if __name__ == "__main__":
    unittest.main()
