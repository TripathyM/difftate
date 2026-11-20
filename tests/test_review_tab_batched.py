"""Seam: the Review tab's batched mode (herdr/mods/difftate/batched.js).

The Herdr mod has no test runner of its own, and main.js needs Herdr to load.
batched.js is plain JavaScript, so node runs it here: each test hands it what
GET /api/mode answers (api.js mode()) and reads back what the tab would show or
say. Skipped where node isn't installed.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCHED_JS = os.path.join(ROOT, "herdr", "mods", "difftate", "batched.js")
NODE = shutil.which("node")


def mode(name="batched", held=0):
    """What GET /api/mode answers."""
    return {"mode": name, "held": [f"t{i}" for i in range(held)]}


def run(call, **args):
    """The value of batched.js's <call>, given <args> as JSON."""
    script = (
        "const m = await import(process.argv[1]);\n"
        "const a = JSON.parse(process.argv[2]);\n"
        f"const out = ({call});\n"
        "process.stdout.write(JSON.stringify(out ?? null));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script, "file://" + BATCHED_JS, json.dumps(args)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't installed")
class TheReviewMode(unittest.TestCase):
    def test_a_batched_review_shows_how_many_threads_are_held(self):
        self.assertEqual(run("m.modeLabel(a.mode)", mode=mode(held=2)), "Batched · 2 held")
        self.assertEqual(run("m.modeLabel(a.mode)", mode=mode(held=0)), "Batched · 0 held")

    def test_a_live_review_shows_nothing_for_it_holds_nothing(self):
        self.assertIsNone(run("m.modeLabel(a.mode)", mode=mode("live")))

    def test_a_watcher_with_no_mode_shows_nothing(self):
        self.assertIsNone(run("m.modeLabel(a.mode)", mode=None))

    def test_the_toggle_goes_to_the_other_mode(self):
        self.assertEqual(run("m.otherMode(a.mode)", mode=mode("live")), "batched")
        self.assertEqual(run("m.otherMode(a.mode)", mode=mode("batched")), "live")

    def test_a_held_thread_is_called_held_until_you_submit(self):
        self.assertEqual(run("m.STATE_LABEL.held"), "held until you submit")
        self.assertEqual(run("m.STATE_LABEL.waiting"), "waiting for agent")


@unittest.skipUnless(NODE, "node isn't installed")
class ChangingTheMode(unittest.TestCase):
    def test_changing_to_batched_says_comments_are_held(self):
        self.assertEqual(run("m.modeChangedMessage('batched', [])"), "Batched: comments are held until you submit")

    def test_changing_to_live_says_how_many_threads_it_submitted(self):
        self.assertEqual(run("m.modeChangedMessage('live', ['a', 'b'])"), "Live: 2 held threads submitted to the coding agent")
        self.assertEqual(run("m.modeChangedMessage('live', ['a'])"), "Live: 1 held thread submitted to the coding agent")

    def test_changing_to_live_with_nothing_held_says_comments_go_on_as_written(self):
        self.assertEqual(run("m.modeChangedMessage('live', [])"), "Live: comments go to the coding agent as you write them")
        self.assertEqual(run("m.modeChangedMessage('live', undefined)"), "Live: comments go to the coding agent as you write them")


@unittest.skipUnless(NODE, "node isn't installed")
class Submitting(unittest.TestCase):
    def test_held_threads_can_be_submitted(self):
        self.assertIsNone(run("m.submitProblem(a.mode)", mode=mode(held=1)))

    def test_nothing_held_does_nothing_and_says_so(self):
        self.assertEqual(run("m.submitProblem(a.mode)", mode=mode(held=0)), "Nothing is held: nothing to submit")

    def test_a_live_review_has_nothing_to_submit(self):
        self.assertIn("nothing to submit", run("m.submitProblem(a.mode)", mode=mode("live")))

    def test_a_submit_says_how_many_threads_it_sent(self):
        self.assertEqual(run("m.submittedMessage(['a', 'b'])"), "Submitted 2 held threads")
        self.assertEqual(run("m.submittedMessage(['a'])"), "Submitted 1 held thread")

    def test_a_submit_that_found_nothing_held_says_so(self):
        self.assertEqual(run("m.submittedMessage([])"), "Nothing is held: nothing to submit")


@unittest.skipUnless(NODE, "node isn't installed")
class WritingAComment(unittest.TestCase):
    def test_in_a_batched_review_the_comment_is_held(self):
        self.assertEqual(run("m.commentMessage(a.mode, 'thread')", mode=mode()), "Comment held until you submit")
        self.assertEqual(run("m.commentMessage(a.mode, 'reply')", mode=mode()), "Comment held until you submit")

    def test_in_a_live_review_the_comment_is_sent(self):
        self.assertTrue(run("m.commentMessage(a.mode, 'thread')", mode=mode("live")).startswith("Comment sent"))
        self.assertEqual(run("m.commentMessage(a.mode, 'reply')", mode=mode("live")), "Comment sent")


if __name__ == "__main__":
    unittest.main()
