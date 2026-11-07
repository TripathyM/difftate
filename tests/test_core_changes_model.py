"""Seam: the Changes model (core/changes/model.py), with no git and no
repository.

A thread moves with its code, or is outdated: the code reader hands back plain
data (the file now, and the hunks of the diff from the thread's snapshot to
it), and the model decides. Hunks are as `git diff -U0` gives them: (old
start, old count, new start, new count), with a count of 0 for lines added
after (or removed after) the start line.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.core.changes.model import (  # noqa: E402
    OUTDATED, Hunk, Moved, View, lines_in_view, map_lines, moved_or_outdated, moved_or_outdated_by_code,
)

SNAPSHOT, NOW = "snapshot-blob", "now-blob"


class AThreadMovesWithItsCode(unittest.TestCase):
    """A thread on lines 12..13 of its snapshot, and the file now."""

    def decide(self, hunks, now=NOW, snapshot=SNAPSHOT):
        return moved_or_outdated(12, 13, snapshot, now, hunks)

    def test_lines_added_above_it_move_it_down(self):
        self.assertEqual(self.decide([Hunk(0, 0, 1, 3)]), Moved(15, 16, NOW))

    def test_lines_removed_above_it_move_it_up(self):
        self.assertEqual(self.decide([Hunk(2, 2, 1, 0)]), Moved(10, 11, NOW))

    def test_changes_below_it_leave_it_where_it_is(self):
        self.assertIsNone(self.decide([Hunk(20, 1, 20, 1), Hunk(30, 0, 31, 4)]))

    def test_a_file_that_is_its_snapshot_changes_nothing(self):
        self.assertIsNone(self.decide(None, now=SNAPSHOT))


class AThreadIsOutdatedWhenItsCodeChanges(unittest.TestCase):
    def decide(self, hunks, now=NOW):
        return moved_or_outdated(12, 13, SNAPSHOT, now, hunks)

    def test_a_change_to_one_of_its_lines(self):
        self.assertIs(self.decide([Hunk(0, 0, 1, 1), Hunk(13, 1, 14, 1)]), OUTDATED)

    def test_a_line_added_between_its_lines(self):
        self.assertIs(self.decide([Hunk(12, 0, 13, 1)]), OUTDATED)

    def test_its_lines_removed(self):
        self.assertIs(self.decide([Hunk(11, 4, 10, 0)]), OUTDATED)

    def test_its_file_gone(self):
        self.assertIs(self.decide(None, now=None), OUTDATED)

    def test_a_lost_snapshot(self):
        # The snapshot is gone from where the code reader kept it (git gc):
        # there is nothing to diff, so nothing to move with
        self.assertIs(self.decide(None), OUTDATED)


class AThreadWrittenBeforeSnapshotsExisted(unittest.TestCase):
    """It has no snapshot to diff: it moves with its code from the file now
    if its code is still on its lines."""

    CODE = "line_12 = 12\nline_13 = 13"

    def test_its_code_still_on_its_lines_starts_moving_with_it_from_the_file_now(self):
        self.assertEqual(moved_or_outdated_by_code(12, 13, self.CODE, NOW, "line_12 = 12\r\nline_13 = 13\n"),
                         Moved(12, 13, NOW))

    def test_other_code_on_its_lines_is_outdated(self):
        self.assertIs(moved_or_outdated_by_code(12, 13, self.CODE, NOW, "line_12 = 'twelve'\nline_13 = 13"),
                      OUTDATED)

    def test_no_such_lines_or_no_code_kept_is_outdated(self):
        self.assertIs(moved_or_outdated_by_code(12, 13, self.CODE, NOW, None), OUTDATED)
        self.assertIs(moved_or_outdated_by_code(12, 13, None, NOW, "line_12 = 12\nline_13 = 13"), OUTDATED)


class AThreadInAView(unittest.TestCase):
    """Where a thread's lines are in a view: its snapshot diffed against the
    file on its side of that view."""

    def test_it_sits_where_its_code_is_there(self):
        self.assertEqual(lines_in_view(12, 13, SNAPSHOT, "there", [Hunk(0, 0, 1, 2)]), (14, 15))

    def test_the_file_as_snapshotted_keeps_its_lines(self):
        self.assertEqual(lines_in_view(12, 13, SNAPSHOT, SNAPSHOT, None), (12, 13))

    def test_its_code_not_there_or_changed_there_places_it_nowhere(self):
        self.assertIsNone(lines_in_view(12, 13, SNAPSHOT, None, None))
        self.assertIsNone(lines_in_view(12, 13, SNAPSHOT, "there", [Hunk(12, 1, 12, 1)]))
        self.assertIsNone(lines_in_view(12, 13, SNAPSHOT, "there", None))


class MappingLines(unittest.TestCase):
    def test_hunks_after_the_lines_stop_the_mapping(self):
        self.assertEqual(map_lines([Hunk(1, 1, 1, 2), Hunk(13, 0, 15, 1), Hunk(14, 1, 16, 1)], 12, 13), (13, 14))

    def test_no_hunks_keep_the_lines(self):
        self.assertEqual(map_lines([], 3, 4), (3, 4))


class AView(unittest.TestCase):
    def test_the_terminal_names_each_view(self):
        self.assertEqual(View("").name, "all changes")
        self.assertEqual(View("HEAD").name, "uncommitted changes")
        self.assertEqual(View("staged").name, "staged changes")
        self.assertEqual(View("unstaged").name, "unstaged changes")
        self.assertEqual(View("HEAD~2").name, "the commits after HEAD~2")

    def test_all_changes_is_the_default_view(self):
        self.assertEqual(View(), View(""))
        self.assertTrue(View().is_all_changes)
        self.assertFalse(View("HEAD").is_all_changes)


if __name__ == "__main__":
    unittest.main()
