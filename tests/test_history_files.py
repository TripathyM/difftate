"""Seam: the review history files, behind the port for recording review history
(ForRecordingReviewHistory).

One JSON-lines file per month: every event the store keeps, as its
events.jsonl line, with the repository, branch, base and review added. For
the same events, the adapter writes the same lines as the old History
(local.py) did: tests/fixtures/todays-review/history.jsonl. The history
folder is a temporary one, never ~/.difftate.
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
from difftate.core.review.model import Comment, CommentAdded, ThreadOpened, ThreadStatusChanged  # noqa: E402
from test_core_replay import TODAYS_REVIEW  # noqa: E402

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
        with open(os.path.join(TODAYS_REVIEW, "events.jsonl"), encoding="utf-8") as f:
            events = read_events(f.read())
        history = HistoryFiles(ABOUT, os.path.join(self.tmp, "new"))

        history.record(events[:2])
        for event in events[2:]:
            history.record([event])

        with open(os.path.join(TODAYS_REVIEW, "history.jsonl"), "rb") as f:
            self.assertEqual(lines_in(os.path.join(self.tmp, "new")), f.read().splitlines(keepends=True))

    def test_a_line_is_the_stored_line_with_the_review_it_came_from(self):
        folder = os.path.join(self.tmp, "history")

        HistoryFiles(ABOUT, folder).record([ThreadOpened("t1", None, "2026-11-07T10:00:00.000Z")])

        [name] = os.listdir(folder)
        self.assertRegex(name, r"^\d{4}-\d{2}\.jsonl$")
        [line] = lines_in(folder)
        self.assertEqual(json.loads(line), dict(
            {"type": "opened", "thread": "t1", "anchor": None, "time": "2026-11-07T10:00:00.000Z"}, **ABOUT))

    def test_a_comment_and_a_status_change_carry_the_reviewer_name(self):
        folder = os.path.join(self.tmp, "history")
        time = "2026-11-07T10:00:00.000Z"

        HistoryFiles(ABOUT, folder).record([
            CommentAdded("t1", Comment("c1", "reviewer", "comment", "Tests?", time, 1, "security-bot")),
            ThreadStatusChanged("t1", "resolved", time, "security-bot")])

        self.assertEqual([json.loads(line) for line in lines_in(folder)], [
            dict({"id": "c1", "author": "reviewer", "by": "security-bot", "kind": "comment", "body": "Tests?",
                  "time": time, "seq": 1, "type": "comment", "thread": "t1"}, **ABOUT),
            dict({"type": "status", "thread": "t1", "status": "resolved", "by": "security-bot", "time": time},
                 **ABOUT)])

    def test_a_history_it_cannot_write_is_a_warning_not_an_error(self):
        in_the_way = os.path.join(self.tmp, "a-file")
        open(in_the_way, "w").close()
        out = StringIO()

        with redirect_stdout(out):
            HistoryFiles(ABOUT, os.path.join(in_the_way, "history")).record([ThreadOpened("t1", None, "now")])

        self.assertIn("Warning: could not write the review history", out.getvalue())


if __name__ == "__main__":
    unittest.main()
