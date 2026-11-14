"""Seam: the Review tab's thread lists (herdr/mods/difftate/threads.js).

The Herdr mod has no test runner of its own, and main.js needs Herdr to load.
threads.js is plain JavaScript, so node runs it here: each test hands it
threads as the API flattens them (api.js viewThread) and reads back what the
tab would list. Skipped where node isn't installed.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THREADS_JS = os.path.join(ROOT, "herdr", "mods", "difftate", "threads.js")
NODE = shutil.which("node")


def thread(id, file=None, line=0, status="open", **rest):
    return {"id": id, "filePath": file, "side": "new", "startLine": line, "endLine": line,
            "status": status, "inView": True, "outdated": False, "comments": [], **rest}


def files(*paths):
    return [{"path": p} for p in paths]


def run(call, **args):
    """The value of threads.js's <call>, given <args> as JSON."""
    script = (
        "const m = await import(process.argv[1]);\n"
        "const a = JSON.parse(process.argv[2]);\n"
        f"const out = ({call});\n"
        "process.stdout.write(JSON.stringify(out ?? null));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script, "file://" + THREADS_JS, json.dumps(args)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def ids(threads):
    return [t["id"] for t in threads]


@unittest.skipUnless(NODE, "node isn't installed")
class TheThreadsPicker(unittest.TestCase):
    def test_general_threads_come_first_in_a_group_of_their_own(self):
        threads = [thread("f1", "b.py", 3), thread("g1"), thread("f2", "a.py", 9),
                   thread("g2", status="resolved"), thread("g3"), thread("f3", "a.py", 1, status="resolved")]
        groups = run("m.pickerThreads(a.threads, a.files)", threads=threads, files=files("a.py", "b.py"))
        self.assertEqual([ids(t) for t in groups], [["g1", "g3", "g2"], ["f2", "f1", "f3"]])

    def test_without_general_threads_the_general_group_is_empty(self):
        threads = [thread("f1", "b.py", 3), thread("f2", "a.py", 9), thread("f3", "a.py", 1, status="resolved")]
        groups = run("m.pickerThreads(a.threads, a.files)", threads=threads, files=files("a.py", "b.py"))
        self.assertEqual([ids(t) for t in groups], [[], ["f2", "f1", "f3"]])

    def test_a_general_thread_is_labelled_general_and_a_file_thread_by_its_lines(self):
        self.assertEqual(run("m.threadPlace(a.t)", t=thread("g1")), "general")
        self.assertEqual(run("m.threadPlace(a.t)", t={**thread("f1", "a.py", 3), "startLine": 2}), "a.py:2-3")
        self.assertEqual(run("m.threadPlace(a.t)", t=thread("f1", "a.py", 3)), "a.py:3")


@unittest.skipUnless(NODE, "node isn't installed")
class NextThread(unittest.TestCase):
    """]d and [d: open threads in review order, general ones before the files."""

    THREADS = [thread("f1", "b.py", 3), thread("g1"), thread("f2", "a.py", 9), thread("g2"),
               thread("gx", status="resolved")]
    FILES = files("a.py", "b.py")

    def step(self, here, d):
        return run("m.stepThread(m.openThreads(a.threads, a.files), a.files, a.here, a.d)?.id",
                   threads=self.THREADS, files=self.FILES, here=here, d=d)

    def test_open_threads_in_review_order_start_with_the_general_ones(self):
        self.assertEqual(ids(run("m.openThreads(a.threads, a.files)", threads=self.THREADS, files=self.FILES)),
                         ["g1", "g2", "f2", "f1"])

    def test_from_a_file_the_next_thread_is_further_down_the_files(self):
        self.assertEqual(self.step({"path": "a.py", "line": 1}, 1), "f2")
        self.assertEqual(self.step({"path": "a.py", "line": 10}, 1), "f1")

    def test_past_the_last_thread_the_next_one_is_the_first_general_thread(self):
        self.assertEqual(self.step({"path": "b.py", "line": 5}, 1), "g1")

    def test_from_a_general_thread_the_next_is_the_next_general_one_then_the_files(self):
        self.assertEqual(self.step({"general": "g1"}, 1), "g2")
        self.assertEqual(self.step({"general": "g2"}, 1), "f2")

    def test_back_from_the_first_file_thread_is_the_last_general_thread(self):
        self.assertEqual(self.step({"path": "a.py", "line": 9}, -1), "g2")
        self.assertEqual(self.step({"general": "g2"}, -1), "g1")
        self.assertEqual(self.step({"general": "g1"}, -1), "f1")

    def test_in_the_general_threads_with_none_picked_the_next_is_the_first(self):
        self.assertEqual(self.step({"general": None}, 1), "g1")
        self.assertEqual(self.step({"general": None}, -1), "f1")


if __name__ == "__main__":
    unittest.main()
