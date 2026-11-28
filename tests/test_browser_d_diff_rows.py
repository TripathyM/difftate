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


if __name__ == "__main__":
    unittest.main()
