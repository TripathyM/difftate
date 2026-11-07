"""Seam: the Review, the aggregate root of the core (ADR 0004).

Plain calls, no fakes: the Review checks the rules and returns events, and
applying an event is the only way its state changes.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.core.changes.model import Snapshot  # noqa: E402
from difftate.core.review.model import (  # noqa: E402
    Anchor, CommentAdded, Conflict, FileViewed, NotAllowed, NotFound, NoteWritten, Review, Run, RunEnded, RunStarted,
    ThreadMoved, ThreadOpened, ThreadOutdated, lasting,
)

# Line 2 of app.py on the new side, as the viewer showed it
SHOWN = Anchor("app.py", "new", 2, 2, code="    return f'hello {name}'", view="HEAD~1")


class OpeningAThread(unittest.TestCase):
    def test_a_reviewer_opens_a_general_thread_with_their_comment(self):
        review = Review()

        events = review.open_thread("reviewer", "Is this ready?")

        self.assertEqual([type(e) for e in events], [ThreadOpened, CommentAdded])
        thread = review.thread(events[0].thread_id)
        self.assertIsNone(thread.anchor)
        self.assertEqual(thread.status, "open")
        self.assertFalse(thread.outdated)
        self.assertEqual([(c.author, c.kind, c.body) for c in thread.comments],
                         [("reviewer", "comment", "Is this ready?")])

    def test_anyone_but_a_reviewer_is_not_allowed_to_open_a_thread(self):
        review = Review()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    review.open_thread(author, "I opened this myself")

    def test_a_thread_on_code_that_is_still_there_keeps_its_snapshot_and_is_not_outdated(self):
        review = Review()
        snapshot = Snapshot("blob-1", "commit-1", "    return f'hello {name}'")

        events = review.open_thread("reviewer", "Why an f-string?", SHOWN, snapshot)

        thread = review.thread(events[0].thread_id)
        self.assertEqual(thread.anchor, Anchor("app.py", "new", 2, 2, code="    return f'hello {name}'",
                                               view="HEAD~1", snapshot_id="blob-1", commit="commit-1"))
        self.assertFalse(thread.outdated)

    def test_a_thread_whose_code_changed_since_the_viewer_showed_it_is_outdated_at_once(self):
        review = Review()
        snapshot = Snapshot("blob-2", "commit-1", "    return 'hello ' + name")

        events = review.open_thread("reviewer", "Why an f-string?", SHOWN, snapshot)

        self.assertEqual([type(e) for e in events], [ThreadOpened, CommentAdded, ThreadOutdated])
        thread = review.thread(events[0].thread_id)
        self.assertTrue(thread.outdated)
        self.assertEqual(thread.anchor.code, "    return f'hello {name}'")  # the code it was written on

    def test_a_thread_whose_viewer_sent_no_code_is_written_on_the_code_there_now(self):
        review = Review()
        snapshot = Snapshot("blob-1", "commit-1", "    return f'hello {name}'")

        events = review.open_thread("reviewer", "Why an f-string?", Anchor("app.py", "new", 2, 2), snapshot)

        thread = review.thread(events[0].thread_id)
        self.assertEqual(thread.anchor.code, "    return f'hello {name}'")
        self.assertFalse(thread.outdated)

    def test_a_thread_on_lines_that_are_gone_is_outdated_at_once(self):
        for gone in (Snapshot(None, "commit-1", None), Snapshot("blob-1", "commit-1", None)):
            with self.subTest(gone=gone):
                review = Review()

                events = review.open_thread("reviewer", "Why an f-string?", SHOWN, gone)

                self.assertTrue(review.thread(events[0].thread_id).outdated)


def a_review_with_a_thread():
    """A Review with one general thread, and that thread's id."""
    review = Review()
    events = review.open_thread("reviewer", "Is this ready?")
    return review, events[0].thread_id


