"""Seam: the Review tab's Export action (herdr/mods/difftate/exported.js).

main.js needs Herdr to load; exported.js is plain JavaScript, so node runs it here:
each test reads back what the tab would say. Skipped where node isn't installed.
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTED_JS = os.path.join(ROOT, "herdr", "mods", "difftate", "exported.js")
KEYMAP = os.path.join(ROOT, "herdr", "mods", "difftate", "keymap.json")
NODE = shutil.which("node")


def run(call, **args):
    script = (
        "const m = await import(process.argv[1]);\n"
        "const a = JSON.parse(process.argv[2]);\n"
        f"const out = ({call});\n"
        "process.stdout.write(JSON.stringify(out ?? null));\n"
    )
    r = subprocess.run([NODE, "--input-type=module", "-e", script, "file://" + EXPORTED_JS, json.dumps(args)],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@unittest.skipUnless(NODE, "node isn't installed")
class ExportingFromTheReviewTab(unittest.TestCase):
    def test_a_copied_export_says_where_to_paste_it(self):
        self.assertEqual(run("m.exportedMessage()"), "Export copied: paste it into an agent session")

    def test_a_failure_says_what_went_wrong(self):
        self.assertEqual(run("m.exportFailedMessage({message: 'no difftate is running'})"), "Could not export: no difftate is running")
        self.assertEqual(run("m.exportFailedMessage('boom')"), "Could not export: boom")

    def test_an_empty_answer_is_not_an_export(self):
        self.assertIsNotNone(run("m.exportProblem('')"))
        self.assertIsNotNone(run("m.exportProblem(null)"))
        self.assertIsNone(run("m.exportProblem('# Review\\n')"))

    def test_the_export_key_is_bound_and_free(self):
        with open(KEYMAP) as f:
            keys = json.load(f)["normal"]
        self.assertEqual(keys["<leader>E"], "export")
        self.assertEqual(list(keys.values()).count("export"), 1)
