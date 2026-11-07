"""Seam: the changeset use case (core/changes/use_cases/changeset.py), with
the fake code reader."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from core_fakes import FakeCode, UnreadableCode  # noqa: E402
from difftate.core.changes.use_cases.changeset import changeset  # noqa: E402
from difftate.core.review.model import CouldNotRead, NotFound  # noqa: E402

BASE = {"app.py": "def greet(name):\n    return 'hi ' + name\n"}
NOW = {"app.py": "def greet(name):\n    return f'hello {name}'\n"}


class TheChangeset(unittest.TestCase):
    def setUp(self):
        self.code = FakeCode(dict(NOW), base=dict(BASE))

    def test_all_changes_is_the_default_view(self):
        found = changeset(self.code)

        self.assertEqual((found.view, found.base), ("", "main"))
        self.assertIn("+    return f'hello {name}'", found.diff)

    def test_it_is_the_changeset_in_the_view_asked_for(self):
        self.assertEqual(changeset(self.code, "staged").view, "staged")

    def test_a_view_given_as_nothing_is_all_changes(self):
        self.assertEqual(changeset(self.code, None).view, "")

    def test_a_view_that_isnt_one_is_not_found(self):
        with self.assertRaises(NotFound):
            changeset(self.code, "no-such-commit")

    def test_a_changeset_that_cannot_be_read_says_so(self):
        with self.assertRaises(CouldNotRead):
            changeset(UnreadableCode())


if __name__ == "__main__":
    unittest.main()
