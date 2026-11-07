"""Seam: the Review's use cases for reviewing, with a fake at every driven port.

The memory store keeps the review, a fake code reader stands in for git, and
a fake history keeps what it was asked to record. Each use case rebuilds the
Review from the store, so a test sets the review up through the use cases.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import Conflict, CouldNotRead, NotAllowed, NotFound, Review  # noqa: E402
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.list_viewed import list_viewed  # noqa: E402
from difftate.core.review.use_cases.mark_viewed import mark_viewed  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402


class UseCaseTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({}, diff_hashes={"app.py": "hash-1", "lib.py": "hash-2"})
        self.history = FakeHistory()

    def a_thread(self, body="Is this ready?"):
        return open_thread(self.store, self.code, self.history, "reviewer", body).id

    def rebuilt(self):
        return Review.from_events(self.store.load())


class AddingAComment(UseCaseTest):
    def test_a_reply_is_kept_and_recorded_in_the_review_history(self):
        tid = self.a_thread()

        reply = add_comment(self.store, self.history, "agent", tid, "reply", "It is ready.")

        self.assertEqual(self.rebuilt().thread(tid).comments[-1], reply)
        self.assertEqual((reply.author, reply.kind, reply.body), ("agent", "reply", "It is ready."))
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_note_is_kept_for_this_process_but_not_recorded_until_it_is_final(self):
        tid = self.a_thread()
        recorded = list(self.history.recorded)

        note = add_comment(self.store, self.history, "difftate", tid, "progress", "Thinking…")

        self.assertEqual(self.rebuilt().thread(tid).comments[-1], note)
        self.assertEqual(self.history.recorded, recorded)

    def test_a_reply_written_by_anyone_but_the_coding_agent_is_not_allowed_and_nothing_is_kept(self):
        tid = self.a_thread()
        kept, recorded = self.store.load(), list(self.history.recorded)

        for author in ("reviewer", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    add_comment(self.store, self.history, author, tid, "reply", "A reply in disguise")

        self.assertEqual((self.store.load(), self.history.recorded), (kept, recorded))

    def test_a_comment_on_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            add_comment(self.store, self.history, "agent", "no-such-thread", "reply", "Hello?")


class SettingAThreadStatus(UseCaseTest):
    def test_a_reviewer_resolves_a_thread_and_it_stays_resolved(self):
        tid = self.a_thread()

        thread = set_status(self.store, self.history, "reviewer", tid, "resolved")

        self.assertEqual(thread.status, "resolved")
        self.assertEqual(self.rebuilt().thread(tid).status, "resolved")
        self.assertEqual(self.history.recorded, self.store.load())

    def test_anyone_but_a_reviewer_is_not_allowed_and_nothing_is_kept(self):
        tid = self.a_thread()
        kept = self.store.load()

        with self.assertRaises(NotAllowed):
            set_status(self.store, self.history, "agent", tid, "resolved")

        self.assertEqual(self.store.load(), kept)


class ListingThreads(UseCaseTest):
    def test_each_thread_comes_with_its_thread_state_and_can_be_listed_by_status(self):
        replied, waiting = self.a_thread(), self.a_thread("And the docs?")
        review = self.rebuilt()
        self.store.append(review.start_run([replied]))
        add_comment(self.store, self.history, "agent", replied, "reply", "It is ready.")
        self.store.append(self.rebuilt().end_run("done"))
        resolved = self.a_thread("And the tests?")
        set_status(self.store, self.history, "reviewer", resolved, "resolved")

        self.assertEqual([(t.id, state) for t, state in list_threads(self.store)],
                         [(replied, "replied"), (waiting, "waiting"), (resolved, None)])
        self.assertEqual([t.id for t, _ in list_threads(self.store, "open")], [replied, waiting])
        self.assertEqual([t.id for t, _ in list_threads(self.store, "resolved")], [resolved])


class MarkingAFileViewed(UseCaseTest):
    def test_a_viewed_file_is_kept_and_recorded_and_the_files_viewed_come_back(self):
        self.assertEqual(mark_viewed(self.store, self.code, self.history, "lib.py"), ["lib.py"])
        self.assertEqual(mark_viewed(self.store, self.code, self.history, "app.py"), ["app.py", "lib.py"])
        self.assertEqual(mark_viewed(self.store, self.code, self.history, "lib.py", False), ["app.py"])

        self.assertEqual(self.rebuilt().viewed(), {"app.py": "hash-1"})
        self.assertEqual(self.history.recorded, self.store.load())

    def test_marking_a_file_clears_the_marks_whose_diff_changed(self):
        mark_viewed(self.store, self.code, self.history, "app.py")
        self.code.hashes["app.py"] = "hash-3"

        self.assertEqual(mark_viewed(self.store, self.code, self.history, "lib.py"), ["lib.py"])
        self.assertEqual(self.rebuilt().viewed(), {"lib.py": "hash-2"})

    def test_a_file_that_is_not_in_the_changeset_is_not_found(self):
        with self.assertRaises(NotFound):
            mark_viewed(self.store, self.code, self.history, "gone.py")

    def test_while_another_branch_is_checked_out_it_conflicts_without_reading_the_code(self):
        self.code.checked_out = False

        with self.assertRaises(Conflict):
            mark_viewed(self.store, self.code, self.history, "app.py")

        self.assertEqual((self.code.reads, self.store.load()), (0, []))

    def test_a_changeset_that_cannot_be_read_keeps_nothing(self):
        with self.assertRaises(CouldNotRead):
            mark_viewed(self.store, UnreadableCode(), self.history, "app.py")

        self.assertEqual(self.store.load(), [])


class ListingViewedFiles(UseCaseTest):
    def test_a_file_whose_diff_changed_is_no_longer_viewed_even_when_the_change_is_undone(self):
        mark_viewed(self.store, self.code, self.history, "app.py")
        mark_viewed(self.store, self.code, self.history, "lib.py")
        self.code.hashes["app.py"] = "hash-3"

        self.assertEqual(list_viewed(self.store, self.code, self.history), ["lib.py"])
        self.code.hashes["app.py"] = "hash-1"
        self.assertEqual(list_viewed(self.store, self.code, self.history), ["lib.py"])
        self.assertEqual(self.history.recorded, self.store.load())

    def test_nothing_is_kept_when_no_mark_changed(self):
        mark_viewed(self.store, self.code, self.history, "app.py")
        kept = self.store.load()

        self.assertEqual(list_viewed(self.store, self.code, self.history), ["app.py"])
        self.assertEqual(self.store.load(), kept)

    def test_while_another_branch_is_checked_out_the_marks_stay_and_the_code_is_not_read(self):
        mark_viewed(self.store, self.code, self.history, "app.py")
        self.code.checked_out, self.code.hashes, self.code.reads = False, {}, 0

        self.assertEqual(list_viewed(self.store, self.code, self.history), ["app.py"])
        self.assertEqual(self.code.reads, 0)
        self.code.checked_out = True
        self.assertEqual(list_viewed(self.store, self.code, self.history), [])


if __name__ == "__main__":
    unittest.main()
