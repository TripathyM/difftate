"""Seam: the core use case "read the review path" (GLOSSARY.md, Review path),
with a fake at every driven port.

The coding agent writes review-path.md in the shape the "write a review path"
skill states (skills/write-review-path/SKILL.md). The code reader hands the
core its text, or none; the core reads the stops out of it, in order, each
with its questions and the reviewer's viewed mark for its file.
"""
import os
import re
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import NotFound  # noqa: E402
from difftate.core.review.review_path import BadReviewPath, Question, Section, SideFile, Skipped, Spec, Stop  # noqa: E402
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
        named = re.findall(r"`([^`:]+)(?::[\d,-]+)?`", text or "")  # unless told, every file the text names is changed
        self.code = FakeCode(files or {**CHANGED, **{n: "x\n" for n in named}}, base={}, review_path=text)
        return read_review_path(self.store, self.code, self.history)

    def test_no_text_gives_no_path(self):
        self.assertIsNone(self.read(None))

    def test_the_stops_come_in_order_each_with_its_file_and_questions(self):
        path = self.read(A_PATH)

        self.assertEqual([(s.number, s.file) for s in path.all_stops()], [
            ("1", "src/cards/CardList.tsx"), ("1.1", "src/cards/Card.tsx"), ("2", "src/data/useTrails.ts")])
        self.assertEqual(path.stops[0].questions, (
            Question("What does the list do?", "It shows the trails as cards,\nthree to a row."),
            Question("Is the fetch cancelled?", "Yes, on unmount.")))
        self.assertEqual(path.stops[1].questions, (Question("How is the fetch built?", "One request, retried twice."),))

    def test_a_stop_under_a_stop_is_its_child_and_comes_after_the_stops_before_it(self):
        path = self.read("## 1 `a.py`\n\n### A?\nx\n\n## 1.1 `b.py`\n\n### B?\nx\n\n## 1.1.1 `c.py`\n\n### C?\nx\n\n"
                         "## 1.2 `d.py`\n\n### D?\nx\n\n## 2 `e.py`\n\n### E?\nx\n")

        self.assertEqual([s.file for s in path.stops], ["a.py", "e.py"])
        self.assertEqual([s.file for s in path.stops[0].children], ["b.py", "d.py"])
        self.assertEqual([s.file for s in path.stops[0].children[0].children], ["c.py"])
        self.assertEqual([s.number for s in path.all_stops()], ["1", "1.1", "1.1.1", "1.2", "2"])

    def test_a_stop_whose_parent_is_missing_stands_on_its_own(self):
        path = self.read("## 1 `a.py`\n\n### A?\nx\n\n## 3.1 `b.py`\n\n### B?\nx\n")

        self.assertEqual([s.file for s in path.stops], ["a.py", "b.py"])

    def test_a_star_marks_a_key_stop(self):
        path = self.read("## 1 `a.py` ★\n\n### A?\nx\n\n## 2 `b.py:3-4` ★\n\n### B?\nx\n\n## 3 `c.py`\n\n### C?\nx\n")

        self.assertEqual([s.key for s in path.stops], [True, True, False])

    def test_a_stop_lists_its_side_files_in_order_with_no_number_and_no_questions(self):
        path = self.read(A_PATH)

        self.assertEqual(path.stops[0].side_files, (SideFile("src/cards/cards.css", text="Layout only."),))
        self.assertEqual(path.stops[1].side_files, ())
        self.assertEqual([q.question for q in path.stops[0].questions], ["What does the list do?", "Is the fetch cancelled?"])

    def test_a_side_file_under_a_nested_stop_belongs_to_that_stop(self):
        path = self.read("## 1 `a.py`\n\n### A?\nx\n\n## 1.1 `b.py`\n\n### B?\nx\n\n### Side file: `b.css:1-4`\nStyle.\n")

        self.assertEqual(path.stops[0].side_files, ())
        self.assertEqual(path.stops[0].children[0].side_files, (SideFile("b.css", ranges=((1, 4),), text="Style."),))

    def test_the_changed_files_the_path_does_not_name_are_not_on_the_path(self):
        files = {"src/cards/CardList.tsx": "1\n", "src/cards/Card.tsx": "1\n", "src/cards/cards.css": "1\n",
                 "src/data/useTrails.ts": "1\n", "package-lock.json": "1\n", "src/data/trailTypes.d.ts": "1\n", "README.md": "1\n", "src/extra.ts": "1\n"}

        path = self.read(A_PATH, files)

        self.assertEqual(path.not_on_the_path, ("README.md", "src/extra.ts"))

    def test_with_every_file_named_nothing_is_off_the_path(self):
        self.assertEqual(self.read("## 1 `a.py`\n\n### A?\nx\n", {"a.py": "1\n"}).not_on_the_path, ())

    def test_a_skipped_file_and_a_side_file_are_on_the_path(self):
        files = {"a.py": "1\n", "a.css": "1\n", "uv.lock": "1\n"}

        path = self.read("## 1 `a.py`\n\n### A?\nx\n\n### Side file: `a.css`\n\n## Skipped\n- `uv.lock` — lockfile only\n", files)

        self.assertEqual(path.not_on_the_path, ())

    def test_a_side_file_a_path_section_and_skipped_files_are_not_stops_or_questions(self):
        path = self.read(A_PATH)

        self.assertNotIn("src/cards/cards.css", [s.file for s in path.stops])
        self.assertNotIn("Not a question", [q.question for s in path.stops for q in s.questions])
        self.assertNotIn("package-lock.json", [s.file for s in path.stops])

    def test_skipped_files_come_with_their_reasons(self):
        self.assertEqual(self.read(A_PATH).skipped, (Skipped("package-lock.json", "lockfile only"),
                                                     Skipped("src/data/trailTypes.d.ts", "generated")))

    def test_each_stop_and_side_file_carries_the_reviewers_viewed_mark_for_its_own_file(self):
        self.read(A_PATH)
        mark_viewed(self.store, self.code, self.history, "src/cards/Card.tsx", True)
        mark_viewed(self.store, self.code, self.history, "src/cards/cards.css", True)

        path = read_review_path(self.store, self.code, self.history)

        self.assertEqual([s.viewed for s in path.all_stops()], [False, True, False])
        self.assertEqual(path.stops[0].side_files, (SideFile("src/cards/cards.css", viewed=True, text="Layout only."),))

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

    def test_a_stop_and_a_side_file_carry_their_line_ranges_and_none_means_the_whole_file(self):
        path = self.read("## 1 `a.py:10-48,90-120`\n\n### A?\nx\n\n### Side file: `a.css:3`\nStyle.\n\n"
                         "## 2 `b.py:7`\n\n### B?\nx\n\n## 3 `c.py`\n\n### C?\nx\n")

        self.assertEqual([s.ranges for s in path.stops], [((10, 48), (90, 120)), ((7, 7),), ()])
        self.assertEqual(path.stops[0].side_files[0].ranges, ((3, 3),))

    def test_a_file_whose_name_has_a_colon_has_no_ranges(self):
        self.assertEqual(self.read("## 1 `docs/time:zones.md`\n\n### Why?\nBecause.\n").stops[0].ranges, ())

    def test_a_stop_lists_the_specs_under_its_heading_in_order(self):
        path = self.read(A_PATH + "\n## 3 `lib.py`\nSpec: `lib.test.py` \"one\"\nSpec: `lib.test.py` \"two\"\nSpec: `x.test.py`\n\n### Q?\nA.\n")

        self.assertEqual(path.stops[0].specs, (Spec("src/cards/CardList.test.tsx", "shows three cards"),))
        self.assertEqual(path.stops[1].specs, ())
        self.assertEqual(path.stops[-1].specs, (Spec("lib.test.py", "one"), Spec("lib.test.py", "two"), Spec("x.test.py", "")))

    def test_a_spec_line_after_a_question_is_part_of_its_answer(self):
        path = self.read("## 1 `a.py`\n\n### A?\nSpec: `a.test.py` \"x\"\n")

        self.assertEqual(path.stops[0].specs, ())
        self.assertEqual(path.stops[0].questions[0].answer, 'Spec: `a.test.py` "x"')

    def test_a_side_file_keeps_the_text_under_it(self):
        self.assertEqual(self.read(A_PATH).stops[0].side_files[0].text, "Layout only.")

    def test_the_path_sections_come_with_their_text_in_order_a_deeper_heading_being_text(self):
        path = self.read(A_PATH + "")

        self.assertEqual(path.sections, (Section("State flow", "### Not a question\nFree text."),))
        two = self.read("## 1 `a.py`\n\n### A?\nx\n\n## Section: One\nfirst\n\n```\n## 2 `b.py`\n```\n\n"
                        "## Section: Two words\nsecond\n\n## Skipped\n")
        self.assertEqual(two.sections, (Section("One", "first\n\n```\n## 2 `b.py`\n```"), Section("Two words", "second")))

    def test_a_stop_links_to_the_sections_its_answers_point_to_by_name(self):
        path = self.read('## 1 `a.py`\n\n### A?\nSee "State flow".\n\n### B?\nAlso see "Events" and "State flow" and "Nowhere".\n\n'
                         '## 1.1 `b.py`\n\n### C?\nplain\n\n## Section: Events\ne\n\n## Section: State flow\ns\n')

        self.assertEqual(path.stops[0].see, ("State flow", "Events"))
        self.assertEqual(path.stops[0].children[0].see, ())

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

    def test_a_file_that_is_a_stop_and_a_side_file_is_named_twice(self):
        text = "## 1 `app.py`\n\n### Why?\nBecause.\n\n### Side file: `app.py`\n"

        self.assertIn("twice", self.problem(text, {"app.py": "x\n"}))

    def test_a_heading_inside_a_code_block_is_not_checked(self):
        text = "## 1 `app.py`\n\n### Why?\n```\n## not a heading\n```\n"

        self.assertIsNone(self.problem(text, {"app.py": "x\n"}))

    def test_a_fixed_file_has_no_problem_on_the_next_read(self):
        code = self.code("## 1 `src/gone.ts`\n\n### Why?\nBecause.\n")
        self.assertIsNotNone(review_path_problem(code))

        code.review_path = A_PATH

        self.assertIsNone(review_path_problem(code))
        self.assertEqual(len(list(read_review_path(self.store, code, self.history).all_stops())), 3)

    def test_while_another_branch_is_checked_out_the_file_is_its_and_has_no_problem_here(self):
        code = FakeCode(CHANGED, base={}, review_path="## 1 `src/gone.ts`\n", on_branch=False)

        self.assertIsNone(review_path_problem(code))

    def test_checking_a_path_writes_nothing(self):
        self.problem("## 1 `src/gone.ts`\n")

        self.assertEqual(self.store.load(), [])


