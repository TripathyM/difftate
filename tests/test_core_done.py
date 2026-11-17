"""Seam: marking a review Done (GLOSSARY.md, Done), with a fake at every
driven port.

The memory store keeps the review, a fake code reader says which commit the
branch is at (its `commit`), and a fake history keeps what it was asked to
record. A new commit is `code.commit = "commit-2"`.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import (  # noqa: E402
    Conflict, CouldNotRead, DoneCleared, DoneMarked, DoneUndone, NotAllowed, NotesInProgress, Review,
)
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.clear_done import clear_done  # noqa: E402
from difftate.core.review.use_cases.end_run import end_run  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.read_done import read_done  # noqa: E402
from difftate.core.review.use_cases.set_done import set_done  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402
from difftate.core.review.use_cases.start_run import start_run  # noqa: E402


class DoneTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({}, commit="commit-1")
        self.history = FakeHistory()
        self.notes = NotesInProgress()

    def a_thread(self, body="Is this ready?"):
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", body).thread.id

    def mark(self, author="reviewer"):
        return set_done(self.store, self.code, self.history, author, True)

    def undo(self, author="reviewer"):
        return set_done(self.store, self.code, self.history, author, False)

    def commit(self):
        """A new commit on the branch."""
        self.code.commit += "+"

    def kinds(self):
        return [type(e).__name__ for e in self.store.load() if type(e) in (DoneMarked, DoneUndone, DoneCleared)]


class MarkingDone(DoneTest):
    def test_the_reviewer_marks_the_review_done_at_the_commit_the_branch_is_at(self):
        status = self.mark()

        self.assertTrue(status.done)
        self.assertEqual((status.mark.kind, status.mark.commit), ("done", "commit-1"))
        self.assertEqual(status.last_mark, status.mark)
        self.assertEqual(status.head, "commit-1")
        self.assertRegex(status.mark.time, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

    def test_the_mark_is_kept_and_recorded_in_the_review_history(self):
        self.mark()

        [event] = self.store.load()
        self.assertEqual((type(event), event.commit), (DoneMarked, "commit-1"))
        self.assertEqual(self.history.recorded, [event])
        self.assertTrue(Review.from_events(self.store.load()).done())

    def test_a_review_is_not_done_until_a_reviewer_marks_it(self):
        status = read_done(self.store, self.code)

        self.assertEqual((status.done, status.mark, status.last_mark), (False, None, None))

    def test_marking_a_review_that_is_done_at_this_commit_keeps_nothing_more(self):
        self.mark()
        kept = self.store.load()

        status = self.mark()

        self.assertTrue(status.done)
        self.assertEqual(self.store.load(), kept)
        self.assertEqual(self.history.recorded, kept)

    def test_only_a_reviewer_marks_it_and_nothing_is_kept(self):
        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    self.mark(author)
        self.assertEqual((self.store.load(), self.history.recorded), ([], []))

    def test_while_another_branch_is_checked_out_it_conflicts_and_keeps_nothing(self):
        self.code.checked_out = False

        with self.assertRaises(Conflict):
            self.mark()

        self.assertEqual((self.store.load(), self.history.recorded), ([], []))

    def test_a_branch_the_repository_does_not_have_has_no_commit_to_be_done_at(self):
        self.code.commit = None

        with self.assertRaises(CouldNotRead):
            self.mark()

        self.assertEqual(self.store.load(), [])

    def test_open_threads_do_not_stop_it(self):
        self.a_thread()

        status = self.mark()

        self.assertTrue(status.done)


class UndoingDone(DoneTest):
    def test_the_reviewer_undoes_it_and_the_undo_is_kept_with_the_commit_it_was_done_at(self):
        self.mark()

        status = self.undo()

        self.assertFalse(status.done)
        self.assertEqual((status.mark, status.last_mark.kind, status.last_mark.commit), (None, "undone", "commit-1"))
        self.assertEqual(self.kinds(), ["DoneMarked", "DoneUndone"])
        self.assertEqual(self.history.recorded, self.store.load())

    def test_it_can_be_marked_again_after_an_undo(self):
        self.mark()
        self.undo()

        status = self.mark()

        self.assertEqual((status.done, status.last_mark.kind), (True, "done"))
        self.assertEqual(self.kinds(), ["DoneMarked", "DoneUndone", "DoneMarked"])

    def test_undoing_a_review_that_is_not_done_keeps_nothing(self):
        self.undo()
        self.assertEqual(self.store.load(), [])

        self.mark()
        self.undo()
        kept = self.store.load()
        self.undo()

        self.assertEqual(self.store.load(), kept)

    def test_only_a_reviewer_undoes_it(self):
        self.mark()
        kept = self.store.load()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    self.undo(author)

        self.assertEqual(self.store.load(), kept)
        self.assertTrue(read_done(self.store, self.code).done)


class ANewCommit(DoneTest):
    def test_it_clears_done_and_the_clearing_is_kept_with_the_new_commit(self):
        self.mark()
        self.commit()

        self.assertTrue(clear_done(self.store, self.code, self.history))

        status = read_done(self.store, self.code)
        self.assertEqual((status.done, status.mark), (False, None))
        self.assertEqual((status.last_mark.kind, status.last_mark.commit), ("cleared", "commit-1+"))
        self.assertEqual(self.kinds(), ["DoneMarked", "DoneCleared"])
        self.assertEqual(self.history.recorded, self.store.load())

    def test_it_is_cleared_once(self):
        self.mark()
        self.commit()
        clear_done(self.store, self.code, self.history)
        kept = self.store.load()

        self.assertFalse(clear_done(self.store, self.code, self.history))

        self.assertEqual(self.store.load(), kept)

    def test_with_no_new_commit_nothing_is_cleared(self):
        self.mark()
        kept = self.store.load()

        self.assertFalse(clear_done(self.store, self.code, self.history))

        self.assertEqual(self.store.load(), kept)
        self.assertTrue(read_done(self.store, self.code).done)

    def test_a_review_that_is_not_done_has_nothing_to_clear(self):
        self.commit()

        self.assertFalse(clear_done(self.store, self.code, self.history))

        self.assertEqual(self.store.load(), [])

    def test_a_branch_the_repository_no_longer_has_keeps_its_done(self):
        self.mark()
        self.code.commit = None  # merged and deleted

        self.assertFalse(clear_done(self.store, self.code, self.history))

        status = read_done(self.store, self.code)
        self.assertEqual((status.done, status.mark.commit, status.head), (True, "commit-1", None))

    def test_reading_done_after_a_new_commit_says_so_without_keeping_anything(self):
        self.mark()
        self.commit()
        kept = self.store.load()

        status = read_done(self.store, self.code)

        self.assertEqual((status.done, status.mark), (False, None))
        self.assertEqual((status.last_mark.kind, status.last_mark.commit), ("cleared", "commit-1+"))
        self.assertEqual(self.store.load(), kept)
        self.assertEqual(self.history.recorded, kept)

    def test_it_clears_done_even_while_another_branch_is_checked_out(self):
        self.mark()
        self.commit()
        self.code.checked_out = False

        self.assertTrue(clear_done(self.store, self.code, self.history))

    def test_undoing_after_a_new_commit_is_a_clearing_not_an_undo(self):
        self.mark()
        self.commit()

        status = self.undo()

        self.assertEqual((status.done, status.last_mark.kind), (False, "cleared"))
        self.assertEqual(self.kinds(), ["DoneMarked", "DoneCleared"])

    def test_marking_again_after_a_new_commit_keeps_the_clearing_then_the_new_mark(self):
        self.mark()
        self.commit()

        status = self.mark()

        self.assertEqual((status.done, status.mark.commit), (True, "commit-1+"))
        self.assertEqual(self.kinds(), ["DoneMarked", "DoneCleared", "DoneMarked"])

    def test_a_new_thread_a_comment_or_a_status_change_do_not_clear_done(self):
        tid = self.a_thread()
        self.mark()

        late = self.a_thread("One more thing")
        add_comment(self.store, self.notes, self.history, "reviewer", late, "comment", "And this?")
        set_status(self.store, self.notes, self.history, "reviewer", tid, "resolved")
        clear_done(self.store, self.code, self.history)

        status = read_done(self.store, self.code)
        self.assertEqual((status.done, status.mark.commit), (True, "commit-1"))
        self.assertEqual(self.kinds(), ["DoneMarked"])


class TheMarksInReviewHistory(DoneTest):
    def test_every_mark_is_kept_in_order_each_with_its_time_and_commit(self):
        self.mark()
        self.undo()
        self.mark()
        self.commit()
        clear_done(self.store, self.code, self.history)
        self.mark()

        marks = [e for e in self.history.recorded if type(e) in (DoneMarked, DoneUndone, DoneCleared)]
        self.assertEqual([(type(e).__name__, e.commit) for e in marks], [
            ("DoneMarked", "commit-1"), ("DoneUndone", "commit-1"), ("DoneMarked", "commit-1"),
            ("DoneCleared", "commit-1+"), ("DoneMarked", "commit-1+")])
        self.assertTrue(all(e.time for e in marks))
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_review_rebuilt_from_the_marks_is_as_it_was(self):
        self.mark()
        self.undo()
        self.mark()

        rebuilt = Review.from_events(self.store.load())

        self.assertEqual(rebuilt.done().commit, "commit-1")
        self.assertEqual(rebuilt.last_done_mark().kind, "done")


class TheOpenThreadCount(DoneTest):
    def test_each_open_thread_is_counted_and_a_resolved_or_dismissed_one_is_not(self):
        self.a_thread()
        resolved, dismissed = self.a_thread(), self.a_thread()
        set_status(self.store, self.notes, self.history, "reviewer", resolved, "resolved")
        set_status(self.store, self.notes, self.history, "reviewer", dismissed, "dismissed")

        status = read_done(self.store, self.code)

        # A waiting thread is open, and no run has it yet
        self.assertEqual((status.open_threads, status.in_flight), (1, 0))

    def test_no_threads_is_none_open(self):
        status = read_done(self.store, self.code)

        self.assertEqual((status.open_threads, status.in_flight), (0, 0))

    def test_an_open_thread_with_a_run_working_or_queued_is_counted_apart_but_still_open(self):
        working, queued = self.a_thread(), self.a_thread()
        review = Review.from_events(self.store.load())
        start_run(self.store, self.notes, self.history, [review.thread(working)])

        status = read_done(self.store, self.code)

        self.assertEqual(Review.from_events(self.store.load()).state(working), "working")
        self.assertEqual(Review.from_events(self.store.load()).state(queued), "queued")
        self.assertEqual((status.open_threads, status.in_flight), (2, 2))

    def test_a_thread_the_agent_replied_to_is_open_but_not_in_flight(self):
        tid = self.a_thread()
        review = Review.from_events(self.store.load())
        start_run(self.store, self.notes, self.history, [review.thread(tid)])
        add_comment(self.store, self.notes, self.history, "agent", tid, "reply", "Yes.")
        end_run(self.store, self.notes, self.history, "done")

        status = read_done(self.store, self.code)

        self.assertEqual((status.open_threads, status.in_flight), (1, 0))

    def test_the_count_is_there_whether_or_not_it_is_done(self):
        self.a_thread()
        self.mark()

        self.assertEqual(read_done(self.store, self.code).open_threads, 1)


if __name__ == "__main__":
    unittest.main()
