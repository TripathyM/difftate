"""Layout D's unified diff (#257): the rows of one file of the changeset's diff
(web/d/diff_rows.js, over web/diff.js). Node runs it."""
import json
import shutil
import unittest

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
            {"kind": "line", "type": "delete", "old": 2, "new": None, "text": "    return 'hi ' + name"},
            {"kind": "line", "type": "add", "old": None, "new": 2, "text": "    return f'hello {name}'"},
        ])

    def test_a_file_with_no_lines_to_show_has_one_note_saying_why(self):
        diff = ("diff --git a/logo.png b/logo.png\nindex 1111111..2222222 100644\n"
                "Binary files a/logo.png and b/logo.png differ\n"
                "diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n")

        self.assertEqual(self.rows(diff, "logo.png"), [{"kind": "note", "text": "Binary file"}])
        self.assertEqual(self.rows(diff, "new.py"), [{"kind": "note", "text": "No changes to its lines"}])

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


if __name__ == "__main__":
    unittest.main()