class AnOutOfDateReviewPath(unittest.TestCase):
    """review-path.md naming a file that has no changes (a stop, a side file or
    a skipped file): the path is out of date, not broken. It is read, each such
    entry marked not in the changeset, and review_path_problem names the files
    for a warning asking for the path to be rewritten."""

    def setUp(self):
        self.store = MemoryStore()
        self.history = FakeHistory()

    def code(self, text, files=None):
        return FakeCode(files or CHANGED, base={}, review_path=text)

    def read(self, text, files=None):
        return read_review_path(self.store, self.code(text, files), self.history)

    def test_a_stop_whose_file_has_no_changes_is_on_the_path_marked_not_in_the_changeset(self):
        path = self.read("## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n## 2 `src/gone.ts`\n\n### Why?\nBecause.\n")

        self.assertEqual([(s.file, s.in_changeset) for s in path.all_stops()],
                         [("src/cards/Card.tsx", True), ("src/gone.ts", False)])
        self.assertEqual(path.stops[1].questions, (Question("Why?", "Because."),))

    def test_the_problem_names_every_file_with_no_changes_first_and_asks_for_a_rewrite(self):
        text = ("## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n### Side file: `gone.css`\n\n"
                "## 2 `src/gone.ts`\n\n### Why?\nBecause.\n\n## Skipped\n- `yarn.lock` — lockfile only\n")

        self.assertEqual(review_path_problem(self.code(text)),
                         "review-path.md is out of date: `gone.css`, `src/gone.ts`, `yarn.lock` have no changes."
                         " Ask the agent to rewrite it")

    def test_one_file_has_no_changes(self):
        text = "## 1 `src/cards/Card.tsx`\n\n### Why?\nBecause.\n\n### Side file: `gone.css`\n"

        self.assertEqual(review_path_problem(self.code(text)),
                         "review-path.md is out of date: `gone.css` has no changes. Ask the agent to rewrite it")

    def test_a_path_out_of_shape_is_still_not_used(self):
        text = "## 1 `src/gone.ts`\n\n### Why?\nB.\n\n## 2 `src/gone.ts`\n\n### Why?\nB.\n"

        self.assertTrue(review_path_problem(self.code(text)).startswith("review-path.md is not used"))


