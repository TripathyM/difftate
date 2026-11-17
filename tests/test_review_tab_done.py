"""Seam: the Review tab's Done action (herdr/mods/difftate/done.js).

The Herdr mod has no test runner of its own, and main.js needs Herdr to load.
done.js is plain JavaScript, so node runs it here: each test hands it what
GET /api/done answers (api.js done()) and reads back what the tab would show or
ask. Skipped where node isn't installed.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DONE_JS = os.path.join(ROOT, "herdr", "mods", "difftate", "done.js")
NODE = shutil.which("node")
SHA = "0123456789abcdef0123456789abcdef01234567"


def status(done=False, open_threads=0, in_flight=0, **rest):
    """What GET /api/done answers, as api.js flattens it."""
    return {"done": done, "commit": SHA if done else None, "time": "2026-11-17T10:00:00.000Z" if done else None,
            "head": SHA, "lastMark": None, "openThreads": open_threads, "runsInFlight": in_flight, **rest}


def run(call, **args):
    """The value of done.js's <call>, given <args> as JSON."""
    script = (
        "const m = await import(process.argv[1]);\n"
        "const a = JSON.parse(process.argv[2]);\n"
        f"const out = ({call});\n"
        "process.stdout.write(JSON.stringify(out ?? null));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script, "file://" + DONE_JS, json.dumps(args)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't installed")
class TheDoneAction(unittest.TestCase):
    def test_a_done_review_shows_done_at_the_short_commit(self):
        self.assertEqual(run("m.doneLabel(a.status)", status=status(done=True)), "Done at 0123456")

    def test_a_review_that_is_not_done_shows_nothing(self):
        self.assertIsNone(run("m.doneLabel(a.status)", status=status()))

    def test_nothing_open_has_nothing_to_warn_about(self):
        self.assertEqual(run("m.doneWarnings(a.status)", status=status()), [])

    def test_every_open_thread_is_counted_in_one_line(self):
        self.assertEqual(run("m.doneWarnings(a.status)", status=status(open_threads=2)), ["2 threads still open"])
        self.assertEqual(run("m.doneWarnings(a.status)", status=status(open_threads=1)), ["1 thread still open"])

    def test_a_thread_with_a_run_queued_or_working_gets_its_own_line(self):
        self.assertEqual(run("m.doneWarnings(a.status)", status=status(open_threads=2, in_flight=1)),
                         ["2 threads still open", "1 run still working"])
        self.assertEqual(run("m.doneWarnings(a.status)", status=status(open_threads=3, in_flight=2)),
                         ["3 threads still open", "2 runs still working"])

    def test_the_question_names_the_warnings_and_asks_to_mark_done_anyway(self):
        self.assertEqual(run("m.doneQuestion(a.status)", status=status(open_threads=2, in_flight=1)),
                         "2 threads still open · 1 run still working. Mark Done anyway?")

    def test_with_nothing_to_warn_about_there_is_no_question(self):
        self.assertIsNone(run("m.doneQuestion(a.status)", status=status()))


if __name__ == "__main__":
    unittest.main()
