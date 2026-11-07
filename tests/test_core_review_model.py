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
    Anchor, CommentAdded, NotAllowed, NotFound, Review, ThreadOpened, ThreadOutdated,
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
                                               view="HEAD~1", snapshot="blob-1", commit="commit-1"))
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



class RebuildingAReview(unittest.TestCase):
    def test_a_review_rebuilt_from_its_events_holds_the_same_threads(self):
        review = Review()
        events = review.open_thread("reviewer", "Is this ready?")
        events += review.open_thread("reviewer", "Why an f-string?", SHOWN,
                                     Snapshot("blob-2", "commit-1", "    return 'hello ' + name"))

        rebuilt = Review.from_events(events)

        for opened in (events[0], events[2]):
            self.assertEqual(rebuilt.thread(opened.thread_id), review.thread(opened.thread_id))


    def test_a_thread_the_review_does_not_have_is_not_found(self):
        with self.assertRaises(NotFound):
            Review().thread("no-such-thread")


if __name__ == "__main__":
    unittest.main()
