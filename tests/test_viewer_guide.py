"""Seam: the `difftate` command (`difftate --guide`), #233 and ADR 0010.

`difftate --guide` prints the viewer guide, whose one source is
docs/viewer-guide.md. Each test runs it in a temporary HOME and a temporary
difftate folder (DIFFTATE_HOME), from a folder that is no git repository and
with no watcher running: nothing here touches the real ~/.difftate.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_review_api import RELEASED, no_such_call, route_of  # noqa: E402
from test_watcher import DIFFTATE, ROOT  # noqa: E402

GUIDE = os.path.join(ROOT, "docs", "viewer-guide.md")


class ViewerGuideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="difftate-guide-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home, difftate_home = os.path.join(self.tmp, "home"), os.path.join(self.tmp, "difftate-home")
        self.outside = os.path.join(self.tmp, "not-a-repository")
        for d in (home, difftate_home, self.outside):
            os.makedirs(d)
        with open(os.path.join(difftate_home, "agents.toml"), "w") as f:
            f.write('[agents.nothing]\ntool = "claude"\ncmd = "/usr/bin/true"\n')
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("DT_OPEN", "DT_INTERVAL", "DT_RUN_DIR", "XDG_CONFIG_HOME")
                    and not k.startswith("GIT_")}
        self.env.update(HOME=home, DIFFTATE_HOME=difftate_home, GIT_CEILING_DIRECTORIES=self.tmp)

    def difftate(self, *args):
        return subprocess.run([sys.executable, DIFFTATE, *args], cwd=self.outside, env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)

    def guide(self):
        run = self.difftate("--guide")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout

    def test_it_prints_the_repositorys_copy_with_no_watcher_and_outside_a_repository(self):
        with open(GUIDE, encoding="utf-8") as f:
            self.assertEqual(self.guide(), f.read())
        self.assertFalse(os.path.exists(os.path.join(self.env["DIFFTATE_HOME"], "api.json")),
                         "no watcher was started")

    def test_it_names_every_route_of_the_released_review_api(self):
        """A route added to the API and released fails here until the viewer guide names it."""
        with open(RELEASED, encoding="utf-8") as f:
            routes = sorted({route_of(*s["request"][:2]) for s in json.load(f) if not no_such_call(s)})
        self.assertGreater(len(routes), 20)
        guide = self.guide()

        self.assertEqual([r for r in routes if f"`{r}`" not in guide], [])

    def test_its_sections_come_in_order_and_each_capability_has_what_it_is_its_calls_and_its_rules(self):
        guide = self.guide()
        headings = re.findall(r"^#{2,3} (.+)$", guide, re.MULTILINE)
        sections = [h for h in headings if re.match(r"\d\. ", h)]
        self.assertEqual(sections, ["1. What a viewer is", "2. Finding the watcher", "3. Capabilities",
                                    "4. Start here", "5. Checking your viewer", "6. Working examples"])
        capabilities = [h for h in headings if re.match(r"3\.\d ", h)]
        self.assertEqual([h.split(" ", 1)[1] for h in capabilities],
                         ["Threads", "Review path", "Views", "Viewed files", "Review mode: live, batched, submit",
                          "Done", "The coding agent that replies", "Export"])
        for capability, text in zip(capabilities, re.split(r"^### 3\.\d .*$", guide, flags=re.MULTILINE)[1:]):
            for part in ("**What it is.**", "**Calls.**", "**Rules.**"):
                self.assertIn(part, text, capability)
        self.assertIn("Threads, review mode with submit, and the review path make a useful first viewer.", guide)
        self.assertIn("Run `difftate demo`", guide)
        self.assertIn("**A viewer that starts threads in batched mode offers submit.**", guide)

    def test_the_help_names_it(self):
        run = self.difftate("--help")

        self.assertEqual(run.returncode, 0)
        self.assertRegex(run.stdout, r"difftate --guide +prints the viewer guide")


if __name__ == "__main__":
    unittest.main()