class WritingInAThread(unittest.TestCase):
    """Rule 2: each author writes only their own kind. A reviewer writes
    comments, the coding agent writes replies, difftate writes notes."""

    def test_each_author_writes_their_own_kind_and_it_goes_at_the_end_of_the_thread(self):
        review, tid = a_review_with_a_thread()

        review.add_comment("agent", tid, "reply", "It is ready.")
        review.add_comment("difftate", tid, "progress", "Thinking…")
        review.add_comment("reviewer", tid, "comment", "And the tests?")

        self.assertEqual([(c.author, c.kind, c.body) for c in review.thread(tid).comments],
                         [("reviewer", "comment", "Is this ready?"), ("agent", "reply", "It is ready."),
                          ("difftate", "progress", "Thinking…"), ("reviewer", "comment", "And the tests?")])

    def test_a_reply_or_comment_is_added_and_a_note_is_written_not_final(self):
        review, tid = a_review_with_a_thread()

        [reply] = review.add_comment("agent", tid, "reply", "It is ready.")
        [note] = review.add_comment("difftate", tid, "queued", "Queued")

        self.assertIsInstance(reply, CommentAdded)
        self.assertIsInstance(note, NoteWritten)
        self.assertFalse(note.final)

    def test_no_author_writes_another_authors_kind(self):
        review, tid = a_review_with_a_thread()

        for author, kind in (("agent", "comment"), ("agent", "progress"), ("reviewer", "reply"),
                             ("reviewer", "queued"), ("difftate", "reply"), ("difftate", "comment"),
                             ("agent", "no-such-kind")):
            with self.subTest(author=author, kind=kind):
                with self.assertRaises(NotAllowed):
                    review.add_comment(author, tid, kind, "Not mine to write")
        self.assertEqual(len(review.thread(tid).comments), 1)

    def test_a_comment_on_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            Review().add_comment("agent", "no-such-thread", "reply", "Hello?")

    def test_each_comment_has_its_place_in_the_review_in_the_order_it_was_written(self):
        review, first = a_review_with_a_thread()
        second = review.open_thread("reviewer", "And the docs?")[0].thread_id

        review.add_comment("agent", first, "reply", "Yes.")
        review.add_comment("agent", second, "reply", "Done.")

        self.assertEqual([c.seq for c in review.thread(first).comments], [1, 3])
        self.assertEqual([c.seq for c in review.thread(second).comments], [2, 4])


