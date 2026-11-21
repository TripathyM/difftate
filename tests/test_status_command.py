"""Seam: `difftate status --json`, the command that reads a review's Done state
from outside difftate.

Each test runs the real command (difftate-watch.py status) in a temporary git
repository on the branch "feature", beside the real watcher when the test
starts one. The command only reads: it works with a watcher running or not, on
any branch of the repository, and it keeps nothing. HOME points into the
temporary folder, so the review history stays there too.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_watcher import DIFFTATE, Harness, git, wait_for  # noqa: E402

TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"


class TheStatusCommand(Harness, unittest.TestCase):
    def status(self, *args, cwd=None):
        """The command's result: (exit code, what it printed, what it said on stderr)."""
        r = subprocess.run([sys.executable, DIFFTATE, "status", *args], cwd=cwd or self.repo, env=self.env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def state(self, *args, cwd=None):
        """The JSON the command prints."""
        code, out, err = self.status("--json", *args, cwd=cwd)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def head(self, branch="feature"):
        return subprocess.run(["git", "-C", self.repo, "rev-parse", branch], check=True, capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def commit(self, message="another commit"):
        git(self.repo, self.env, "add", "-A")
        git(self.repo, self.env, "commit", "-q", "-m", message)

    def events_file(self):
        folder = os.path.join(self.repo, ".git", "difftate", "reviews")
        [review] = os.listdir(folder)
        return os.path.join(folder, review, "events.jsonl")

    def events(self):
        with open(self.events_file()) as f:
            return [json.loads(line) for line in f]

    def mark_done(self, done=True):
        return self.api("PUT", "/api/done", {"done": done})

    # ── What it prints ───────────────────────────────────────────────────────
    def test_a_review_nobody_marked_is_not_done_and_asking_starts_no_review(self):
        state = self.state("--branch", "feature")

        self.assertEqual(state, {"branch": "feature", "base": "main", "head": self.head(), "done": False,
                                 "time": None, "commit": None, "lastMark": None, "openThreads": 0,
                                 "runsInFlight": 0})
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "difftate", "reviews")))

    def test_a_review_marked_done_prints_the_mark_with_its_time_and_commit(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["commit"], state["head"]), (True, self.head(), self.head()))
        self.assertRegex(state["time"], TIME)
        self.assertEqual(state["lastMark"], {"kind": "done", "time": state["time"], "commit": self.head()})

    def test_it_works_while_a_watcher_runs_and_counts_the_threads_still_open(self):
        self.start_watcher()
        self.open_thread("Is this ready?")
        self.mark_done()

        state = self.state("--branch", "feature")

        # The watcher may have sent the thread to the agent by now: a run in flight, or not yet
        self.assertEqual((state["done"], state["openThreads"]), (True, 1))
        self.assertIn(state["runsInFlight"], (0, 1))

    def test_reading_it_beside_a_watcher_keeps_nothing_and_is_not_taken_for_tampering(self):
        self.start_watcher()
        self.mark_done()
        before = self.events()

        for _ in range(3):
            self.state("--branch", "feature")

        self.assertEqual(self.events(), before)
        self.mark_done(False)  # the watcher still keeps what it is asked to: nothing was restored over it
        self.assertEqual([e["type"] for e in self.events()], ["done", "undone"])
        self.assertNotIn("changed outside difftate", self.terminal())

    def test_without_a_branch_it_is_the_review_of_the_checked_out_branch(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()

        self.assertEqual(self.state(), self.state("--branch", "feature"))

    def test_it_says_which_branch_and_base_in_every_answer(self):
        state = self.state("--branch", "feature", "--base", "main")

        self.assertEqual((state["branch"], state["base"]), ("feature", "main"))

    def test_an_undo_is_the_last_mark_and_the_review_is_not_done(self):
        self.start_watcher()
        self.mark_done()
        self.mark_done(False)
        self.stop_watcher()

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["time"], state["commit"]), (False, None, None))
        self.assertEqual((state["lastMark"]["kind"], state["lastMark"]["commit"]), ("undone", self.head()))
        self.assertRegex(state["lastMark"]["time"], TIME)

    def test_a_new_commit_with_no_watcher_shows_done_cleared_by_it_and_keeps_nothing(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()
        done_at = self.head()
        before = self.events()
        self.commit()

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["head"]), (False, self.head()))
        self.assertNotEqual(self.head(), done_at)
        self.assertEqual((state["lastMark"]["kind"], state["lastMark"]["commit"]), ("cleared", self.head()))
        self.assertRegex(state["lastMark"]["time"], TIME)
        self.assertEqual(self.events(), before, "reading keeps nothing")

    def test_a_running_watcher_keeps_the_clearing_a_new_commit_makes(self):
        self.start_watcher()
        self.mark_done()
        self.commit()

        cleared = wait_for("the clearing", lambda: [e for e in self.events() if e["type"] == "done-cleared"])

        self.assertEqual([(e["type"], e["commit"]) for e in cleared], [("done-cleared", self.head())])
        state = self.state("--branch", "feature")
        self.assertEqual((state["done"], state["lastMark"]["kind"], state["lastMark"]["commit"]),
                         (False, "cleared", self.head()))

    def test_every_mark_is_in_the_review_history_with_its_time_and_commit(self):
        self.start_watcher()
        done_at = self.head()
        self.mark_done()
        self.mark_done(False)
        self.mark_done()
        self.commit()
        wait_for("the clearing", lambda: [e for e in self.events() if e["type"] == "done-cleared"])
        self.stop_watcher()

        history = os.path.join(self.difftate_home, "history")
        lines = []
        for name in sorted(os.listdir(history)):
            with open(os.path.join(history, name)) as f:
                lines += [json.loads(line) for line in f]
        marks = [(line["type"], line["commit"]) for line in lines if line["type"] in ("done", "undone", "done-cleared")]

        self.assertEqual(marks, [("done", done_at), ("undone", done_at), ("done", done_at),
                                 ("done-cleared", self.head())])
        self.assertTrue(all(line["time"] for line in lines))

    def test_a_new_thread_after_done_does_not_clear_it(self):
        self.start_watcher()
        self.mark_done()
        self.open_thread("One more thing")
        self.stop_watcher()

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["openThreads"]), (True, 1))

    # ── Whatever branch the folder has checked out ───────────────────────────
    def test_it_reads_the_review_of_a_branch_that_is_not_checked_out(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()
        done_at = self.head()
        git(self.repo, self.env, "checkout", "-q", "main")

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["commit"], state["head"]), (True, done_at, done_at))

    def test_a_branch_that_was_merged_and_deleted_keeps_its_done_state(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()
        done_at = self.head()
        git(self.repo, self.env, "checkout", "-q", "main")
        git(self.repo, self.env, "merge", "-q", "--ff-only", "feature")
        git(self.repo, self.env, "branch", "-q", "-D", "feature")

        state = self.state("--branch", "feature")

        self.assertEqual((state["done"], state["commit"], state["head"]), (True, done_at, None))

    def test_it_runs_from_a_worktree_for_any_branch_of_the_repository(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()
        folder = self.add_worktree("topic")

        state = self.state("--branch", "feature", cwd=folder)

        self.assertEqual((state["branch"], state["done"]), ("feature", True))
        self.assertFalse(self.state("--branch", "topic", cwd=folder)["done"])

    # ── Without --json, and when it can't answer ─────────────────────────────
    def test_without_json_it_says_it_in_a_line(self):
        self.start_watcher()
        self.mark_done()
        self.stop_watcher()

        code, out, err = self.status("--branch", "feature")

        self.assertEqual(code, 0, err)
        self.assertIn(f"Done at {self.head()[:7]}", out)
        self.assertNotIn("{", out)

    def test_outside_a_git_repository_it_fails_and_says_so(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(elsewhere)

        code, out, err = self.status("--json", cwd=elsewhere)

        self.assertEqual(code, 1)
        self.assertIn("is not a git repository", out + err)

    def test_a_flag_it_does_not_know_is_refused(self):
        code, out, err = self.status("--json", "--tool", "claude")

        self.assertEqual(code, 1)
        self.assertIn("--tool", out + err)

    def test_a_branch_that_has_no_commit_and_no_review_is_an_error(self):
        code, out, err = self.status("--json", "--branch", "no-such-branch")

        self.assertEqual(code, 1)
        self.assertIn("no-such-branch", out + err)

    # ── From the shell ───────────────────────────────────────────────────────
    def test_the_difftate_program_on_the_path_runs_it_and_does_not_start_a_watcher(self):
        self.env["PATH"] = os.pathsep.join([os.path.join(ROOT, "bin"), self.env["PATH"]])
        r = subprocess.run(["difftate", "status", "--json", "--branch", "feature"],
                           cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=60)

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["branch"], "feature")
        self.assertIsNone(self.running_pid())
        self.assertFalse(os.path.exists(os.path.join(self.difftate_home, "api.json")))


if __name__ == "__main__":
    unittest.main()
