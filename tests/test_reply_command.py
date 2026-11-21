"""Seam: `dt-reply`, the command an agent answers a review thread with.

Each test runs the real command (bin/dt-reply) in a temporary git repository on
the branch "feature", beside the real watcher when the test starts one.

Outside a run (no DT_RUN_DIR) it finds the watcher of its folder as dt-export
does, and posts the answer through the review API (ADR 0006). Inside a run
(DT_RUN_DIR set) it leaves the answer in the run's folder as it always did, and
never reaches the review API: a run's sandbox denies it the token. The review
is batched in these tests, so its threads are held and no run starts. HOME
points into the temporary folder, so the review history stays there too.
"""
import io
import os
import re
import subprocess
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from test_watcher import Harness, git  # noqa: E402

from difftate.adapters.outbound.coding_agents.reply_channel import RunFolder  # noqa: E402

DT_REPLY = os.path.join(ROOT, "bin", "dt-reply")
DT_EXPORT = os.path.join(ROOT, "bin", "dt-export")


class TheReplyCommand(Harness, unittest.TestCase):
    def reply(self, *args, cwd=None, stdin="", env=None):
        """The command's result: (exit code, what it printed, what it said on stderr)."""
        r = subprocess.run([sys.executable, DT_REPLY, *args], cwd=cwd or self.repo, env=env or self.env,
                           input=stdin, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr

    def a_review_with_a_held_thread(self):
        git(self.repo, self.env, "add", "-A")
        git(self.repo, self.env, "commit", "-q", "-m", "Greet with an f-string")
        self.start_watcher()
        self.api("PUT", "/api/mode", {"mode": "batched"})
        return self.open_thread("Why an f-string?")["id"]

    def events(self):
        folder = os.path.join(self.repo, ".git", "difftate", "reviews")
        [review] = os.listdir(folder)
        with open(os.path.join(folder, review, "events.jsonl")) as f:
            return f.read()

    # ── Outside a run: through the watcher ───────────────────────────────────
    def test_a_reply_on_an_open_thread_shows_as_the_coding_agents_reply_and_makes_it_replied(self):
        tid = self.a_review_with_a_held_thread()

        code, out, err = self.reply(tid[:8], "It reads better than +.")

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, f"Replied to thread {tid[:8]}.\n")
        last = self.thread(tid)["comments"][-1]
        self.assertEqual((last["author"], last["by"], last["kind"], last["body"]),
                         ("agent", None, "reply", "It reads better than +."))
        self.assertEqual(self.state(tid), "replied")

    def test_a_reply_has_no_progress_note(self):
        tid = self.a_review_with_a_held_thread()

        self.reply(tid[:8], "It reads better than +.")

        self.assertEqual([k for k, _ in self.comments(tid)], ["comment", "reply"])

    def test_the_whole_thread_id_works_too(self):
        tid = self.a_review_with_a_held_thread()

        code, _, err = self.reply(tid, "Yes.")

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.bodies(tid)[-1], "Yes.")

    def test_the_answer_can_come_from_stdin_for_quotes_and_several_lines(self):
        tid = self.a_review_with_a_held_thread()
        answer = "It's \"cleaner\".\nSecond line.\n"

        code, _, err = self.reply(tid[:8], stdin=answer)

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.bodies(tid)[-1], answer)

    def test_an_empty_answer_is_refused_and_nothing_is_posted(self):
        tid = self.a_review_with_a_held_thread()

        code, out, err = self.reply(tid[:8], "  ")

        self.assertEqual((code, out), (1, ""))
        self.assertIn("dt-reply: the answer is empty", err)
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string?")])

    def test_a_reply_on_a_resolved_or_dismissed_thread_is_accepted_and_leaves_its_status(self):
        resolved = self.a_review_with_a_held_thread()
        dismissed = self.open_thread("Rename it?", line=1)["id"]
        self.api("PATCH", f"/api/threads/{resolved}/status", {"status": "resolved"})
        self.api("PATCH", f"/api/threads/{dismissed}/status", {"status": "dismissed"})

        for tid, status in ((resolved, "resolved"), (dismissed, "dismissed")):
            code, _, err = self.reply(tid[:8], "Noted.")

            self.assertEqual((code, err), (0, ""))
            self.assertEqual(self.thread(tid)["comments"][-1]["kind"], "reply")
            self.assertEqual(self.thread(tid)["status"], status)

    def test_a_thread_that_is_not_in_the_review_is_refused_and_nothing_is_posted(self):
        self.a_review_with_a_held_thread()
        before = self.events()

        code, out, err = self.reply("deadbeef", "Hello.")

        self.assertEqual((code, out), (1, ""))
        self.assertIn("dt-reply: no thread 'deadbeef' in this review", err)
        self.assertEqual(self.events(), before)

    def test_an_empty_thread_id_is_refused_and_nothing_is_posted(self):
        self.a_review_with_a_held_thread()
        before = self.events()

        code, out, err = self.reply("", "Hello.")

        self.assertEqual((code, out), (1, ""))
        self.assertIn("dt-reply: no thread '' in this review", err)
        self.assertEqual(self.events(), before)

    def test_a_thread_id_must_match_the_start_of_an_id_not_the_middle(self):
        tid = self.a_review_with_a_held_thread()

        code, _, err = self.reply(tid[1:9], "Hello.")

        self.assertEqual(code, 1)
        self.assertIn("no thread", err)

    # ── Which watcher it asks ────────────────────────────────────────────────
    def test_it_works_from_a_subfolder_of_the_repository(self):
        tid = self.a_review_with_a_held_thread()
        os.makedirs(os.path.join(self.repo, "sub"))

        code, _, err = self.reply(tid[:8], "Yes.", cwd=os.path.join(self.repo, "sub"))

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.state(tid), "replied")

    def test_with_a_folder_it_asks_the_watcher_of_that_folder_from_anywhere(self):
        tid = self.a_review_with_a_held_thread()

        code, _, err = self.reply("--folder", self.repo, tid[:8], "Yes.", cwd=self.tmp)

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.state(tid), "replied")

    def test_in_a_worktree_it_replies_in_that_worktrees_review_not_the_repositorys(self):
        tid = self.a_review_with_a_held_thread()
        worktree = self.add_worktree("other")

        code, out, err = self.reply(tid[:8], "Yes.", cwd=worktree)

        self.assertEqual((code, out), (1, ""))
        self.assertIn(f"no thread {tid[:8]!r} in this review", err, "the worktree has its own review")
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string?")])

    def test_the_command_the_export_names_works_from_the_session(self):
        tid = self.a_review_with_a_held_thread()
        for args, cwd in (([], self.repo), ([self.repo], self.tmp)):
            exported = subprocess.run([sys.executable, DT_EXPORT, *args], cwd=cwd, env=self.env,
                                      capture_output=True, text=True, timeout=60, check=True).stdout
            command = re.search(r"Reply to a thread with: (.*) <thread> \"<answer>\"", exported).group(1)

            r = subprocess.run(f"{command} {tid[:8]} 'Answer from {len(args)}'", shell=True, cwd=cwd, env=self.env,
                               capture_output=True, text=True, timeout=60)

            self.assertEqual((r.returncode, r.stderr), (0, ""))
            self.assertEqual(self.bodies(tid)[-1], f"Answer from {len(args)}")

    # ── When it can't ────────────────────────────────────────────────────────
    def test_with_no_running_watcher_it_says_so_and_fails_posting_nothing(self):
        code, out, err = self.reply("deadbeef", "Hello.")

        self.assertEqual((code, out), (1, ""))
        self.assertIn("No difftate is running: run `difftate` in a terminal", err)
        self.assertIn("nothing was posted", err)

    def test_after_the_watcher_stopped_it_fails_the_same_way(self):
        tid = self.a_review_with_a_held_thread()
        self.stop_watcher()

        code, out, err = self.reply(tid[:8], "Hello.")

        self.assertEqual((code, out), (1, ""))
        self.assertIn("No difftate is running", err)

    def test_a_folder_that_is_not_a_git_repository_is_refused(self):
        code, out, err = self.reply("--folder", self.tmp, "deadbeef", "Hello.", cwd=self.tmp)

        self.assertEqual((code, out), (1, ""))
        self.assertIn("is not a git repository", err)

    def test_the_command_never_writes_the_store_itself(self):
        tid = self.a_review_with_a_held_thread()
        self.stop_watcher()
        before = self.events()

        self.reply(tid[:8], "Hello.")

        self.assertEqual(self.events(), before)

    # ── Usage ────────────────────────────────────────────────────────────────
    def test_help_prints_the_usage_and_a_wrong_number_of_arguments_is_a_usage_error(self):
        code, out, _ = self.reply("--help")
        self.assertEqual(code, 0)
        self.assertIn("dt-reply [--folder <folder>] <thread>", out)

        for args in ([], ["a", "b", "c"], ["--folder"], ["--folder", "x"]):
            code, out, err = self.reply(*args)
            self.assertEqual((code, out), (2, ""), args)
            self.assertIn("dt-reply [--folder <folder>] <thread>", err)

    # ── Inside a run ─────────────────────────────────────────────────────────
    def run_env(self, folder):
        return dict(self.env, DT_RUN_DIR=folder.path)

    def test_inside_a_run_the_answer_goes_to_the_runs_folder_not_the_review_api(self):
        tid = self.a_review_with_a_held_thread()
        folder = RunFolder.create([tid])
        self.addCleanup(folder.remove)

        code, out, err = self.reply(tid[:8], "From the run.", env=self.run_env(folder))

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, f"Replied to thread {tid[:8]}.\n")
        [(_, thread, body)] = folder.replies()
        self.assertEqual((thread, body), (tid, "From the run."))
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string?")],
                         "the watcher posts it, when the run ends: dt-reply didn't")

    def test_inside_a_run_a_thread_it_may_not_reply_to_is_refused_not_sent_to_the_api(self):
        tid = self.a_review_with_a_held_thread()
        folder = RunFolder.create([])
        self.addCleanup(folder.remove)

        code, out, err = self.reply(tid[:8], "Not mine.", env=self.run_env(folder))

        self.assertEqual((code, out), (1, ""))
        self.assertIn("no open thread", err)
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string?")])

    def test_inside_a_run_whose_folder_is_gone_it_fails_and_does_not_fall_back_to_the_api(self):
        tid = self.a_review_with_a_held_thread()

        code, out, err = self.reply(tid[:8], "Lost.", env=dict(self.env, DT_RUN_DIR=os.path.join(self.tmp, "gone")))

        self.assertEqual((code, out), (1, ""))
        self.assertIn("no run's folder", err)
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string?")])

    def test_inside_a_run_a_folder_is_refused_since_the_run_has_no_review_api(self):
        tid = self.a_review_with_a_held_thread()
        folder = RunFolder.create([tid])
        self.addCleanup(folder.remove)

        code, out, err = self.reply("--folder", self.repo, tid[:8], "Nope.", env=self.run_env(folder))

        self.assertEqual((code, out), (1, ""))
        self.assertIn("--folder", err)
        self.assertEqual((folder.replies(), self.comments(tid)), ([], [("comment", "Why an f-string?")]))

    def test_an_empty_DT_RUN_DIR_counts_as_no_run(self):
        # As dt-reply always read it: a run always sets a folder
        tid = self.a_review_with_a_held_thread()

        code, _, err = self.reply(tid[:8], "Yes.", env=dict(self.env, DT_RUN_DIR=""))

        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.state(tid), "replied")


class AmbiguousThreadIds(unittest.TestCase):
    """Two threads whose ids start the same: no real review makes them on demand,
    so the command line runs against a stand-in for the watcher."""

    def test_an_id_start_that_matches_several_threads_is_refused_and_nothing_is_posted(self):
        from difftate.adapters.inbound.cli import run_reply
        posted = []

        def ask(folder, method, path, payload=None):
            if method == "GET":
                return 200, [{"id": "abcd1234-one"}, {"id": "abcd1234-two"}, {"id": "ffff0000-three"}]
            posted.append((path, payload))
            return 200, {}

        wiring = SimpleNamespace(difftate_folder=lambda cwd: SimpleNamespace(reviews="/r/.git/difftate", root="/r"),
                                 difftate_home="/home/.difftate",
                                 running_watcher=lambda folder: 1234, ask_running_watcher=ask)
        out, err = io.StringIO(), io.StringIO()

        code = run_reply(["abcd"], wiring, env={}, cwd="/r", stdin=io.StringIO("Hello."), out=out, err=err)

        self.assertEqual((code, out.getvalue(), posted), (1, "", []))
        self.assertIn("'abcd' matches several threads", err.getvalue())


if __name__ == "__main__":
    unittest.main()
