"""Layout D's unified diff (#257): the rows of one file of the changeset's diff
(web/d/diff_rows.js, over web/diff.js). Node runs it."""
import json
import shutil
import unittest
from unittest.mock import ANY

from browser_d import changed, released, run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheUnifiedDiffRows(unittest.TestCase):
    def rows(self, diff, path):
        return run_js("diff_rows", f"""
import {{ parseDiff }} from "{{DIFF}}";
console.log(JSON.stringify(m.diffRows(parseDiff({json.dumps(diff)}).find((f) => f.path === {json.dumps(path)}))));""")

    def test_a_hunk_header_then_each_line_with_its_old_and_new_numbers(self):
        diff = released("GET", "/api/changeset")["diff"]

        self.assertEqual(self.rows(diff, "app.py"), [
            {"kind": "hunk", "text": "@@ -1,2 +1,2 @@"},
            {"kind": "line", "type": "context", "old": 1, "new": 1, "text": "def greet(name):"},
            {"kind": "line", "type": "delete", "old": 2, "new": None, "text": "    return 'hi ' + name", "words": ANY},
            {"kind": "line", "type": "add", "old": None, "new": 2, "text": "    return f'hello {name}'", "words": ANY},
        ])

    def test_a_file_with_no_lines_to_show_has_one_note_saying_why(self):
        diff = ("diff --git a/logo.png b/logo.png\nindex 1111111..2222222 100644\n"
                "Binary files a/logo.png and b/logo.png differ\n"
                "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n")

        self.assertEqual(self.rows(diff, "logo.png"), [{"kind": "note", "text": "Binary file"}])
        self.assertEqual(self.rows(diff, "new.py"), [{"kind": "note", "text": "No changes to its lines"}])

@unittest.skipUnless(shutil.which("node"), "needs node")
class TheWordsChangedInPairedLines(unittest.TestCase):
    """A run of deleted lines and the added run after it pair line by line."""

    def marked(self, *lines, header="@@ -1,9 +1,9 @@"):
        """Each changed line of a hunk of <lines> as (sign, the parts of it that are highlighted)."""
        old = sum(not line.startswith("+") for line in lines)
        new = sum(not line.startswith("-") for line in lines)
        diff = changed("a.py", f"@@ -1,{old} +1,{new} @@", *lines)
        return [tuple(r) for r in run_js("diff_rows", f"""
import {{ parseDiff }} from "{{DIFF}}";
const rows = m.diffRows(parseDiff({json.dumps(diff)})[0]);
console.log(JSON.stringify(rows.filter((r) => r.kind === "line" && r.type !== "context")
  .map((r) => [r.type === "add" ? "+" : "-", (r.words ?? []).map(([a, b]) => r.text.slice(a, b))])));""")]

    def test_a_changed_word_is_highlighted_whole_on_both_lines(self):
        self.assertEqual(self.marked("-greet(name, count)", "+greet(user, count)"),
                         [("-", ["name"]), ("+", ["user"])])

    def test_two_edits_far_apart_on_a_line_are_two_highlights_not_all_between_them(self):
        self.assertEqual(self.marked("-total = add(first, second, 10)", "+count = add(first, second, 20)"),
                         [("-", ["total", "10"]), ("+", ["count", "20"])])

    def test_changed_words_with_only_blanks_between_them_are_one_highlight(self):
        self.assertEqual(self.marked("-if the old name is here:", "+if a new name is here:"),
                         [("-", ["the old"]), ("+", ["a new"])])

    def test_the_first_deleted_line_pairs_with_the_first_added_and_a_line_left_over_has_none(self):
        self.assertEqual(self.marked("-a = 1", "-b = 2", "+a = 10", "+b = 20", "+c = 30"),
                         [("-", ["1"]), ("-", ["2"]), ("+", ["10"]), ("+", ["20"]), ("+", [])])

    def test_lines_either_side_of_an_unchanged_one_do_not_pair(self):
        self.assertEqual(self.marked("-a = 1", " same", "+a = 2"), [("-", []), ("+", [])])

    def test_lines_with_little_in_common_are_not_a_small_edit_so_have_no_highlight(self):
        self.assertEqual(self.marked("-    raise ValueError(message)", "+# see the notes (later)"),
                         [("-", []), ("+", [])])

    def test_a_line_that_only_gained_words_highlights_them_on_the_new_line_alone(self):
        self.assertEqual(self.marked("-def greet(name):", "+def greet(name, loud=False):"),
                         [("-", []), ("+", [", loud=False"])])

    def test_a_changed_indent_is_highlighted(self):
        self.assertEqual(self.marked("-  return name", "+      return name"), [("-", ["  "]), ("+", ["      "])])

    def test_a_very_long_line_is_not_compared_so_the_page_stays_quick(self):
        line = " ".join(f"v{n}" for n in range(3000))

        self.assertEqual(self.marked(f"-old {line} end", f"+new {line} done"), [("-", []), ("+", [])])


