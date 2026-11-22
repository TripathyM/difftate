"""Seam: the core use case "read the review path" (GLOSSARY.md, Review path),
with a fake at every driven port.

The coding agent writes review-path.md in the shape the "write a review path"
skill states (skills/write-review-path/SKILL.md). The code reader hands the
core its text, or none; the core reads the stops out of it, in order, each
with its questions and the reviewer's viewed mark for its file.
"""
import os
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.review_path import BadReviewPath, Question, Skipped, Stop  # noqa: E402
from difftate.core.review.use_cases.mark_viewed import mark_viewed  # noqa: E402
from difftate.core.review.use_cases.read_review_path import read_review_path  # noqa: E402
from difftate.core.review.use_cases.review_path_problem import review_path_problem  # noqa: E402

A_PATH = textwrap.dedent("""\
    ---
    branch: feature/trail-cards
    createdAt: 2026-11-22T06:10:00Z
    ---

    Review path for "Show trail cards" (made up).

    ## 1 `src/cards/CardList.tsx:12-64` ★
    Spec: `src/cards/CardList.test.tsx` "shows three cards"

    ### What does the list do?
    It shows the trails as cards,
    three to a row.

    ### Is the fetch cancelled?
    Yes, on unmount.

    ### Side file: `src/cards/cards.css`
    Layout only.

    ## 1.1 `src/cards/Card.tsx`

    ### Where does the picture come from?
    The trail's first photo.

    ## 2 `src/data/useTrails.ts`

    ### How is the fetch built?
    One request, retried twice.

    ## Section: State flow
    ### Not a question
    Free text.

    ## Skipped
    - `package-lock.json` — lockfile only
    - `src/data/trailTypes.d.ts` — generated
    """)


CHANGED = {f: "x\n" for f in ("src/cards/CardList.tsx", "src/cards/Card.tsx", "src/cards/cards.css",
                              "src/data/useTrails.ts", "package-lock.json", "src/data/trailTypes.d.ts", "app.py", "lib.py", "docs/time:zones.md")}


class ReadingTheReviewPath(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.history = FakeHistory()

    def read(self, text, files=None):
        self.code = FakeCode(files or CHANGED, base={}, review_path=text)
        return read_review_path(self.store, self.code, self.history)

    def test_no_text_gives_no_path(self):
        self.assertIsNone(self.read(None))

    def test_the_stops_come_in_order_each_with_its_file_and_questions(self):
        path = self.read(A_PATH)

        self.assertEqual([(s.number, s.file) for s in path.stops], [
            ("1", "src/cards/CardList.tsx"), ("1.1", "src/cards/Card.tsx"), ("2", "src/data/useTrails.ts")])
        self.assertEqual(path.stops[0].questions, (
            Question("What does the list do?", "It shows the trails as cards,\nthree to a row."),
            Question("Is the fetch cancelled?", "Yes, on unmount.")))
        self.assertEqual(path.stops[2].questions, (Question("How is the fetch built?", "One request, retried twice."),))

    def test_a_side_file_a_path_section_and_skipped_files_are_not_stops_or_questions(self):
        path = self.read(A_PATH)

        self.assertNotIn("src/cards/cards.css", [s.file for s in path.stops])
        self.assertNotIn("Not a question", [q.question for s in path.stops for q in s.questions])
        self.assertNotIn("package-lock.json", [s.file for s in path.stops])

    def test_skipped_files_come_with_their_reasons(self):
        self.assertEqual(self.read(A_PATH).skipped, (Skipped("package-lock.json", "lockfile only"),
                                                     Skipped("src/data/trailTypes.d.ts", "generated")))

    def test_each_stop_carries_the_reviewers_viewed_mark_for_its_file(self):
        self.read(A_PATH)
        mark_viewed(self.store, self.code, self.history, "src/cards/Card.tsx", True)

        path = read_review_path(self.store, self.code, self.history)

        self.assertEqual([s.viewed for s in path.stops], [False, True, False])

    def test_a_heading_inside_a_code_block_in_an_answer_is_text(self):
        path = self.read(textwrap.dedent("""\
            ## 1 `app.py`

            ### What does it print?
            ```
            ## 2 `not-a-stop.py`
            ```
            """))

        self.assertEqual(path.stops, (Stop("1", "app.py", (Question("What does it print?",
                                                                     "```\n## 2 `not-a-stop.py`\n```"),)),))

    def test_a_code_block_ends_only_at_a_fence_like_the_one_that_opened_it(self):
        path = self.read("## 1 `app.py`\n\n### What does it print?\n~~~~\n```\n## 2 `inside.py`\n~~~~\n\n"
                         "## 2 `lib.py`\n\n### And this?\nA helper.\n")

        self.assertEqual([s.file for s in path.stops], ["app.py", "lib.py"])

    def test_one_line_ranges_are_line_ranges_too(self):
        self.assertEqual(self.read("## 1 `app.py:42,50-60`\n\n### Why?\nBecause.\n").stops[0].file, "app.py")

    def test_a_file_whose_name_has_a_colon_keeps_it_when_no_line_ranges_follow(self):
        path = self.read("## 1 `docs/time:zones.md`\n\n### Why?\nBecause.\n")

        self.assertEqual(path.stops[0].file, "docs/time:zones.md")

    def test_text_with_no_stops_is_a_path_with_none(self):
        self.assertEqual(self.read("Just some words.\n").stops, ())

    def test_reading_it_writes_nothing(self):
        self.read(A_PATH)

        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.history.recorded, [])


