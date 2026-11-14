"""Seam: the Review's use cases, for reviewing and for running the loop
(Dispatch), with a fake at every driven port.

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

from core_fakes import CodeThatCantKeep, FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.changes.model import FileInView  # noqa: E402
from difftate.core.review.model import (  # noqa: E402
    Anchor, Comment, CommentAdded, Conflict, CouldNotRead, NotAllowed, NotFound, NotesInProgress, NoteWritten,
    Review, RunEnded, ThreadOpened,
)
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.edit_note import edit_note  # noqa: E402
from difftate.core.review.use_cases.end_run import end_run  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.list_viewed import list_viewed  # noqa: E402
from difftate.core.review.use_cases.mark_viewed import mark_viewed  # noqa: E402
from difftate.core.review.use_cases.move_with_code import move_with_code  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.recover_runs import recover_runs  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402
from difftate.core.review.use_cases.start_run import start_run  # noqa: E402

TIME = "2026-11-07T10:00:00.000Z"


class UseCaseTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({}, diff_hashes={"app.py": "hash-1", "lib.py": "hash-2"})
        self.history = FakeHistory()
        self.notes = NotesInProgress()

    def a_thread(self, body="Is this ready?"):
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", body).thread.id

    def rebuilt(self):
        return Review.from_events(self.store.load() + self.notes.events())


class AddingAComment(UseCaseTest):
    def test_a_reply_is_kept_and_recorded_in_the_review_history(self):
        tid = self.a_thread()

        reply = add_comment(self.store, self.notes, self.history, "agent", tid, "reply", "It is ready.")

        self.assertEqual(self.rebuilt().thread(tid).comments[-1], reply)
        self.assertEqual((reply.author, reply.kind, reply.body), ("agent", "reply", "It is ready."))
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_note_that_is_not_final_yet_is_held_in_the_core_and_never_given_to_the_store(self):
        tid = self.a_thread()
        kept, recorded = self.store.load(), list(self.history.recorded)

        note = add_comment(self.store, self.notes, self.history, "difftate", tid, "progress", "Thinking…")
        reply = add_comment(self.store, self.notes, self.history, "agent", tid, "reply", "It is ready.")

        self.assertEqual(self.store.load(), kept + [e for e in self.history.recorded if e not in recorded])
        self.assertFalse(any(isinstance(e, NoteWritten) for e in self.store.load() + self.history.recorded))
        [listed] = list_threads(self.store, self.notes, self.code)
        self.assertEqual(listed.thread.comments[1:], (note, reply))

    def test_a_reply_written_by_anyone_but_the_coding_agent_is_not_allowed_and_nothing_is_kept(self):
        tid = self.a_thread()
        kept, recorded = self.store.load(), list(self.history.recorded)

        for author in ("reviewer", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    add_comment(self.store, self.notes, self.history, author, tid, "reply", "A reply in disguise")

        self.assertEqual((self.store.load(), self.history.recorded), (kept, recorded))

    def test_a_comment_on_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            add_comment(self.store, self.notes, self.history, "agent", "no-such-thread", "reply", "Hello?")


class EditingANote(UseCaseTest):
    def setUp(self):
        super().setUp()
        self.tid = self.a_thread()
        self.note = add_comment(self.store, self.notes, self.history, "difftate", self.tid, "queued", "Queued")

    def edit(self, *args, **kwargs):
        return edit_note(self.store, self.notes, self.history, "difftate", *args, **kwargs)

    def test_a_note_changes_in_its_place_and_is_kept_only_once_final(self):
        kept = self.store.load()

        edited = self.edit(self.note.id, "progress", "Thinking…")
        self.assertEqual((edited.id, edited.kind, edited.body, edited.seq),
                         (self.note.id, "progress", "Thinking…", self.note.seq))
        self.assertEqual(self.rebuilt().thread(self.tid).comments[-1], edited)
        self.assertEqual(self.store.load(), kept, "not final yet: held in the core")

        final = self.edit(self.note.id, "progress", "✅ Done in 3s", final=True)
        self.assertEqual(Review.from_events(self.store.load()).thread(self.tid).comments[-1], final)
        self.assertEqual(self.history.recorded, self.store.load())
        self.assertEqual(self.notes.events(), [], "no longer held")

    def test_a_final_note_does_not_change_again(self):
        self.edit(self.note.id, "progress", "✅ Done in 3s", final=True)
        kept = self.store.load()

        with self.assertRaises(Conflict):
            self.edit(self.note.id, "progress", "Thinking…")

        self.assertEqual(self.store.load(), kept)

    def test_a_comment_is_not_a_note_and_is_not_edited(self):
        comment = self.rebuilt().thread(self.tid).comments[0]

        with self.assertRaises(NotAllowed) as refused:
            self.edit(comment.id, "progress", "Overwritten")

        self.assertEqual(str(refused.exception), f"{comment.id} is not a note: only notes can be edited")
        self.assertEqual(self.rebuilt().thread(self.tid).comments[0], comment)

    def test_only_difftate_edits_a_note(self):
        with self.assertRaises(NotAllowed):
            edit_note(self.store, self.notes, self.history, "agent", self.note.id, "queued", "Mine now")

    def test_a_note_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            self.edit("no-such-note", "progress", "Hello?")


class SettingAThreadStatus(UseCaseTest):
    def test_a_reviewer_resolves_a_thread_and_it_stays_resolved(self):
        tid = self.a_thread()

        thread = set_status(self.store, self.notes, self.history, "reviewer", tid, "resolved")

        self.assertEqual(thread.status, "resolved")
        self.assertEqual(self.rebuilt().thread(tid).status, "resolved")
        self.assertEqual(self.history.recorded, self.store.load())

    def test_anyone_but_a_reviewer_is_not_allowed_and_nothing_is_kept(self):
        tid = self.a_thread()
        kept = self.store.load()

        with self.assertRaises(NotAllowed):
            set_status(self.store, self.notes, self.history, "agent", tid, "resolved")

        self.assertEqual(self.store.load(), kept)


class ListingThreads(UseCaseTest):
    def test_each_thread_comes_with_its_thread_state_and_can_be_listed_by_status(self):
        replied, waiting = self.a_thread(), self.a_thread("And the docs?")
        review = self.rebuilt()
        self.store.append(review.start_run([replied]))
        add_comment(self.store, self.notes, self.history, "agent", replied, "reply", "It is ready.")
        self.store.append(self.rebuilt().end_run("done"))
        resolved = self.a_thread("And the tests?")
        set_status(self.store, self.notes, self.history, "reviewer", resolved, "resolved")

        self.assertEqual([(t.thread.id, t.state) for t in list_threads(self.store, self.notes, self.code)],
                         [(replied, "replied"), (waiting, "waiting"), (resolved, None)])
        self.assertEqual([t.thread.id for t in list_threads(self.store, self.notes, self.code, "open")],
                         [replied, waiting])
        self.assertEqual([t.thread.id for t in list_threads(self.store, self.notes, self.code, "resolved")],
                         [resolved])

    def test_a_thread_comes_with_the_notes_that_are_not_final_yet(self):
        tid = self.a_thread()
        note = add_comment(self.store, self.notes, self.history, "difftate", tid, "queued", "Queued")

        thread = set_status(self.store, self.notes, self.history, "reviewer", tid, "dismissed")

        self.assertEqual(thread.comments[-1], note)
        self.assertEqual(list_threads(self.store, self.notes, self.code)[0].thread, thread)


LONG = "".join(f"line_{n} = {n}\n" for n in range(1, 21))


class ListingThreadsInAView(UseCaseTest):
    """A thread sits by its code in every view: its snapshot diffed against
    the file in the view. The staged view here is the file without the three
    lines added above on disk, and without the tail line."""

    def setUp(self):
        super().setUp()
        on_disk = "import os\nimport re\nimport sys\n" + LONG + "tail = 1\n"
        self.code = FakeCode({"long.py": on_disk}, views={"staged": {"long.py": LONG}})

    def open_on(self, line, code=None):
        anchor = Anchor("long.py", "new", line, line, code)
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", "Why?", anchor).thread.id

    def listed(self, view=None):
        return {t.thread.id: t for t in list_threads(self.store, self.notes, self.code, view=view)}

    def lines(self, listed):
        return listed.thread.anchor.start_line, listed.thread.anchor.end_line, listed.in_view

    def test_a_thread_is_listed_on_the_lines_its_code_has_in_the_view(self):
        tid = self.open_on(15)  # line_12 = 12, three lines down on disk

        self.assertEqual(self.lines(self.listed("staged")[tid]), (12, 12, True))
        self.assertEqual(self.lines(self.listed("")[tid]), (15, 15, True))

    def test_a_thread_whose_code_the_view_does_not_show_is_listed_with_its_own_lines_not_placed(self):
        tail = self.open_on(24)

        self.assertEqual(self.lines(self.listed("staged")[tail]), (24, 24, False))
        self.assertEqual(self.lines(self.listed("")[tail]), (24, 24, True))

    def test_without_a_view_each_thread_is_listed_with_its_own_lines(self):
        tid = self.open_on(15)

        self.assertEqual(self.lines(self.listed()[tid]), (15, 15, True))

    def test_an_outdated_thread_or_a_general_thread_is_listed_as_it_is(self):
        outdated = self.open_on(15, code="line_12 = 1200")
        general = self.a_thread()

        listed = self.listed("staged")
        self.assertEqual(self.lines(listed[outdated]), (15, 15, True))
        self.assertTrue(listed[outdated].thread.outdated)
        self.assertEqual((listed[general].thread.anchor, listed[general].in_view), (None, True))

    def test_a_thread_whose_file_cannot_be_read_now_is_listed_as_it_is(self):
        tid = self.open_on(15)

        [listed] = list_threads(self.store, self.notes, UnreadableCode(), view="staged")

        self.assertEqual((listed.thread.id, self.lines(listed)), (tid, (15, 15, True)))

    def test_while_another_branch_is_checked_out_no_thread_is_placed_in_its_code(self):
        tid, general = self.open_on(15), self.a_thread()
        self.code.checked_out, self.code.reads = False, 0

        for view in (None, "", "staged"):
            with self.subTest(view=view):
                listed = self.listed(view)
                self.assertEqual(self.lines(listed[tid]), (15, 15, False))
                self.assertTrue(listed[general].in_view, "a general thread is in every view")
        self.assertEqual(self.code.reads, 0, "the other branch's code is not read")


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


class ForRunningTheLoop(unittest.TestCase):
    """The use cases Dispatch runs the loop with, on the Review."""

    def setUp(self):
        self.store = MemoryStore()
        self.notes = NotesInProgress()
        self.history = FakeHistory()
        self.code = FakeCode({"long.py": LONG})

    def rebuilt(self):
        return Review.from_events(self.store.load() + self.notes.events())

    def open_on(self, line, file="long.py"):
        anchor = Anchor(file, "new", line, line)
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", "Why?", anchor).thread.id

    def now_id(self, file="long.py"):
        return self.code.versions([FileInView(file, "new")])[FileInView(file, "new")]


class MovingThreadsWithTheirCode(ForRunningTheLoop):
    def setUp(self):
        super().setUp()
        self.tid = self.open_on(12)

    def move(self, code=None):
        return move_with_code(self.store, code or self.code, self.history)

    def test_lines_added_above_a_thread_move_it_with_its_code_and_the_move_is_kept(self):
        self.code.files["long.py"] = "import os\nimport re\nimport sys\n" + LONG

        self.assertEqual(self.move(), [], "none outdated")

        anchor = self.rebuilt().thread(self.tid).anchor
        self.assertEqual((anchor.start_line, anchor.end_line, anchor.code, anchor.snapshot_id),
                         (15, 15, "line_12 = 12", self.now_id()))
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_change_on_its_lines_makes_it_outdated_with_the_code_it_was_written_on(self):
        self.code.files["long.py"] = LONG.replace("line_12 = 12", "line_12 = 1200")

        self.assertEqual(self.move(), [self.tid])

        thread = self.rebuilt().thread(self.tid)
        self.assertTrue(thread.outdated)
        self.assertEqual((thread.anchor.start_line, thread.anchor.code), (12, "line_12 = 12"))
        self.assertEqual(self.move(), [], "outdated once")

    def test_code_that_did_not_change_keeps_nothing(self):
        kept = self.store.load()

        self.assertEqual(self.move(), [])

        self.assertEqual(self.store.load(), kept)

    def test_the_code_reader_keeps_the_snapshot_a_thread_moved_to_and_lets_the_one_before_go(self):
        before = self.rebuilt().thread(self.tid).anchor.snapshot_id
        self.code.files["long.py"] = "import os\n" + LONG

        self.move()

        self.assertEqual(self.code.asked_to_keep, {self.now_id()})
        self.assertNotEqual(self.now_id(), before)

    def test_the_snapshot_of_a_thread_that_became_outdated_is_no_longer_kept(self):
        self.code.files["long.py"] = LONG.replace("line_12 = 12", "line_12 = 1200")

        self.move()

        self.assertEqual(self.code.asked_to_keep, set())

    def test_a_move_whose_snapshot_cant_be_kept_is_not_kept_until_it_can_be(self):
        self.code.files["long.py"] = "import os\n" + LONG
        kept = self.store.load()
        cant = CodeThatCantKeep(self.code.files, self.code)

        with self.assertRaises(CouldNotRead):
            self.move(cant)
        self.assertEqual(self.store.load(), kept)

        self.move()
        self.assertEqual(self.rebuilt().thread(self.tid).anchor.start_line, 13)

    def test_a_move_the_store_cant_keep_leaves_the_snapshot_before_it_kept(self):
        before = self.rebuilt().thread(self.tid).anchor.snapshot_id
        self.code.files["long.py"] = "import os\n" + LONG
        store = StoreThatCannotKeep()
        store.append(self.store.load())

        with self.assertRaises(CouldNotRead):
            move_with_code(store, self.code, self.history)

        self.assertIn(before, self.code.asked_to_keep, "the thread the store has still moves from it")

    def test_a_review_whose_snapshots_were_never_kept_has_them_kept_when_its_code_is_next_read(self):
        snapshot = self.rebuilt().thread(self.tid).anchor.snapshot_id
        self.code.asked_to_keep = None  # opened by a difftate that didn't keep snapshots

        self.move()

        self.assertEqual(self.code.asked_to_keep, {snapshot})

    def test_a_thread_written_before_snapshots_existed_starts_moving_from_the_file_now(self):
        old = "written-before-snapshots"
        self.store.append([ThreadOpened(old, Anchor("long.py", "new", 5, 5, "line_5 = 5"), TIME),
                           CommentAdded(old, Comment("c-old", "reviewer", "comment", "Why 5?", TIME, 99))])

        self.move()
        self.assertEqual(self.rebuilt().thread(old).anchor.snapshot_id, self.now_id())
        self.code.files["long.py"] = "import os\n" + LONG
        self.move()

        anchor = self.rebuilt().thread(old).anchor
        self.assertEqual((anchor.start_line, anchor.snapshot_id), (6, self.now_id()))

    def test_a_thread_written_before_snapshots_existed_whose_code_is_gone_is_outdated(self):
        old = "written-before-snapshots"
        self.store.append([ThreadOpened(old, Anchor("long.py", "new", 5, 5, "line_5 = 500"), TIME),
                           CommentAdded(old, Comment("c-old", "reviewer", "comment", "Why 5?", TIME, 99))])

        self.assertEqual(self.move(), [old])

    def test_while_another_branch_is_checked_out_nothing_moves_and_its_code_is_not_read(self):
        self.code.files["long.py"] = "import os\n" + LONG
        self.code.checked_out, self.code.reads = False, 0
        kept = self.store.load()

        self.assertEqual(self.move(), [])

        self.assertEqual((self.store.load(), self.code.reads), (kept, 0))

    def test_code_that_cannot_be_read_moves_nothing(self):
        kept = self.store.load()

        self.assertEqual(self.move(UnreadableCode()), [])

        self.assertEqual(self.store.load(), kept)

    def test_a_checkout_while_the_code_was_read_keeps_nothing(self):
        self.code.files["long.py"] = "import os\n" + LONG
        code = CheckedOutWhileReading(self.code)
        kept = self.store.load()

        self.assertEqual(self.move(code), [])

        self.assertEqual(self.store.load(), kept)


class Runs(ForRunningTheLoop):
    def setUp(self):
        super().setUp()
        self.first, self.second = self.open_on(1), self.open_on(2)

    def read(self):
        """The open threads, as Dispatch reads them before a run."""
        return [t.thread for t in list_threads(self.store, self.notes, self.code, "open")]

    def states(self):
        return [t.state for t in list_threads(self.store, self.notes, self.code)]

    def start(self, threads):
        return start_run(self.store, self.notes, self.history, threads)

    def reply(self, tid):
        add_comment(self.store, self.notes, self.history, "agent", tid, "reply", "Because.")

    def test_a_run_starts_on_the_threads_with_their_comments_and_is_kept(self):
        threads = self.read()

        run = self.start(threads)

        self.assertEqual((run.threads, run.sent), ((self.first, self.second),
                                                   tuple(t.comments[0].id for t in threads)))
        self.assertEqual(self.states(), ["working", "working"])
        self.assertEqual(self.rebuilt().runs(), [run])
        self.assertEqual(self.history.recorded, self.store.load())

    def test_a_comment_written_after_the_threads_were_read_waits_for_the_next_run(self):
        threads = self.read()
        add_comment(self.store, self.notes, self.history, "reviewer", self.first, "comment", "And the tests?")

        run = self.start(threads)

        self.assertEqual(run.sent, tuple(t.comments[0].id for t in threads))
        end_run(self.store, self.notes, self.history, "done")
        self.assertEqual(self.states()[0], "waiting")

    def test_a_run_the_store_cannot_keep_does_not_start(self):
        store = StoreThatCannotKeep()
        store.append(self.store.load())

        with self.assertRaises(CouldNotRead):
            start_run(store, self.notes, self.history, self.read())

        self.assertEqual(Review.from_events(store.load()).runs(), [])

    def test_a_run_ends_and_leaves_its_threads_with_no_reply_failed(self):
        self.start(self.read())
        self.reply(self.first)

        failed = end_run(self.store, self.notes, self.history, "done")

        self.assertEqual([t.id for t in failed], [self.second])
        self.assertEqual(self.states(), ["replied", "failed"])
        self.assertEqual(self.rebuilt().runs()[0].outcome, "done")
        self.assertEqual(self.history.recorded, self.store.load())

    def test_with_no_run_in_progress_ending_keeps_nothing_and_fails_no_thread(self):
        kept = self.store.load()

        self.assertEqual(end_run(self.store, self.notes, self.history, "stopped"), [])

        self.assertEqual(self.store.load(), kept)

    def test_a_run_whose_watcher_was_killed_ends_interrupted_and_its_threads_with_no_reply_fail(self):
        self.start(self.read())
        self.reply(self.first)

        failed = recover_runs(self.store, NotesInProgress(), self.history)  # the next watcher

        self.assertEqual([t.id for t in failed], [self.second])
        self.assertIsInstance(self.store.load()[-1], RunEnded)
        self.assertEqual(self.rebuilt().runs()[0].outcome, "interrupted")
        self.assertEqual(recover_runs(self.store, NotesInProgress(), self.history), [], "recovered once")


class StoreThatCannotKeep(MemoryStore):
    """A store that can't write (a full disk, say)."""

    def append(self, events):
        if self.load():
            raise CouldNotRead("could not write the review")
        super().append(events)


class CheckedOutWhileReading(FakeCode):
    """Another branch is checked out after the code reader first says the
    review's branch is: what it read may be the other branch's."""

    def __init__(self, code):
        super().__init__(code.files)
        self._kept = code._kept  # the snapshots <code> gave out
        self.asked = 0

    def on_branch(self):
        self.asked += 1
        return self.asked == 1


if __name__ == "__main__":
    unittest.main()