class EditingANote(unittest.TestCase):
    """Rule 3: only difftate writes notes, and only notes can be edited. A
    final note doesn't change again."""

    def setUp(self):
        self.review, self.tid = a_review_with_a_thread()
        [written] = self.review.add_comment("difftate", self.tid, "queued", "Queued")
        self.note = written.comment

    def test_difftate_edits_a_note_in_its_place_and_may_change_its_kind(self):
        self.review.add_comment("agent", self.tid, "reply", "A reply after the note")

        [edited] = self.review.edit_note("difftate", self.note.id, "progress", "Thinking…")

        self.assertFalse(edited.final)
        comments = self.review.thread(self.tid).comments
        self.assertEqual([(c.kind, c.body) for c in comments],
                         [("comment", "Is this ready?"), ("progress", "Thinking…"), ("reply", "A reply after the note")])
        self.assertEqual((comments[1].id, comments[1].seq, comments[1].time),
                         (self.note.id, self.note.seq, self.note.time))

    def test_only_difftate_edits_a_note(self):
        for author in ("reviewer", "agent"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    self.review.edit_note(author, self.note.id, "progress", "Mine now")

    def test_a_comment_or_reply_is_not_a_note_and_cannot_be_edited(self):
        [reply] = self.review.add_comment("agent", self.tid, "reply", "It is ready.")
        comment = self.review.thread(self.tid).comments[0]

        for cid in (comment.id, reply.comment.id):
            with self.subTest(cid=cid):
                with self.assertRaises(NotAllowed):
                    self.review.edit_note("difftate", cid, "progress", "Overwritten")

    def test_a_note_does_not_become_a_comment_or_reply(self):
        for kind in ("comment", "reply"):
            with self.subTest(kind=kind):
                with self.assertRaises(NotAllowed):
                    self.review.edit_note("difftate", self.note.id, kind, "Now a reply")

    def test_a_note_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            self.review.edit_note("difftate", "no-such-note", "progress", "Hello?")

    def test_a_final_note_does_not_change_again(self):
        [final] = self.review.edit_note("difftate", self.note.id, "progress", "✅ Done in 3s", final=True)

        self.assertTrue(final.final)
        for again_final in (False, True):
            with self.subTest(final=again_final):
                with self.assertRaises(Conflict):
                    self.review.edit_note("difftate", self.note.id, "progress", "Thinking…", final=again_final)
        self.assertEqual(self.review.thread(self.tid).comments[1].body, "✅ Done in 3s")

    def test_a_note_rebuilt_from_its_final_event_alone_is_final_and_keeps_its_place(self):
        review = Review()
        events = review.open_thread("reviewer", "Is this ready?")
        tid = events[0].thread_id
        events += review.add_comment("difftate", tid, "progress", "Thinking…")
        note = events[-1].comment
        events += review.add_comment("agent", tid, "reply", "After the note")
        events += review.edit_note("difftate", note.id, "progress", "✅ Done", final=True)
        # A store keeps a note only once it is final: the events before that are gone
        kept = [e for e in events if not isinstance(e, NoteWritten) or e.final]

        rebuilt = Review.from_events(kept)

        self.assertEqual([(c.kind, c.body) for c in rebuilt.thread(tid).comments],
                         [("comment", "Is this ready?"), ("progress", "✅ Done"), ("reply", "After the note")])
        with self.assertRaises(Conflict):
            rebuilt.edit_note("difftate", note.id, "progress", "Thinking…")


class ChangingAThreadStatus(unittest.TestCase):
    """Rule 1: only a reviewer changes a thread's status."""

    def test_a_reviewer_resolves_dismisses_and_reopens_a_thread(self):
        review, tid = a_review_with_a_thread()

        for status in ("resolved", "dismissed", "open"):
            with self.subTest(status=status):
                review.set_status("reviewer", tid, status)
                self.assertEqual(review.thread(tid).status, status)

    def test_the_threads_can_be_listed_by_status(self):
        review, first = a_review_with_a_thread()
        second = review.open_thread("reviewer", "And the docs?")[0].thread_id
        review.set_status("reviewer", first, "resolved")

        self.assertEqual([t.id for t in review.threads()], [first, second])
        self.assertEqual([t.id for t in review.threads("open")], [second])
        self.assertEqual([t.id for t in review.threads("resolved")], [first])

    def test_anyone_but_a_reviewer_is_not_allowed_to_change_a_thread_status(self):
        review, tid = a_review_with_a_thread()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    review.set_status(author, tid, "resolved")
        self.assertEqual(review.thread(tid).status, "open")

    def test_the_status_of_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            Review().set_status("reviewer", "no-such-thread", "resolved")


class TheThreadState(unittest.TestCase):
    """Rule 4: one rule gives the thread state, from the runs and the replies."""

    def test_a_thread_whose_comment_no_run_was_sent_is_waiting(self):
        review, tid = a_review_with_a_thread()

        self.assertEqual(review.state(tid), "waiting")
        self.assertEqual(review.unsent(tid), [review.thread(tid).comments[0].id])

    def test_a_run_works_on_its_threads_while_other_waiting_threads_are_queued(self):
        review, sent = a_review_with_a_thread()
        review.start_run([sent])
        later = review.open_thread("reviewer", "And the docs?")[0].thread_id

        self.assertEqual(review.state(sent), "working")
        self.assertEqual(review.state(later), "queued")
        self.assertEqual(review.unsent(sent), [])

    def test_a_thread_the_coding_agent_replied_to_in_its_run_is_replied(self):
        review, tid = a_review_with_a_thread()
        review.start_run([tid])
        review.add_comment("agent", tid, "reply", "It is ready.")
        review.end_run("done")

        self.assertEqual(review.state(tid), "replied")

    def test_a_thread_its_run_did_not_reply_to_is_failed(self):
        review, tid = a_review_with_a_thread()
        review.start_run([tid])
        review.end_run("failed")

        self.assertEqual(review.state(tid), "failed")

    def test_a_reply_to_an_earlier_comment_does_not_answer_a_later_one(self):
        review, tid = a_review_with_a_thread()
        review.start_run([tid])
        review.add_comment("agent", tid, "reply", "It is ready.")
        review.end_run("done")
        review.add_comment("reviewer", tid, "comment", "And the tests?")
        self.assertEqual(review.state(tid), "waiting")

        review.start_run([tid])
        review.end_run("done")

        self.assertEqual(review.state(tid), "failed")

    def test_a_resolved_or_dismissed_thread_has_no_thread_state(self):
        review, tid = a_review_with_a_thread()

        for status in ("resolved", "dismissed"):
            with self.subTest(status=status):
                review.set_status("reviewer", tid, status)
                self.assertIsNone(review.state(tid))


class Runs(unittest.TestCase):
    def test_a_run_keeps_the_comments_it_was_sent_and_the_replies_its_threads_had(self):
        review, tid = a_review_with_a_thread()
        review.start_run([tid])
        reply = review.add_comment("agent", tid, "reply", "It is ready.")[0].comment
        review.end_run("done")
        review.add_comment("reviewer", tid, "comment", "And the tests?")
        comments = review.thread(tid).comments

        [started] = review.start_run([tid])

        self.assertIsInstance(started, RunStarted)
        self.assertEqual(review.runs()[-1], Run(started.run_id, (tid,), (comments[2].id,), {tid: (reply.id,)}, None))
        self.assertEqual(review.runs()[0].sent, (comments[0].id,))
        self.assertEqual(review.runs()[0].outcome, "done")

    def test_ending_a_run_ends_the_run_in_progress_and_nothing_when_there_is_none(self):
        review, tid = a_review_with_a_thread()
        [started] = review.start_run([tid])

        [ended] = review.end_run("stopped")

        self.assertEqual((type(ended), ended.run_id, ended.outcome), (RunEnded, started.run_id, "stopped"))
        self.assertEqual(review.end_run("done"), [])

    def test_a_run_whose_watcher_was_killed_ends_as_interrupted_and_leaves_its_threads_failed(self):
        review = Review()
        events = review.open_thread("reviewer", "Is this ready?")
        done = events[0].thread_id
        events += review.start_run([done])
        events += review.add_comment("agent", done, "reply", "It is ready.")
        events += review.end_run("done")
        events += review.open_thread("reviewer", "And the docs?")
        killed = events[-1].thread_id
        events += review.start_run([killed])
        # The watcher is killed here: the next one rebuilds the review from its events
        restarted = Review.from_events(events)
        self.assertEqual(restarted.state(killed), "working")

        [ended] = restarted.recover_runs()

        self.assertEqual((ended.run_id, ended.outcome), (restarted.runs()[1].id, "interrupted"))
        self.assertEqual([r.outcome for r in restarted.runs()], ["done", "interrupted"])
        self.assertEqual((restarted.state(done), restarted.state(killed)), ("replied", "failed"))
        self.assertEqual(restarted.recover_runs(), [])


class ViewedFiles(unittest.TestCase):
    """A file stays viewed until its diff in the changeset changes; then the
    mark is cleared."""

    NOW = {"app.py": "hash-1", "lib.py": "hash-2"}  # each file's diff hash in the changeset

    def test_a_reviewer_marks_a_file_viewed_with_its_diff_as_it_is_now_and_unmarks_it(self):
        review = Review()

        [marked] = review.mark_viewed("app.py", True, self.NOW)
        review.mark_viewed("lib.py", True, self.NOW)
        [unmarked] = review.mark_viewed("lib.py", False, self.NOW)

        self.assertEqual((type(marked), marked.file, marked.diff_hash), (FileViewed, "app.py", "hash-1"))
        self.assertIsNone(unmarked.diff_hash)
        self.assertEqual(review.viewed(), {"app.py": "hash-1"})

    def test_a_file_that_is_not_in_the_changeset_is_not_found(self):
        with self.assertRaises(NotFound):
            Review().mark_viewed("gone.py", True, self.NOW)

    def test_a_mark_whose_diff_changed_is_cleared_and_undoing_the_change_does_not_bring_it_back(self):
        review = Review()
        review.mark_viewed("app.py", True, self.NOW)
        review.mark_viewed("lib.py", True, self.NOW)

        [cleared] = review.clear_changed_marks({"app.py": "hash-1", "lib.py": "hash-3"})

        self.assertEqual((cleared.file, cleared.diff_hash), ("lib.py", None))
        self.assertEqual(review.clear_changed_marks(self.NOW), [])
        self.assertEqual(review.viewed(), {"app.py": "hash-1"})

    def test_a_mark_whose_file_left_the_changeset_is_cleared(self):
        review = Review()
        review.mark_viewed("app.py", True, self.NOW)

        review.clear_changed_marks({})

        self.assertEqual(review.viewed(), {})


class WhileAnotherBranchIsCheckedOut(unittest.TestCase):
    """The files on disk are another branch's, so nothing that reads them
    changes the review: opening a thread and marking a file viewed conflict."""

    def test_opening_a_thread_conflicts(self):
        review = Review()

        for anchor in (None, SHOWN):
            with self.subTest(anchor=anchor):
                with self.assertRaises(Conflict):
                    review.open_thread("reviewer", "Why?", anchor, on_branch=False)
        self.assertEqual(review.threads(), [])

    def test_marking_a_file_viewed_conflicts_and_the_marks_stay(self):
        review = Review()
        review.mark_viewed("app.py", True, {"app.py": "hash-1"})

        for viewed in (True, False):
            with self.subTest(viewed=viewed):
                with self.assertRaises(Conflict):
                    review.mark_viewed("app.py", viewed, {}, on_branch=False)
        self.assertEqual(review.viewed(), {"app.py": "hash-1"})

    def test_a_non_reviewer_is_still_not_allowed_rather_than_in_conflict(self):
        with self.assertRaises(NotAllowed):
            Review().open_thread("agent", "Why?", on_branch=False)


class RebuildingAReview(unittest.TestCase):
    def test_a_review_rebuilt_from_its_events_holds_the_same_threads(self):
        review = Review()
        events = review.open_thread("reviewer", "Is this ready?")
        events += review.open_thread("reviewer", "Why an f-string?", SHOWN,
                                     Snapshot("blob-2", "commit-1", "    return 'hello ' + name"))

        rebuilt = Review.from_events(events)

        for opened in (events[0], events[2]):
            self.assertEqual(rebuilt.thread(opened.thread_id), review.thread(opened.thread_id))

    def test_a_thread_whose_code_moved_keeps_its_code_on_the_new_lines(self):
        review = Review()
        events = review.open_thread("reviewer", "Why an f-string?", SHOWN,
                                    Snapshot("blob-1", "commit-1", "    return f'hello {name}'"))
        tid = events[0].thread_id

        rebuilt = Review.from_events(events + [ThreadMoved(tid, 5, 5, "blob-2", "2026-11-07T10:00:00.000Z")])

        self.assertEqual(rebuilt.thread(tid).anchor,
                         Anchor("app.py", "new", 5, 5, code="    return f'hello {name}'", view="HEAD~1",
                                snapshot_id="blob-2", commit="commit-1"))

    def test_every_event_lasts_but_a_note_that_is_not_final_yet(self):
        review, tid = a_review_with_a_thread()
        events = review.start_run([tid])
        events += review.add_comment("difftate", tid, "progress", "Thinking…")
        note = events[-1].comment
        events += review.edit_note("difftate", note.id, "progress", "Read app.py")
        events += review.add_comment("agent", tid, "reply", "It is ready.")
        events += review.edit_note("difftate", note.id, "progress", "✅ Done", final=True)
        events += review.end_run("done")

        self.assertEqual([type(e) for e in lasting(events)], [RunStarted, CommentAdded, NoteWritten, RunEnded])
        self.assertTrue(lasting(events)[2].final)

    def test_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            Review().thread("no-such-thread")


if __name__ == "__main__":
    unittest.main()
