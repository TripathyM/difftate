"""Seam: the open_thread use case, with a fake at every driven port.

The memory store keeps the review, a fake code reader stands in for git, and
a fake history keeps what it was asked to record.
"""
import os
import sys
import unittest
from dataclasses import replace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import CodeThatCantKeep, FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.changes.model import FileInView  # noqa: E402
from difftate.core.review.model import Anchor, Conflict, CouldNotRead, NotAllowed, NotesInProgress, Review  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402

BASE = "def greet(name):\n    return 'hi ' + name\n"
APP = "def greet(name):\n    return f'hello {name}'\n"
# Line 2 of app.py, as the viewer showed it: the same as the file, or changed since
SHOWN = Anchor("app.py", "new", 2, 2, code="    return f'hello {name}'")
CHANGED_SINCE = Anchor("app.py", "new", 2, 2, code="    return 'hello ' + name")
NEW_APP = FileInView("app.py", "new")


class OpeningAThread(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({"app.py": APP}, base={"app.py": BASE})
        self.history = FakeHistory()

    def open_a_thread(self, *args):
        return open_thread(self.store, NotesInProgress(), self.code, self.history, *args).thread

    def test_a_review_rebuilt_from_the_store_holds_the_thread_that_was_opened(self):
        thread = self.open_a_thread("reviewer", "Why an f-string?", SHOWN)

        rebuilt = Review.from_events(self.store.load())

        self.assertEqual(rebuilt.thread(thread.id), thread)
        self.assertEqual(thread.anchor.snapshot_id, self.code.versions([FileInView("app.py", "new")])[
            FileInView("app.py", "new")], "the file as it was then")
        self.assertEqual(thread.anchor.commit, "commit-1")
        self.assertFalse(thread.outdated)

    def test_the_history_records_exactly_the_events_the_store_kept(self):
        self.open_a_thread("reviewer", "Is this ready?")
        self.open_a_thread("reviewer", "Why an f-string?", Anchor("app.py", "new", 2, 2))

        self.assertEqual(len(self.store.load()), 4)
        self.assertEqual(self.history.recorded, self.store.load())

    def test_the_code_reader_keeps_the_snapshot_of_each_thread_that_moves_with_its_code(self):
        first = self.open_a_thread("reviewer", "Why an f-string?", SHOWN)
        self.code.files["app.py"] = "import os\n" + APP
        second = self.open_a_thread("reviewer", "Why an f-string here?", Anchor("app.py", "new", 3, 3))
        self.open_a_thread("reviewer", "Is this ready?")

        self.assertEqual(self.code.asked_to_keep, {first.anchor.snapshot_id, second.anchor.snapshot_id})
        self.assertNotEqual(first.anchor.snapshot_id, second.anchor.snapshot_id)

    def test_a_thread_whose_snapshot_cant_be_kept_now_is_opened_all_the_same(self):
        self.code = CodeThatCantKeep({"app.py": APP})

        thread = self.open_a_thread("reviewer", "Why an f-string?", SHOWN)

        self.assertEqual(Review.from_events(self.store.load()).thread(thread.id), thread)

    def test_an_outdated_threads_snapshot_is_kept_too(self):
        thread = self.open_a_thread("reviewer", "Why an f-string?", CHANGED_SINCE)

        self.assertEqual(self.code.asked_to_keep, {thread.anchor.snapshot_id}, "for the review history")

    def test_a_thread_whose_code_changed_since_the_viewer_showed_it_is_outdated_at_once(self):
        thread = self.open_a_thread("reviewer", "Why an f-string?", CHANGED_SINCE)

        self.assertTrue(thread.outdated)
        self.assertTrue(Review.from_events(self.store.load()).thread(thread.id).outdated)

    # ── On the version the viewer showed ─────────────────────────────────────
    def shown(self):
        """The version of app.py the viewer shows now: its id, as the changeset names it."""
        return self.code.changeset("").versions["app.py"].new

    def test_a_thread_on_code_that_only_moved_since_the_viewer_showed_it_moves_with_its_code(self):
        version = self.shown()
        self.code.files["app.py"] = "import os\nimport sys\n" + APP

        thread = self.open_a_thread("reviewer", "Why an f-string?", replace(SHOWN, snapshot_id=version))

        self.assertFalse(thread.outdated)
        self.assertEqual((thread.anchor.start_line, thread.anchor.end_line), (4, 4))
        self.assertEqual(thread.anchor.code, SHOWN.code)
        self.assertEqual(thread.anchor.snapshot_id, self.code.versions([NEW_APP])[NEW_APP], "the file now")
        self.assertEqual(Review.from_events(self.store.load()).thread(thread.id), thread)
        self.assertEqual(self.code.asked_to_keep, {version, thread.anchor.snapshot_id}, "both, for the history")

    def test_a_thread_on_code_that_changed_since_the_viewer_showed_it_is_outdated_on_that_version(self):
        version = self.shown()
        self.code.files["app.py"] = APP.replace("hello", "hi")

        thread = self.open_a_thread("reviewer", "Why an f-string?", replace(SHOWN, snapshot_id=version))

        self.assertTrue(thread.outdated)
        self.assertEqual((thread.anchor.start_line, thread.anchor.snapshot_id), (2, version),
                         "it shows the code it was written on")

    def test_a_change_below_the_code_leaves_the_thread_on_its_lines(self):
        version = self.shown()
        self.code.files["app.py"] = APP + "\nprint(greet('you'))\n"

        thread = self.open_a_thread("reviewer", "Why an f-string?", replace(SHOWN, snapshot_id=version))

        self.assertFalse(thread.outdated)
        self.assertEqual((thread.anchor.start_line, thread.anchor.end_line), (2, 2))

    def test_a_version_the_code_reader_doesnt_have_is_as_if_the_viewer_gave_none(self):
        self.code.files["app.py"] = "import os\nimport sys\n" + APP

        thread = self.open_a_thread("reviewer", "Why an f-string?", replace(SHOWN, snapshot_id="no-such-version"))

        self.assertTrue(thread.outdated, "line 2 of the file now has other code")
        self.assertEqual(thread.anchor.snapshot_id, self.code.versions([NEW_APP])[NEW_APP])

    def test_a_version_without_the_viewers_code_on_those_lines_is_as_if_the_viewer_gave_none(self):
        version = self.shown()

        thread = self.open_a_thread("reviewer", "Why?", replace(CHANGED_SINCE, snapshot_id=version))

        self.assertTrue(thread.outdated)
        self.assertEqual(thread.anchor.code, CHANGED_SINCE.code)

    def test_a_general_thread_opens_with_no_anchor(self):
        thread = self.open_a_thread("reviewer", "Is this ready?")

        self.assertIsNone(thread.anchor)
        self.assertFalse(thread.outdated)
        self.assertEqual([c.body for c in thread.comments], ["Is this ready?"])

    def test_a_thread_opens_waiting_or_queued_while_a_run_works_on_others(self):
        opened = open_thread(self.store, NotesInProgress(), self.code, self.history, "reviewer", "Is this ready?")
        self.assertEqual(opened.state, "waiting")

        self.store.append(Review.from_events(self.store.load()).start_run([opened.thread.id]))
        during = open_thread(self.store, NotesInProgress(), self.code, self.history, "reviewer", "And the docs?")

        self.assertEqual(during.state, "queued")

    def test_anyone_but_a_reviewer_is_not_allowed_and_nothing_is_kept(self):
        with self.assertRaises(NotAllowed):
            self.open_a_thread("agent", "I opened this myself")

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])

    def test_code_that_cannot_be_read_keeps_nothing(self):
        with self.assertRaises(CouldNotRead):
            open_thread(self.store, NotesInProgress(), UnreadableCode(), self.history, "reviewer", "Why?", Anchor("app.py", "new", 2, 2))

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
