"""Layout D's file tree (#257): the model of the tree beside the diff, from the changeset's files,
the threads, the viewed files and the filter (web/d/file_tree.js). Node runs it."""
import json
import shutil
import unittest

from browser_d import released, run_js


def thread(file, status="open", outdated=False):
    """A thread of the released transcript, about <file> (None: a general thread)."""
    one = released("GET", "/api/threads")[0]
    anchor = None if file is None else dict(one["anchor"], file=file)
    return dict(one, anchor=anchor, status=status, outdated=outdated)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheFileTree(unittest.TestCase):
    def rows(self, paths, **given):
        files = [{"path": p, "status": "modified"} for p in paths]
        return run_js("file_tree", f"console.log(JSON.stringify(m.treeRows({json.dumps(dict(given, files=files))})));")

    def shape(self, rows):
        return [f"{'  ' * r['depth']}{r['name']}{'/' if r['kind'] == 'folder' else ''}" for r in rows]

    def test_files_sit_in_their_folders_folders_first_then_by_name(self):
        rows = self.rows(["zeta.md", "src/view.py", "src/net/http.py", "docs/a.md", "README.md"])

        self.assertEqual(self.shape(rows), [
            "docs/", "  a.md",
            "src/", "  net/", "    http.py", "  view.py",
            "README.md", "zeta.md",
        ])
        self.assertEqual([r["path"] for r in rows if r["kind"] == "file"],
                         ["docs/a.md", "src/net/http.py", "src/view.py", "README.md", "zeta.md"])

    def test_the_filter_keeps_the_files_whose_path_has_the_text_and_their_folders(self):
        rows = self.rows(["docs/a.md", "src/net/http.py", "src/view.py"], filter="NET/")

        self.assertEqual(self.shape(rows), ["src/", "  net/", "    http.py"])

    def test_a_filter_no_path_has_gives_no_rows(self):
        self.assertEqual(self.rows(["src/view.py"], filter="zzz"), [])

    def test_a_file_counts_its_open_threads_outdated_ones_too_but_no_closed_or_general_one(self):
        threads = [thread("a.py"), thread("a.py", outdated=True), thread("a.py", status="resolved"),
                   thread("a.py", status="dismissed"), thread("b.py", status="resolved"), thread(None)]

        rows = self.rows(["a.py", "b.py"], threads=threads)

        self.assertEqual([(r["name"], r["openThreads"]) for r in rows], [("a.py", 2), ("b.py", 0)])

    def test_a_viewed_file_is_marked(self):
        rows = self.rows(["a.py", "b.py"], viewed=["b.py"])

        self.assertEqual([(r["name"], r["viewed"]) for r in rows], [("a.py", False), ("b.py", True)])

    def test_a_file_has_its_added_and_deleted_line_counts_by_folder_and_in_reading_order(self):
        files = [{"path": "a.py", "status": "modified", "additions": 12, "deletions": 3}]
        # gone.py: the path names it, the changeset doesn't have it, so there is nothing to count
        listed = [{"kind": "off", "file": "a.py"}, {"kind": "off", "file": "gone.py"}]

        got = run_js("file_tree", f"""console.log(JSON.stringify([null, {json.dumps(listed)}].map((listed) =>
  m.treeRows({{ files: {json.dumps(files)}, listed }}).map((r) => [r.path, r.counts]))));""")

        self.assertEqual(got, [[["a.py", {"additions": 12, "deletions": 3}]],
                               [["a.py", {"additions": 12, "deletions": 3}], ["gone.py", None]]])


if __name__ == "__main__":
    unittest.main()