class TheReviewPathInAView(unittest.TestCase):
    """In a view other than all changes the path is cut down to the view's
    files: stops and side files in the view, numbers kept; not on the path and
    skipped are the view's files only."""

    TEXT = ("## 1 `a.py`\n\n### A?\nx\n\n### Side file: `a.css`\n\n"
            "## 1.1 `b.py`\n\n### B?\nx\n\n## 2 `c.py`\n\n### C?\nx\n\n"
            "## 3 `d.py`\n\n### D?\nx\n\n## 4 `e.py`\n\n### E?\nx\n\n### Side file: `e.css`\n\n"
            "## Skipped\n- `uv.lock` — lockfile only\n- `gen.py` — generated\n")
    ALL = {f: "new\n" for f in ("a.py", "a.css", "b.py", "c.py", "d.py", "e.py", "e.css", "uv.lock", "gen.py", "x.md", "y.md")}

    def setUp(self):
        self.store = MemoryStore()
        self.history = FakeHistory()

    def read(self, in_view, view="commit-1", text=None):
        """The path in <view>, which holds the files <in_view> of the changeset."""
        code = FakeCode(self.ALL, base={}, review_path=text or self.TEXT, views={view: {f: "new\n" for f in in_view}})
        return read_review_path(self.store, code, self.history, view)

    def test_a_commit_view_keeps_the_stop_and_its_side_file_with_its_number_and_hides_the_rest(self):
        path = self.read(["e.py", "e.css"])

        self.assertEqual([(s.number, s.file) for s in path.all_stops()], [("4", "e.py")])
        self.assertEqual(path.stops[0].side_files, (SideFile("e.css"),))

    def test_the_numbers_are_the_whole_paths_so_a_gap_stays_a_gap(self):
        path = self.read(["a.py", "d.py"])

        self.assertEqual([s.number for s in path.all_stops()], ["1", "3"])

    def test_not_on_the_path_is_the_views_files_the_path_names_nowhere(self):
        path = self.read(["e.py", "x.md"])

        self.assertEqual(path.not_on_the_path, ("x.md",))

    def test_skipped_files_are_the_views_only(self):
        path = self.read(["e.py", "gen.py"])

        self.assertEqual(path.skipped, (Skipped("gen.py", "generated"),))

    def test_a_stop_outside_the_view_hides_but_the_stop_under_it_in_the_view_stays_with_its_number(self):
        path = self.read(["b.py", "c.py"])

        self.assertEqual([(s.number, s.file) for s in path.stops], [("1.1", "b.py"), ("2", "c.py")])

    def test_a_side_file_in_the_view_whose_stop_is_not_is_not_lost_it_is_listed_as_not_on_the_path(self):
        path = self.read(["a.css", "e.py"])

        self.assertEqual([s.file for s in path.stops], ["e.py"])
        self.assertEqual(path.not_on_the_path, ("a.css",))

    def test_a_view_with_no_file_the_path_names_has_no_stops(self):
        path = self.read(["x.md"])

        self.assertEqual(path.stops, ())
        self.assertEqual(path.skipped, ())
        self.assertEqual(path.not_on_the_path, ("x.md",))

    def test_viewed_marks_are_kept_in_the_view(self):
        code = FakeCode(self.ALL, base={}, review_path=self.TEXT, views={"commit-1": {"e.py": "new\n", "e.css": "new\n"}})
        mark_viewed(self.store, code, self.history, "e.css", True)

        path = read_review_path(self.store, code, self.history, "commit-1")

        self.assertEqual(path.stops[0].side_files, (SideFile("e.css", viewed=True),))

    def test_all_changes_and_no_view_are_the_whole_path(self):
        code = FakeCode(self.ALL, base={}, review_path=self.TEXT)

        whole = read_review_path(self.store, code, self.history)

        self.assertEqual(read_review_path(self.store, code, self.history, ""), whole)
        self.assertEqual([s.number for s in whole.all_stops()], ["1", "1.1", "2", "3", "4"])

    def test_a_broken_file_is_broken_in_a_view_too(self):
        with self.assertRaises(BadReviewPath):
            self.read(["a.py"], text="## 1 `a.py`\n\n### Why?\nBecause.\n\n## 2 `a.py`\n\n### Why?\nBecause.\n")

    def test_a_file_with_no_changes_is_in_no_view_but_stays_on_the_path_in_every_view(self):
        text = ("## 1 `a.py`\n\n### A?\nx\n\n### Side file: `gone.css`\n\n## 2 `gone.py`\n\n### Why?\nx\n\n"
                "## 3 `c.py`\n\n### C?\nx\n\n## Skipped\n- `gone.lock` — lockfile only\n")

        path = self.read(["a.py"], text=text)

        self.assertEqual([(s.number, s.file, s.in_changeset) for s in path.stops],
                         [("1", "a.py", True), ("2", "gone.py", False)])
        self.assertEqual(path.stops[0].side_files, (SideFile("gone.css", in_changeset=False),))
        self.assertEqual(path.skipped, (Skipped("gone.lock", "lockfile only", in_changeset=False),))
        self.assertEqual(path.not_on_the_path, ())

    def test_a_name_that_is_no_view_is_not_found(self):
        code = FakeCode(self.ALL, base={}, review_path=self.TEXT)

        with self.assertRaises(NotFound):
            read_review_path(self.store, code, self.history, "nowhere")


if __name__ == "__main__":
    unittest.main()
