"""Seam: one contract for every store behind the port for keeping the review
(ForKeepingTheReview, ADR 0004).

A store is load() and append(events), and holds no rules: it keeps every
event it is given, in order, and gives them back as they were given. The
memory store (tests) and the local store (difftate's own, in files) run the
same suite, so switching stores is safe. What the old stores did with their
method per change (threads, notes, runs, viewed marks) is the core's now:
tests/test_core_review_model.py and tests/test_core_review_use_cases.py.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.adapters.outbound.local_store import LocalStore  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import (  # noqa: E402
    Anchor, Comment, CommentAdded, FileViewed, NoteWritten, RunEnded, RunStarted, ThreadMoved, ThreadOpened,
    ThreadOutdated, ThreadStatusChanged,
)

T1, T2 = "thread-1", "thread-2"
TIME = "2026-11-07T10:00:00.000Z"
ANCHOR = Anchor("app.py", "new", 2, 3, "    return f'hello {name}'\n    pass", "HEAD~1", "a" * 40, "commit-1")
COMMENT = Comment("c1", "reviewer", "comment", "Why an f-string? ✨", TIME, 1)
REPLY = Comment("r1", "agent", "reply", "It reads better.", TIME, 3)
NOTE = Comment("n1", "difftate", "progress", "✅ **Done** in 3s", TIME, 2)

# Every event type, as the core gives them to a store
OPENING = [ThreadOpened(T1, ANCHOR, TIME), CommentAdded(T1, COMMENT),
           ThreadOpened(T2, None, TIME), CommentAdded(T2, Comment("c2", "reviewer", "comment", "Ready?", TIME, 4))]
WORK = [RunStarted("run-1", (T1, T2), ("c1", "c2"), {T1: (), T2: ("r0",)}, TIME),
        NoteWritten(T1, NOTE, final=True), CommentAdded(T1, REPLY), RunEnded("run-1", "done", TIME),
        ThreadStatusChanged(T2, "resolved", TIME), ThreadMoved(T1, 5, 6, "b" * 40, TIME),
        ThreadOutdated(T1, TIME), FileViewed("app.py", "c" * 40, TIME), FileViewed("app.py", None, TIME)]
# A reviewer name on comments and status changes, beside ones with none
NAMED = [ThreadOpened(T1, None, TIME), CommentAdded(T1, Comment("c1", "reviewer", "comment", "Ready?", TIME, 1, "Ada")),
         CommentAdded(T1, Comment("c2", "reviewer", "comment", "Tests? ✨", TIME, 2, "security-bot")),
         CommentAdded(T1, Comment("c3", "reviewer", "comment", "No name", TIME, 3)),
         ThreadStatusChanged(T1, "resolved", TIME, "security-bot"), ThreadStatusChanged(T1, "open", TIME)]


class StoreContract:
    """What every store does. Subclasses set self.store in setUp."""

    def test_a_new_store_has_no_events(self):
        self.assertEqual(self.store.load(), [])

    def test_it_gives_back_every_event_it_was_given_in_order(self):
        self.store.append(OPENING)
        self.store.append(WORK)

        self.assertEqual(self.store.load(), OPENING + WORK)

    def test_it_keeps_what_it_is_given_and_applies_no_rules(self):
        # A reply on a thread that was never opened, and a run that never
        # started, ending: the core decides, the store only keeps
        odd = [CommentAdded("no-such-thread", REPLY), RunEnded("no-such-run", "done", TIME)]

        self.store.append(odd)

        self.assertEqual(self.store.load(), odd)

    def test_it_keeps_a_note_that_isnt_final_as_not_final(self):
        # The core gives a store only final notes (lasting); a store that is
        # given one anyway keeps it as it was given
        progress = [ThreadOpened(T1, None, TIME), NoteWritten(T1, NOTE, final=False)]

        self.store.append(progress)

        self.assertEqual(self.store.load(), progress)

    def test_it_keeps_the_reviewer_name_on_each_comment_and_status_change(self):
        self.store.append(NAMED)

        self.assertEqual(self.store.load(), NAMED)

    def test_appending_nothing_keeps_what_was_there(self):
        self.store.append(OPENING)
        self.store.append([])

        self.assertEqual(self.store.load(), OPENING)

    def test_what_load_gives_is_the_callers_to_change(self):
        self.store.append(OPENING)
        self.store.load().clear()

        self.assertEqual(self.store.load(), OPENING)


class MemoryStoreContract(StoreContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()


def temp_folder(test):
    """A temporary folder the test removes: never a real review folder."""
    tmp = tempfile.mkdtemp(prefix="difftate-store-contract-")
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


class LocalStoreContract(StoreContract, unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(temp_folder(self), "git", "difftate")
        self.store = LocalStore.open(self.folder, branch="feature", base="main")

    def test_a_reopened_store_gives_back_the_same_events(self):
        self.store.append(OPENING)
        self.store.append(WORK)

        self.store.append([NoteWritten(T1, NOTE, final=False)])
        self.store.append(NAMED)

        reopened = LocalStore.open(self.folder, branch="feature", base="main")

        self.assertEqual(reopened.load(), OPENING + WORK + [NoteWritten(T1, NOTE, final=False)] + NAMED)


if __name__ == "__main__":
    unittest.main()
