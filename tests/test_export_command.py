"""Seam: `dt-export`, the command that prints a review's export (GLOSSARY.md,
Export) from outside difftate.

Each test runs the real command (bin/dt-export) in a temporary git repository
on the branch "feature", beside the real watcher when the test starts one. The
command asks the watcher of the folder, as a second `difftate` in that folder
does, and prints what the review API's export route answers. The review is
batched in these tests, so its threads are held and no run starts. HOME points
into the temporary folder, so the review history stays there too.
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_watcher import Harness, git  # noqa: E402

DT_EXPORT = os.path.join(ROOT, "bin", "dt-export")


class TheExportCommand(Harness, unittest.TestCase):
    def export(self, *args, cwd=None):
        """The command's result: (exit code, what it printed, what it said on stderr)."""
        r = subprocess.run([sys.executable, DT_EXPORT, *args], cwd=cwd or self.repo, env=self.env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def a_review_with_a_held_thread(self):
        git(self.repo, self.env, "add", "-A")
        git(self.repo, self.env, "commit", "-q", "-m", "Greet with an f-string\n\nIt reads better than +.")
        self.start_watcher()
        self.api("PUT", "/api/mode", {"mode": "batched"})
        return self.open_thread("Why an f-string?")["id"]

    def events(self):
        folder = os.path.join(self.repo, ".git", "difftate", "reviews")
        [review] = os.listdir(folder)
        with open(os.path.join(folder, review, "events.jsonl")) as f:
            return f.read()

    # ── What it prints ───────────────────────────────────────────────────────
    def test_it_prints_the_export_of_the_review_of_the_folder_it_runs_in(self):
        tid = self.a_review_with_a_held_thread()

        code, out, err = self.export()

        self.assertEqual((code, err), (0, ""))
        self.assertIn("Greet with an f-string\n\nIt reads better than +.", out)
        self.assertIn(f"### Thread {tid[:8]} — app.py:2 — open (held)", out)
        self.assertIn("reviewer Test: Why an f-string?", out)
        self.assertRegex(out, r'Reply to a thread with: \S*dt-reply <thread> "<answer>"')
        self.assertNotIn("--folder", out, "it runs in the folder: dt-reply finds the watcher the same way")

    def test_it_works_from_a_subfolder_of_the_repository(self):
        self.a_review_with_a_held_thread()
        os.makedirs(os.path.join(self.repo, "sub"))

        code, out, _ = self.export(cwd=os.path.join(self.repo, "sub"))

        self.assertEqual(code, 0)
        self.assertIn("Why an f-string?", out)

    def test_it_prints_the_export_of_a_folder_given_from_anywhere_and_names_it_in_the_reply_command(self):
        self.a_review_with_a_held_thread()

        code, out, err = self.export(self.repo, cwd=self.tmp)

        self.assertEqual((code, err), (0, ""))
        self.assertIn("Why an f-string?", out)
        self.assertIn(f"dt-reply --folder {os.path.realpath(self.repo)} <thread> ", out)

    def test_it_changes_no_thread_and_writes_no_event(self):
        tid = self.a_review_with_a_held_thread()
        before = self.events()

        self.export()
        self.export(self.repo, cwd=self.tmp)

        self.assertEqual(self.events(), before)
        self.assertEqual(self.state(tid), "held")

    # ── Which review it asks for ─────────────────────────────────────────────
    def test_in_a_worktree_it_exports_that_worktrees_review_from_the_one_watcher(self):
        self.a_review_with_a_held_thread()
        worktree = self.add_worktree("other")

        code, out, err = self.export(cwd=worktree)

        self.assertEqual((code, err), (0, ""), "the first request naming the worktree adds it")
        self.assertNotIn("Why an f-string?", out, "not the repository's review")
        self.assertIn("## Threads that need an answer (0)", out)

    # ── When it can't ────────────────────────────────────────────────────────
    def test_with_no_running_watcher_it_says_so_and_fails(self):
        code, out, err = self.export()

        self.assertEqual((code, out), (1, ""))
        self.assertIn("No difftate is running: run `difftate` in a terminal", err)

    def test_after_the_watcher_stopped_it_fails_the_same_way(self):
        self.a_review_with_a_held_thread()
        self.stop_watcher()

        code, out, err = self.export()

        self.assertEqual((code, out), (1, ""))
        self.assertIn("No difftate is running", err)

    def test_a_folder_that_is_not_a_git_repository_is_refused(self):
        code, out, err = self.export(self.tmp, cwd=self.tmp)

        self.assertEqual((code, out), (1, ""))
        self.assertIn("is not a git repository", err)

    def test_a_folder_that_does_not_exist_is_refused(self):
        code, out, err = self.export(os.path.join(self.tmp, "nope"), cwd=self.tmp)

        self.assertEqual((code, out), (1, ""))
        self.assertIn("is not a git repository", err)

    def test_help_prints_the_usage_and_more_than_one_folder_is_a_usage_error(self):
        code, out, _ = self.export("--help")
        self.assertEqual(code, 0)
        self.assertIn("dt-export [<folder>]", out)

        code, out, err = self.export("one", "two")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("dt-export [<folder>]", err)


if __name__ == "__main__":
    unittest.main()