def thread(id, side, start, end, file="app.py", code="x", **changes):
    """One thread as GET /api/threads gives it: the released transcript's first, on other lines."""
    first = released("GET", "/api/threads", lambda a: a)[0]
    anchor = dict(first["anchor"], file=file, side=side, startLine=start, endLine=end, code=code)
    return dict(first, id=id, anchor=anchor, **changes)

def draft(key, side, start, end, code, path="app.py"):
    """A draft as web/d/drafts.js keeps it."""
    return {"key": key, "text": "words", "anchor": {"path": path, "side": side, "start": start, "end": end, "code": code}}


@unittest.skipUnless(shutil.which("node"), "needs node")
class WhereThreadsAndDraftsSit(unittest.TestCase):
    # app.py: line 1 is unchanged, line 2 is deleted and added
    def placed(self, threads=(), drafts=(), diff=None, path="app.py"):
        """(what is at the file's top, the rows in short: a line as "old,new", and what is under it)."""
        diff = diff or released("GET", "/api/changeset")["diff"]
        return run_js("diff_rows", f"""
import {{ parseDiff }} from "{{DIFF}}";
const file = parseDiff({json.dumps(diff)}).find((f) => f.path === {json.dumps(path)});
const {{ top, rows }} = m.withThreads(m.diffRows(file),
  {{ path: file.path, threads: {json.dumps(list(threads))}, drafts: {json.dumps(list(drafts))} }});
const ids = (at) => [...at.threads.map((t) => t.id), ...at.drafts.map((d) => d.key)];
console.log(JSON.stringify([ids(top), rows.filter((r) => r.kind !== "hunk").map((r) =>
  (r.kind === "below" ? ids(r) : `${{r.old ?? ""}},${{r.new ?? ""}}`))]));""")

    def test_a_thread_sits_under_the_line_its_anchor_ends_on_on_its_side(self):
        got = self.placed([thread("on-old", "old", 2, 2), thread("on-new", "new", 1, 2),
                           thread("other-file", "new", 1, 1, file="long.py")])

        self.assertEqual(got, [[], ["1,1", "2,", ["on-old"], ",2", ["on-new"]]])

    def test_a_thread_whose_last_lines_the_diff_leaves_out_sits_under_the_last_one_it_shows(self):
        got = self.placed([thread("partly", "new", 2, 4)])

        self.assertEqual(got, [[], ["1,1", "2,", ",2", ["partly"]]])

    def test_an_outdated_thread_goes_to_its_files_top_never_to_the_line_that_is_there_now(self):
        got = self.placed([thread("old-code", "new", 2, 2, outdated=True)])

        self.assertEqual(got, [["old-code"], ["1,1", "2,", ",2"]])

    def test_a_thread_this_view_has_no_line_for_is_not_on_the_files_rows_or_its_top(self):
        # inView false: the view hasn't its code, though its numbers name a line the diff shows
        got = self.placed([thread("other-view", "new", 2, 2, inView=False), thread("no-hunk", "new", 40, 41)])

        # the Conversation tab lists them
        self.assertEqual(got, [[], ["1,1", "2,", ",2"]])

    def test_a_draft_sits_under_its_last_line_while_its_lines_hold_the_code_it_was_started_on(self):
        got = self.placed([thread("t", "new", 2, 2)], [
            draft("lines-1-2", "new", 1, 2, "def greet(name):\n    return f'hello {name}'"),
            draft("old-1", "old", 1, 1, "def greet(name):"),
            draft("other-file", "new", 1, 1, "def greet(name):", path="long.py")])

        self.assertEqual(got, [[], ["1,1", ["old-1"], "2,", ",2", ["t", "lines-1-2"]]])

    def test_a_draft_whose_lines_changed_or_left_the_diff_goes_to_the_top_never_onto_them(self):
        got = self.placed(drafts=[
            draft("changed", "new", 2, 2, "    return name"),
            draft("one-line-gone", "new", 2, 3, "    return f'hello {name}'\n")])

        self.assertEqual(got, [["changed", "one-line-gone"], ["1,1", "2,", ",2"]])

