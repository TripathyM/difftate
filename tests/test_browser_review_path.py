"""The browser's side of the review path (#186): its file list follows the path like
<leader>rf, and a selected file shows its stop above the diff. The drawing is one module
(web/review_path.js) that node runs; no browser, no watcher, no files written."""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "lib", "difftate", "adapters", "inbound", "review_api", "web")
MODULE = os.path.join(WEB, "review_path.js")


def stop(number, file, **more):
    return dict({"number": number, "file": file, "key": False, "viewed": False, "questions": [], "ranges": [],
                 "specs": [], "see": [], "side_files": [], "children": []}, **more)


# what GET /api/review-path answers for a made-up change: a loading view with a tip under it
WRITTEN = {
    "stops": [
        stop("1", "src/loader.py", key=True,
             questions=[{"question": "What does load do?", "answer": "It reads the cache."},
                        {"question": "How is it built?", "answer": "With a dict."}],
             specs=[{"file": "tests/test_loader.py", "name": "reads the cache"}], see=["State flow"],
             side_files=[{"file": "src/cache.py", "viewed": False, "ranges": [[3, 9]], "text": "the store"}],
             children=[stop("2", "src/tips.py", questions=[{"question": "Which tip shows?", "answer": "The next."}])]),
        stop("3", "src/view.py", questions=[{"question": "Where is it drawn?", "answer": "In the panel."}]),
    ],
    "skipped": [{"file": "uv.lock", "reason": "lockfile only"}],
    "not_on_the_path": ["notes.txt"],
    "sections": [{"name": "State flow", "text": "idle, then loading, then done"}],
}


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheBrowserDrawsTheReviewPath(unittest.TestCase):
    def run_js(self, body):
        script = f"import * as rp from {json.dumps('file://' + MODULE)};\n{body}"
        run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def rows(self, written):
        return self.run_js(f"console.log(JSON.stringify(rp.rows({json.dumps(written)}).map((r) => r.text)));")

    def test_the_file_list_is_in_path_order_as_a_tree_each_file_name_first_then_its_folder(self):
        self.assertEqual(self.rows(WRITTEN), [
            "1 loader.py ★  src",
            "├─ cache.py  src",
            "└─ 2 tips.py  src",
            "3 view.py  src",
            "Skipped",
            "└─ uv.lock — lockfile only",
            "Not on the path",
            "└─ notes.txt",
        ])

    def test_a_row_names_the_folder_it_ends_with_for_the_list_to_dim(self):
        folders = self.run_js(f"console.log(JSON.stringify(rp.rows({json.dumps(WRITTEN)}).map((r) => r.folder ?? null)));")
        self.assertEqual(folders, ["src", "src", "src", "src", None, "", None, ""])

    def test_with_no_path_there_are_no_rows(self):
        self.assertEqual(self.run_js("console.log(JSON.stringify(rp.rows(null)));"), [])

    def test_the_files_are_ordered_like_the_list_and_the_rest_keeps_its_order(self):
        files = [{"path": p} for p in ["notes.txt", "src/view.py", "uv.lock", "src/tips.py", "src/cache.py",
                                       "src/loader.py", "src/extra.py"]]
        got = self.run_js(f"console.log(JSON.stringify(rp.orderFiles({json.dumps(files)},"
                          f" rp.rows({json.dumps(WRITTEN)})).map((f) => f.path)));")
        self.assertEqual(got, ["src/loader.py", "src/cache.py", "src/tips.py", "src/view.py", "uv.lock",
                               "notes.txt", "src/extra.py"])

    def stop_text(self, file, written=WRITTEN):
        """The text of the block shown above a file's diff, flattened, and its class names."""
        return self.run_js(f"""
const el = (tag, props = {{}}, ...kids) => ({{ tag, class: props.class ?? "", text: props.text ?? "", kids: kids.flat().filter((k) => k !== null && k !== false && k !== undefined) }});
const flat = (n) => typeof n === "string" ? n : [n.text, ...n.kids.map(flat)].join(" ");
const block = rp.stopBlock({json.dumps(written)}, {json.dumps(file)}, el);
console.log(JSON.stringify(block && {{ class: block.class, text: flat(block).replace(/\\s+/g, " ").trim() }}));""")

    def test_a_stop_shows_its_questions_answers_specs_side_files_and_linked_section(self):
        got = self.stop_text("src/loader.py")
        self.assertIn("review-path-stop", got["class"])
        for text in ["1 src/loader.py", "What does load do?", "It reads the cache.", "How is it built?", "With a dict.",
                     "tests/test_loader.py", "reads the cache", "src/cache.py", "lines 3-9", "the store",
                     "State flow", "idle, then loading, then done"]:
            self.assertIn(text, got["text"])

    def test_a_side_file_names_its_stop(self):
        got = self.stop_text("src/cache.py")
        self.assertIn("Side file of 1 src/loader.py", got["text"])
        self.assertIn("the store", got["text"])

    def test_a_skipped_file_shows_its_reason_and_a_file_off_the_path_says_so(self):
        self.assertIn("lockfile only", self.stop_text("uv.lock")["text"])
        self.assertIn("not on the review path", self.stop_text("notes.txt")["text"].lower())

    def test_a_file_the_path_does_not_know_has_no_block(self):
        self.assertIsNone(self.stop_text("src/other.py"))

    def test_the_stop_has_its_own_style_unlike_a_thread(self):
        with open(os.path.join(WEB, "index.html")) as f:
            page = f.read()
        self.assertIn(".review-path-stop", page)
        self.assertNotIn("review-path-stop thread", page)

    def test_the_page_asks_for_the_path_in_the_shown_view_and_draws_it_with_the_module(self):
        with open(os.path.join(WEB, "app.js")) as f:
            source = f.read()
        self.assertIn('from "./review_path.js"', source)
        self.assertIn("/api/review-path?view=", source)
        self.assertIn("stopBlock(", source)
        self.assertIn("orderFiles(", source)


if __name__ == "__main__":
    unittest.main()
