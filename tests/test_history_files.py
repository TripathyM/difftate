"""Seam: the review history files, behind the port for recording review history
(ForRecordingReviewHistory).

One JSON-lines file per month: every event the store keeps, as its
events.jsonl line, with the repository, branch, base and review added. For
the same events, the new adapter writes the same lines as today's History
(local.py). The history folder is a temporary one, never ~/.difftate.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from difftate.adapters.outbound.history_files import HistoryFiles  # noqa: E402
from difftate.adapters.outbound.local_store.lines import read_events  # noqa: E402
from difftate.core.review.model import ThreadOpened  # noqa: E402
from difftate.local import History, LocalStore as TodaysLocalStore  # noqa: E402
from test_core_replay import write_a_review  # noqa: E402

ABOUT = {"repo": {"path": "/repo", "remote": "git@example.com:me/repo.git"}, "branch": "feature",
         "base": "main", "review": "feature-1234abcd"}


def lines_in(folder):
    """Every history file's lines, oldest month first."""
    found = []
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), "rb") as f:
            found += f.read().splitlines(keepends=True)
    return found


class TheReviewHistoryFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftate-history-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_same_events_give_the_same_lines_as_today(self):
        review = os.path.join(self.tmp, "review")
        os.makedirs(review)
        today_history = os.path.join(self.tmp, "today")
        write_a_review(TodaysLocalStore(review, {"id": "r"}, History(today_history, ABOUT), lambda ids: None,
                                        lambda: "commit-1"))
        with open(os.path.join(review, "events.jsonl"), encoding="utf-8") as f:
            events = read_events(f.read())
        history = HistoryFiles(ABOUT, os.path.join(self.tmp, "new"))

        history.record(events[:2])
        for event in events[2:]:
            history.record([event])

        self.assertEqual(lines_in(os.path.join(self.tmp, "new")), lines_in(today_history))

    def test_a_line_is_the_stored_line_with_the_review_it_came_from(self):
        folder = os.path.join(self.tmp, "history")

        HistoryFiles(ABOUT, folder).record([ThreadOpened("t1", None, "2026-11-07T10:00:00.000Z")])

        [name] = os.listdir(folder)
        self.assertRegex(name, r"^\d{4}-\d{2}\.jsonl$")
        [line] = lines_in(folder)
        self.assertEqual(json.loads(line), dict(
            {"type": "opened", "thread": "t1", "anchor": None, "time": "2026-11-07T10:00:00.000Z"}, **ABOUT))

    def test_a_history_it_cannot_write_is_a_warning_not_an_error(self):
        in_the_way = os.path.join(self.tmp, "a-file")
        open(in_the_way, "w").close()
        out = StringIO()

        with redirect_stdout(out):
            HistoryFiles(ABOUT, os.path.join(in_the_way, "history")).record([ThreadOpened("t1", None, "now")])

        self.assertIn("Warning: could not write the review history", out.getvalue())


if __name__ == "__main__":
    unittest.main()