@unittest.skipUnless(shutil.which("node"), "needs node")
class TheSplitRows(unittest.TestCase):
    def split(self, diff, path, threads=(), drafts=()):
        """The split rows of the file in short: a line as "left | right", each half its number
        and sign, and what sits under a line as (its ids, the old side's first)."""
        return run_js("diff_rows", f"""
import {{ parseDiff }} from "{{DIFF}}";
const file = parseDiff({json.dumps(diff)}).find((f) => f.path === {json.dumps(path)});
const {{ rows }} = m.withThreads(m.diffRows(file),
  {{ path: file.path, threads: {json.dumps(list(threads))}, drafts: {json.dumps(list(drafts))} }});
const half = (h, n) => (h ? `${{n}}${{h.type === "add" ? "+" : h.type === "delete" ? "-" : ""}}` : "");
console.log(JSON.stringify(m.splitRows(rows).map((r) => (r.kind === "line" ? `${{half(r.left, r.old)}} | ${{half(r.right, r.new)}}`
  : r.kind === "below" ? [...r.threads.map((t) => t.id), ...r.drafts.map((d) => d.key)] : r.kind))));""")

    def hunk(self, *lines):
        old = sum(not line.startswith("+") for line in lines)
        new = sum(not line.startswith("-") for line in lines)
        return changed("app.py", f"@@ -1,{old} +1,{new} @@", *lines)

    def test_an_unchanged_line_is_on_both_sides_and_a_deleted_run_is_beside_the_added_run_after_it(self):
        got = self.split(self.hunk(" a", "-b", "-c", "+B", "+C", " d"), "app.py")

        self.assertEqual(got, ["hunk", "1 | 1", "2- | 2+", "3- | 3+", "4 | 4"])

    def test_a_longer_run_leaves_the_other_side_empty(self):
        got = self.split(self.hunk("-a", "+A", "+B", " c", "-d", "-e", "+D", " f", "+g", " h", "-i"), "app.py")

        self.assertEqual(got, ["hunk", "1- | 1+", " | 2+", "2 | 3", "3- | 4+", "4- | ", "5 | 5",
                               " | 6+", "6 | 7", "7- | "])

    def test_runs_that_follow_each_other_pair_within_themselves_and_hunks_stay_apart(self):
        diff = changed("app.py", "@@ -1,2 +1,2 @@", "-a", "+A", "-b", "+B", "@@ -10 +10 @@", "-c", "+C")

        self.assertEqual(self.split(diff, "app.py"), ["hunk", "1- | 1+", "2- | 2+", "hunk", "10- | 10+"])

    def test_a_file_with_no_lines_keeps_its_note(self):
        diff = "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"

        self.assertEqual(self.split(diff, "logo.png"), ["note"])

    def test_each_half_has_its_own_text_and_the_words_changed_from_its_pair(self):
        diff = self.hunk("-greet(name)", "+greet(user)")

        rows = run_js("diff_rows", f"""
import {{ parseDiff }} from "{{DIFF}}";
console.log(JSON.stringify(m.splitRows(m.diffRows(parseDiff({json.dumps(diff)})[0]))));""")

        self.assertEqual(rows[1], {"kind": "line", "old": 1, "new": 1,
                                   "left": {"type": "delete", "text": "greet(name)", "words": [[6, 10]]},
                                   "right": {"type": "add", "text": "greet(user)", "words": [[6, 10]]}})

    def test_threads_and_drafts_stay_on_their_lines_under_the_pair_that_has_them_old_side_first(self):
        # unified puts the added line 1 after both deleted ones; split puts it beside the first
        diff = self.hunk("-a", "-b", "+A", "+B", " c")

        got = self.split(diff, "app.py", [thread("new-1", "new", 1, 1), thread("old-1", "old", 1, 1),
                                          thread("old-2", "old", 2, 2), thread("context", "new", 3, 3),
                                          thread("context-old", "old", 3, 3)],
                         [draft("on-new-2", "new", 2, 2, "B"), draft("on-old-1", "old", 1, 1, "a")])

        self.assertEqual(got, ["hunk",
                               "1- | 1+", ["old-1", "new-1", "on-old-1"],
                               "2- | 2+", ["old-2", "on-new-2"],
                               "3 | 3", ["context-old", "context"]])


if __name__ == "__main__":
    unittest.main()
