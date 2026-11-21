"""The browser's side of a review's warnings (#161): the page shows each warning once.
The page's code is a module, so node runs it; no browser, no watcher."""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARNINGS_JS = os.path.join(ROOT, "lib", "difftate", "adapters", "inbound", "review_api", "web", "warnings.js")
APP_JS = os.path.join(ROOT, "lib", "difftate", "adapters", "inbound", "review_api", "web", "app.js")


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheBrowserShowsEachWarningOnce(unittest.TestCase):
    def unseen(self, polls):
        """What the page would show for each poll of /api/review, in order."""
        script = (f"import {{ unseen }} from {json.dumps('file://' + WARNINGS_JS)};\n"
                  f"const seen = new Set();\n"
                  f"console.log(JSON.stringify({json.dumps(polls)}.map((w) => unseen(w, seen).map((x) => x.id))));")
        run = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_a_warning_is_shown_on_the_poll_that_brings_it_and_not_again(self):
        one = {"id": "w1", "time": "2026-01-02T03:04:05+00:00", "text": "restored"}
        two = {"id": "w2", "time": "2026-01-02T03:04:09+00:00", "text": "restored again"}

        self.assertEqual(self.unseen([[], [one], [one], [one, two], [one, two]]),
                         [[], ["w1"], [], ["w2"], []])

    def test_an_answer_without_warnings_shows_nothing(self):
        self.assertEqual(self.unseen([None, []]), [[], []])

    def test_the_page_uses_it_on_every_review_it_reads(self):
        with open(APP_JS) as f:
            source = f.read()
        self.assertIn('import { unseen } from "./warnings.js"', source)
        self.assertIn("unseen(review.warnings", source)


if __name__ == "__main__":
    unittest.main()