class ABrokenReviewPathIsAProblemAndNoPath(unittest.TestCase):
    """review-path.md that can't be read as a review path: the use case raises
    BadReviewPath naming the problem; review_path_problem says it as a line
    for a warning, or None when the file reads (or there is none)."""

    def setUp(self):
        self.store = MemoryStore()
        self.history = FakeHistory()

    def code(self, text, files=None):
        return FakeCode(files or CHANGED, base={}, review_path=text)

    def problem(self, text, files=None):
        return review_path_problem(self.code(text, files))

    def test_a_good_file_and_no_file_have_no_problem(self):
        self.assertIsNone(self.problem(A_PATH))
        self.assertIsNone(self.problem(None))

    def test_a_stop_naming_a_file_not_in_the_changeset_is_a_problem_naming_it(self):
        text = "## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n## 2 `src/gone.ts`\n\n### Why?\nBecause.\n"

        self.assertIn("src/gone.ts", self.problem(text))
        self.assertIn("not in the changeset", self.problem(text))
        with self.assertRaises(BadReviewPath):
            read_review_path(self.store, self.code(text), self.history)

    def test_a_skipped_file_not_in_the_changeset_is_a_problem_too(self):
        text = "## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n## Skipped\n- `yarn.lock` — lockfile only\n"

        self.assertIn("yarn.lock", self.problem(text))

    def test_a_heading_out_of_shape_is_a_problem_naming_its_line(self):
        for heading in ("## 1 src/cards/Card.tsx", "## One `src/cards/Card.tsx`", "## 1 `src/cards/Card.tsx` ★★",
                        "## Sections: State flow", "## Skippd"):
            with self.subTest(heading=heading):
                text = f"Preamble.\n\n{heading}\n\n### Why?\nBecause.\n"

                self.assertIn(heading, self.problem(text))
                self.assertIn("line 3", self.problem(text))

    def test_the_forms_the_skill_states_are_not_out_of_shape(self):
        for heading in ("## 1 `src/cards/CardList.tsx:10-20,30` ★", "## Section: State flow", "## Skipped"):
            with self.subTest(heading=heading):
                text = f"{heading}\n\n### Why?\nBecause.\n" if heading.startswith("## 1") else (
                    f"## 1 `src/cards/CardList.tsx`\n\n### Why?\nBecause.\n\n{heading}\nText.\n")

                self.assertIsNone(self.problem(text))
        nested = "## 1 `src/cards/CardList.tsx`\n\n### Why?\nB.\n\n## 1.1 `src/cards/Card.tsx`\n\n### Why?\nB.\n"
        self.assertIsNone(self.problem(nested))

    def test_a_file_named_twice_is_a_problem_naming_it(self):
        text = "## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n## 2 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n"

        self.assertIn("src/cards/Card.tsx", self.problem(text))
        self.assertIn("twice", self.problem(text))

    def test_a_heading_inside_a_code_block_is_not_checked(self):
        text = "## 1 `app.py`\n\n### Why?\n```\n## not a heading\n```\n"

        self.assertIsNone(self.problem(text, {"app.py": "x\n"}))

    def test_a_fixed_file_has_no_problem_on_the_next_read(self):
        code = self.code("## 1 `src/gone.ts`\n\n### Why?\nBecause.\n")
        self.assertIsNotNone(review_path_problem(code))

        code.review_path = A_PATH

        self.assertIsNone(review_path_problem(code))
        self.assertEqual(len(read_review_path(self.store, code, self.history).stops), 3)

    def test_checking_a_path_writes_nothing(self):
        self.problem("## 1 `src/gone.ts`\n")

        self.assertEqual(self.store.load(), [])


if __name__ == "__main__":
    unittest.main()
