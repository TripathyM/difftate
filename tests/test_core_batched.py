"""Seam: the review mode, held threads and Submit (GLOSSARY.md, Review mode),
with a fake at every driven port.

The memory store keeps the review and a fake history keeps what it was asked
to record. The watcher tests show the same through a running watcher; these
show each case of the held rule.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import ModeChanged, NotAllowed, NotesInProgress, Review, ReviewSubmitted  # noqa: E402
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.end_run import end_run  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.read_mode import read_mode  # noqa: E402
from difftate.core.review.use_cases.set_mode import set_mode  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402
from difftate.core.review.use_cases.start_run import start_run  # noqa: E402
from difftate.core.review.use_cases.submit import submit  # noqa: E402


class BatchedTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({})
        self.history = FakeHistory()
        self.notes = NotesInProgress()

    def a_thread(self, body="Is this ready?"):
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", body).thread.id

    def comment(self, tid, body="And the tests?"):
        add_comment(self.store, self.notes, self.history, "reviewer", tid, "comment", body)

    def reply(self, tid, body="Yes."):
        add_comment(self.store, self.notes, self.history, "agent", tid, "reply", body)

    def change_mode(self, mode="batched"):
        return set_mode(self.store, self.notes, self.history, "reviewer", mode)

    def submit(self, author="reviewer"):
        return submit(self.store, self.notes, self.history, author)

    def states(self):
        return {t.thread.id: t.state for t in list_threads(self.store, self.notes, self.code)}

    def thread(self, tid):
        return next(t.thread for t in list_threads(self.store, self.notes, self.code) if t.thread.id == tid)

    def run_on(self, *tids):
        threads = [t.thread for t in list_threads(self.store, self.notes, self.code) if t.thread.id in tids]
        return start_run(self.store, self.notes, self.history, threads)

    def waiting(self):
        return [tid for tid, state in self.states().items() if state == "waiting"]


class ANewReview(BatchedTest):
    def test_is_live_with_nothing_held(self):
        status = read_mode(self.store)

        self.assertEqual((status.mode, status.held), ("live", ()))

    def test_a_comment_waits_for_a_run_as_today(self):
        tid = self.a_thread()

        self.assertEqual(self.states(), {tid: "waiting"})


class ABatchedReview(BatchedTest):
    def test_a_new_comment_makes_its_thread_held_and_nothing_waits_for_a_run(self):
        self.change_mode()

        tid = self.a_thread()

        self.assertEqual(self.states(), {tid: "held"})
        self.assertEqual(read_mode(self.store).held, (tid,))

    def test_a_follow_up_on_a_replied_thread_is_held_too(self):
        tid = self.a_thread()
        self.run_on(tid)
        self.reply(tid)
        end_run(self.store, self.notes, self.history, "done")
        self.change_mode()

        self.comment(tid, "One more thing")

        self.assertEqual(self.states(), {tid: "held"})

    def test_a_comment_written_while_live_that_no_run_has_yet_is_held_too(self):
        tid = self.a_thread()

        self.change_mode()

        self.assertEqual(self.states(), {tid: "held"})

    def test_a_thread_queued_behind_a_run_is_held_with_its_later_comment(self):
        busy, queued = self.a_thread(), self.a_thread("And this?")
        self.run_on(busy)
        self.change_mode()
        self.comment(queued, "One more thing")

        end_run(self.store, self.notes, self.history, "done")

        self.assertEqual(self.states()[queued], "held")
        self.assertEqual(self.submit().submitted, (queued,))
        self.assertEqual(self.run_on(queued).sent, tuple(c.id for c in self.thread(queued).comments))

    def test_submit_makes_every_held_thread_wait_for_one_run_and_names_them(self):
        self.change_mode()
        first, second = self.a_thread(), self.a_thread("And this?")

        status = self.submit()

        self.assertEqual(self.states(), {first: "waiting", second: "waiting"})
        self.assertEqual((status.mode, status.held, status.submitted), ("batched", (), (first, second)))
        run = self.run_on(first, second)
        self.assertEqual(run.threads, (first, second))

    def test_submit_while_a_run_is_busy_queues_the_held_threads(self):
        busy = self.a_thread()
        self.run_on(busy)
        self.change_mode()
        tid = self.a_thread("And this?")

        self.submit()

        self.assertEqual(self.states(), {busy: "working", tid: "queued"})

    def test_submit_with_nothing_held_sends_nothing_and_keeps_nothing(self):
        self.change_mode()
        kept = self.store.load()

        status = self.submit()

        self.assertEqual(status.submitted, ())
        self.assertEqual(self.store.load(), kept)

    def test_a_comment_after_a_submit_is_held_again(self):
        self.change_mode()
        tid = self.a_thread()
        self.submit()
        self.run_on(tid)
        self.reply(tid)
        end_run(self.store, self.notes, self.history, "done")

        self.comment(tid)

        self.assertEqual(self.states(), {tid: "held"})

    def test_changing_to_live_submits_the_held_threads(self):
        self.change_mode()
        tid = self.a_thread()

        status = self.change_mode("live")

        self.assertEqual(self.states(), {tid: "waiting"})
        self.assertEqual((status.mode, status.held, status.submitted), ("live", (), (tid,)))
        kinds = [type(e).__name__ for e in self.store.load()][-2:]
        self.assertEqual(kinds, ["ReviewSubmitted", "ModeChanged"], "the switch is a submit too")

    def test_changing_to_batched_leaves_a_run_in_progress_alone(self):
        tid = self.a_thread()
        self.run_on(tid)

        self.change_mode()

        self.assertEqual(self.states(), {tid: "working"})

    def test_a_follow_up_on_a_thread_a_run_is_working_on_is_held_once_the_run_ends(self):
        tid = self.a_thread()
        self.run_on(tid)
        self.change_mode()
        self.comment(tid)
        self.reply(tid)

        end_run(self.store, self.notes, self.history, "done")

        self.assertEqual(self.states(), {tid: "held"}, "the run's reply was not to the held comment")

    def test_a_reply_on_a_thread_held_with_a_comment_from_before_batched_makes_it_replied(self):
        tid = self.a_thread()
        self.change_mode()
        self.comment(tid)

        self.reply(tid)

        self.assertEqual(self.states(), {tid: "replied"})
        self.assertEqual(self.submit().submitted, ())

    def test_a_reply_on_a_held_thread_makes_it_replied_and_a_later_submit_does_not_send_it(self):
        self.change_mode()
        answered, other = self.a_thread(), self.a_thread("And this?")

        self.reply(answered)

        self.assertEqual(self.states(), {answered: "replied", other: "held"})
        self.assertEqual(self.submit().submitted, (other,))
        self.assertEqual(self.waiting(), [other])

    def test_a_held_thread_resolved_is_not_held(self):
        self.change_mode()
        tid = self.a_thread()

        set_status(self.store, self.notes, self.history, "reviewer", tid, "resolved")

        self.assertEqual(read_mode(self.store).held, ())

    def test_a_thread_resolved_while_held_and_reopened_in_a_live_review_waits(self):
        self.change_mode()
        tid = self.a_thread()
        set_status(self.store, self.notes, self.history, "reviewer", tid, "resolved")
        self.change_mode("live")

        set_status(self.store, self.notes, self.history, "reviewer", tid, "open")

        self.assertEqual(self.states(), {tid: "waiting"})


class TheRules(BatchedTest):
    def test_only_a_reviewer_changes_the_mode_or_submits(self):
        self.change_mode()
        self.a_thread()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    set_mode(self.store, self.notes, self.history, author, "live")
                with self.assertRaises(NotAllowed):
                    self.submit(author)
        self.assertEqual(read_mode(self.store).mode, "batched")
        self.assertEqual(len(read_mode(self.store).held), 1)

    def test_a_mode_that_is_not_one_is_refused(self):
        with self.assertRaises(ValueError):
            self.change_mode("pending")

    def test_the_mode_already_set_keeps_nothing_more(self):
        self.change_mode()
        kept = self.store.load()

        self.change_mode()

        self.assertEqual(self.store.load(), kept)

    def test_each_change_and_submit_is_kept_and_recorded_in_the_review_history_with_the_threads_sent(self):
        self.change_mode()
        tid = self.a_thread()
        self.submit()

        kept = [e for e in self.history.recorded if isinstance(e, (ModeChanged, ReviewSubmitted))]
        self.assertEqual([type(e) for e in kept], [ModeChanged, ReviewSubmitted])
        self.assertEqual((kept[0].mode, kept[1].threads), ("batched", (tid,)))
        self.assertEqual(self.store.load()[-1], kept[1])

    def test_the_review_rebuilt_from_its_events_has_the_same_mode_and_held_threads(self):
        self.change_mode()
        first, second = self.a_thread(), self.a_thread("And this?")
        self.reply(first)

        review = Review.from_events(self.store.load())

        self.assertEqual((review.mode(), [t.id for t in review.held()]), ("batched", [second]))


if __name__ == "__main__":
    unittest.main()
