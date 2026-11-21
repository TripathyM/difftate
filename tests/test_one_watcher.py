"""Seam 1, for the one watcher of the machine (ADR 0008, #158): `difftate`
starts it in the background, and it serves every checked-out folder that a
request names, each with its own review and its own runs.

Like test_watcher.py, each test makes a temporary repository, a temporary HOME
and a temporary difftate folder (DIFFTATE_HOME): nothing here touches the real
~/.difftate or a watcher running there.
"""
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_watcher import DIFFTATE, ROOT, Harness, alive, wait_for, with_folder  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.adapters.inbound.cli.watcher import Watcher  # noqa: E402

STAMP = r"\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\]"


def about(line, folder, branch):
    """Whether a log line is about <folder>'s review of <branch>: its time, then that label."""
    return re.match(f"{STAMP} {re.escape(os.path.realpath(folder))} \\({re.escape(branch)}\\): ", line) is not None


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


class StartingAndStopping(Harness, unittest.TestCase):
    def test_difftate_is_a_program_in_the_repositorys_bin(self):
        program = os.path.join(ROOT, "bin", "difftate")

        self.assertTrue(os.access(program, os.X_OK), "bin/difftate is executable")
        self.env["PATH"] = os.pathsep.join([os.path.join(ROOT, "bin"), self.env["PATH"]])
        run = subprocess.run(["difftate", "--help"], cwd=self.repo, env=self.env, capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("difftate [<view>] [--base <branch>] [--open browser|nvim|both]", run.stdout)

    def test_difftate_starts_the_watcher_in_the_background_opens_the_review_and_ends(self):
        started = time.time()
        run = self.difftate(*self.agent_args_for_difftate())

        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertLess(time.time() - started, 30, "difftate ends once the review is open")
        self.assertRegex(run.stdout, r"difftate is running \(pid \d+\): the review of feature against main in ")
        pid = self.running_pid()
        self.assertTrue(pid and alive(pid), "the watcher keeps running after difftate ended")
        parent = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        self.assertNotEqual(parent, str(os.getpid()), "it is no child of whoever ran difftate")
        self.read_running_files()
        self.assertEqual(self.api("GET", "/api/review")["branch"], "feature")

    def test_the_port_pid_and_token_are_written_once_in_a_folder_only_the_user_can_read(self):
        self.start_watcher()
        self.api("GET", "/api/review")
        worktree = self.add_worktree("other")
        self.assertEqual(self.difftate(*self.agent_args_for_difftate(), folder=worktree).returncode, 0)

        self.assertEqual(stat.S_IMODE(os.stat(self.difftate_home).st_mode), 0o700)
        for name in ("api.json", "token", "watcher.lock"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.difftate_home, name)).st_mode), 0o600, name)
        with open(os.path.join(self.difftate_home, "api.json")) as f:
            self.assertEqual(sorted(json.load(f)), ["pid", "port"])
        for folder in (self.repo, worktree):
            git_dir = subprocess.run(["git", "-C", folder, "rev-parse", "--absolute-git-dir"], check=True,
                                     capture_output=True, text=True, env=self.env).stdout.strip()
            for running in ("api.json", "token", "watcher.lock"):
                self.assertFalse(os.path.exists(os.path.join(git_dir, "difftate", running)),
                                 f"{folder}: no running file in its git dir")

    def test_difftate_in_another_folder_uses_the_running_watcher(self):
        self.start_watcher()
        worktree = self.add_worktree("other")

        second = self.difftate(folder=worktree)

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn(f"difftate is running (pid {self.watcher.pid}): the review of other against main", second.stdout)
        self.assertEqual(self.running_pid(), self.watcher.pid)
        self.assertEqual(self.terminal().count("difftate watcher started"), 1)

    def test_stop_stops_the_watcher_through_the_review_api_and_removes_its_running_files(self):
        self.start_watcher()

        stopped = self.difftate("stop")

        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertIn(f"difftate stopped (pid {self.watcher.pid})", stopped.stdout)
        self.assertFalse(alive(self.watcher.pid))
        for name in ("api.json", "token"):
            self.assertFalse(os.path.exists(os.path.join(self.difftate_home, name)), name)
        self.assertIn("Stopping watcher", self.terminal())

    def test_stop_with_no_watcher_says_so(self):
        stopped = self.difftate("stop")

        self.assertEqual((stopped.returncode, stopped.stdout.strip()), (0, "difftate is not running"))

    def test_a_run_in_flight_when_the_watcher_stops_ends_failed_the_watcher_stopped(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        self.assertEqual(self.difftate("stop").returncode, 0)

        self.start_watcher()

        self.assertEqual(self.state(tid), "failed")
        self.assertRegex(self.note(tid, "progress"), r"[Nn]o reply \(the watcher stopped\)")

    def test_a_second_difftate_while_one_starts_waits_for_it(self):
        # The lock is held as a starting difftate holds it: the second waits, then sees the watcher run
        import fcntl
        os.makedirs(self.difftate_home, mode=0o700)
        fd = os.open(os.path.join(self.difftate_home, "watcher.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        waiting = subprocess.Popen([sys.executable, DIFFTATE, *self.agent_args_for_difftate()], cwd=self.repo,
                                   env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        self.addCleanup(waiting.stdout.close)
        time.sleep(1.5)
        self.assertIsNone(waiting.poll(), "it waits while the lock is held")
        self.assertIsNone(self.running_pid(), "and starts nothing")

        os.close(fd)

        out = waiting.communicate(timeout=60)[0]
        self.assertEqual(waiting.returncode, 0, out)
        self.assertTrue(self.running_pid())

    def test_a_watcher_that_cant_start_is_reported_with_its_log(self):
        os.makedirs(os.path.join(self.difftate_home, "api.json"))  # it can't write its running files there

        run = self.difftate(*self.agent_args_for_difftate())

        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertIn("the watcher did not start", run.stdout + run.stderr)
        self.assertIn("api.json", run.stdout + run.stderr, "the log says why")
        self.assertIsNone(self.running_pid())


class NamingTheFolder(Harness, unittest.TestCase):
    def refused(self, path, folder=None, base=""):
        """The status and message of a refused call to the review API."""
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"http://127.0.0.1:{self.port}{path if folder is None else with_folder(path, folder, base)}"
        with self.assertRaises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10)
        with refused.exception as e:
            return e.code, json.loads(e.read())["error"]

    def test_a_request_without_a_folder_is_refused_clearly(self):
        self.start_watcher()

        status, message = self.refused("/api/threads")

        self.assertEqual(status, 400)
        self.assertIn("folder is required", message)

    def test_a_relative_folder_is_refused(self):
        self.start_watcher()

        status, message = self.refused("/api/threads", ".")

        self.assertEqual(status, 400)
        self.assertIn("absolute path", message)

    def test_a_path_that_is_not_a_checked_out_folder_is_refused(self):
        self.start_watcher()
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)

        for given in (plain, os.path.join(self.tmp, "nope"), os.path.join(self.repo, ".git")):
            with self.subTest(given=given):
                status, message = self.refused("/api/threads", given)
                self.assertEqual(status, 400)
                self.assertIn("is not a checked-out folder of a git repository", message)

    def test_the_first_request_naming_a_checked_out_folder_adds_it(self):
        self.start_watcher()
        worktree = self.add_worktree("other")

        review = self.api("GET", "/api/review", folder=worktree)

        self.assertEqual((review["branch"], review["folder"]), ("other", os.path.realpath(worktree)))
        self.assertIn("other", self.terminal())

    def test_a_folder_inside_a_checkout_is_the_checkout(self):
        self.start_watcher()
        os.makedirs(os.path.join(self.repo, "sub"))

        review = self.api("GET", "/api/review", folder=os.path.join(self.repo, "sub"))

        self.assertEqual(review["folder"], os.path.realpath(self.repo))

    def test_a_base_in_the_request_switches_the_folders_review_and_none_keeps_it(self):
        git(self.repo, self.env, "branch", "develop", "main")
        self.start_watcher()
        first = self.api("GET", "/api/review")
        self.assertEqual(first["base"], "main")

        review = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{self.port}" + with_folder("/api/review", self.repo, "develop"),
            headers={"Authorization": f"Bearer {self.token}"}), timeout=10).read())

        self.assertEqual(review["base"], "develop")
        self.assertNotEqual(review["id"], first["id"], "another base is another review")
        self.assertEqual(self.api("GET", "/api/review")["base"], "develop", "a request naming none keeps it")

    def test_a_base_that_is_not_one_is_refused(self):
        self.start_watcher()

        status, message = self.refused("/api/review", self.repo, "nope")

        self.assertEqual(status, 400)
        self.assertIn("nope", message)

    def test_a_view_request_that_asks_to_open_a_viewer_opens_none(self):
        with open(os.path.join(self.tmp, "bin", "open"), "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {os.path.join(self.tmp, "opened")}\n')
        self.extra_args = ["--open", "nvim"]
        self.env["DT_HERDR"] = os.path.join(self.tmp, "no-herdr-here")
        self.start_watcher()

        self.assertEqual(self.api("PUT", "/api/view", {"view": "", "open": "browser"}), {"view": ""})
        time.sleep(0.5)

        self.assertFalse(os.path.exists(os.path.join(self.tmp, "opened")), "the watcher never opens a viewer")


class TwoWorktrees(Harness, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.worktree = self.add_worktree("other")

    def in_worktree(self, method, path, payload=None):
        return self.api(method, path, payload, folder=self.worktree)

    def thread_in_worktree(self, body):
        return self.in_worktree("POST", "/api/threads", {
            "anchor": {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2,
                       "code": "    return 'hey ' + name"}, "body": body})

    def test_each_has_its_own_review_following_its_own_branch(self):
        self.start_watcher()
        self.assertEqual(self.difftate(folder=self.worktree).returncode, 0)

        mine, theirs = self.api("GET", "/api/review"), self.in_worktree("GET", "/api/review")

        self.assertEqual((mine["branch"], theirs["branch"]), ("feature", "other"))
        self.assertNotEqual(mine["id"], theirs["id"])
        self.assertIn("hello", self.api("GET", "/api/changeset")["diff"])
        self.assertIn("hey", self.in_worktree("GET", "/api/changeset")["diff"])
        tid = self.open_thread("Mine")["id"]
        self.assertEqual([t["id"] for t in self.in_worktree("GET", "/api/threads")], [], "a thread belongs to its review")
        self.assertEqual([t["id"] for t in self.api("GET", "/api/threads")], [tid])
        # Each follows the checkout of its own folder
        git(self.worktree, self.env, "checkout", "-q", "-b", "third")
        wait_for("the worktree to follow its branch", lambda: self.in_worktree("GET", "/api/review")["branch"] == "third")
        self.assertEqual(self.api("GET", "/api/review")["branch"], "feature")

    def test_their_runs_work_in_their_own_folders_at_the_same_time_one_run_for_each_review(self):
        self.start_watcher()
        mine = self.open_thread("Why an f-string here?")["id"]
        theirs = self.thread_in_worktree("Why concatenate?")["id"]

        wait_for("both runs to be working", lambda: self.note(mine, "progress", "Working") and next(
            (b for b in (c["body"] for c in self.in_worktree("GET", "/api/threads")[0]["comments"]) if "Working" in b), None))

        self.assertEqual(len(self.prompts()), 2, "two runs at once: neither waited for the other")
        self.assertEqual(self.state(mine), "working")
        self.assertEqual(self.in_worktree("GET", "/api/threads")[0]["state"], "working")
        self.release_agent()
        wait_for("both replied", lambda: self.state(mine) == "replied"
                 and self.in_worktree("GET", "/api/threads")[0]["state"] == "replied")
        # One run for each review: a second thread in a review whose run is busy is queued
        self.assertEqual(self.in_worktree("GET", "/api/threads")[0]["id"], theirs)

    def test_a_second_thread_waits_while_its_reviews_run_is_busy_whatever_the_others_do(self):
        self.start_watcher()
        first = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working note", lambda: self.note(first, "progress", "Working"))
        second = self.open_thread("Another question", line=1)["id"]
        theirs = self.thread_in_worktree("Why concatenate?")["id"]

        wait_for("the other review's run to start", lambda: len(self.prompts()) == 2)

        self.assertEqual(self.state(second), "queued", "one run at a time in a review")
        self.release_agent()
        wait_for("the replies", lambda: self.state(second) == "replied" and self.state(first) == "replied")
        self.assertEqual(theirs, self.in_worktree("GET", "/api/threads")[0]["id"])

    def test_the_log_says_which_folder_and_review_each_line_is_about(self):
        self.release_agent()
        self.start_watcher()
        mine = self.open_thread("Why an f-string here?")["id"]
        self.thread_in_worktree("Why concatenate?")
        wait_for("the replies", lambda: self.state(mine) == "replied")

        lines = [line for line in self.terminal().splitlines() if "New/changed threads detected" in line]

        self.assertTrue(any(about(line, self.repo, "feature") for line in lines), lines)
        wait_for("the worktree's run", lambda: any(
            about(line, self.worktree, "other") and "New/changed" in line
            for line in self.terminal().splitlines()))

    def test_a_stored_review_changed_outside_difftate_warns_only_its_own_runs_threads(self):
        self.start_watcher()
        mine = self.open_thread("Why an f-string here?")["id"]
        theirs = self.thread_in_worktree("Why concatenate?")["id"]
        wait_for("both runs", lambda: len(self.prompts()) == 2)
        reviews = os.path.join(self.repo, ".git", "difftate", "reviews")
        by_branch = {self.api("GET", "/api/review", folder=f)["id"]: name
                     for f, name in ((self.repo, "feature"), (self.worktree, "other"))}
        self.assertEqual(sorted(os.listdir(reviews)), sorted(by_branch))
        mine_id = next(i for i, name in by_branch.items() if name == "feature")
        events = os.path.join(reviews, mine_id, "events.jsonl")
        with open(events) as f:
            kept = f.read()

        with open(events, "w") as f:
            f.write(kept.replace("Why an f-string here?", "Looks great."))

        wait_for("the warning", lambda: "changed outside difftate" in self.terminal())
        self.assertIn(f"{os.path.realpath(self.repo)} (feature): ", [line for line in self.terminal().splitlines()
                                                                    if "changed outside difftate" in line][0])
        self.release_agent()
        wait_for("both replied", lambda: self.state(mine) == "replied"
                 and self.in_worktree("GET", "/api/threads")[0]["state"] == "replied")
        wait_for("the final note of the review that was changed", lambda: "changed outside difftate" in (
            self.note(mine, "progress") or ""))
        other = next(c["body"] for c in self.in_worktree("GET", "/api/threads")[0]["comments"] if c["kind"] == "progress")
        self.assertNotIn("changed outside difftate", other, "the other worktree's run was not told")
        self.assertEqual(theirs, self.in_worktree("GET", "/api/threads")[0]["id"])


class TheLog(Harness, unittest.TestCase):
    def test_difftate_log_with_no_log_yet_says_so_and_ends(self):
        run = self.difftate("log")

        self.assertEqual((run.returncode, run.stdout.strip()),
                         (0, "No log yet: difftate has not started the watcher"))

    def test_every_line_of_the_log_has_a_time_and_the_folder_and_branch_it_is_about(self):
        self.start_watcher()
        worktree = self.add_worktree("other")
        self.assertEqual(self.difftate(folder=worktree).returncode, 0)
        self.open_thread("Why an f-string here?")
        wait_for("the worktree's banner in the log", lambda: any(
            about(line, worktree, "other") for line in self.terminal().splitlines()))

        lines = [line for line in self.terminal().splitlines() if line]

        self.assertIn("difftate watcher started", self.terminal())
        self.assertNotIn("difftate watcher started", self.difftate_output, "the watcher writes to its log, not here")
        for line in lines:
            self.assertRegex(line, rf"^{STAMP} (\(watcher\)|/\S.* \([^()]+\)): ", line)

    def test_difftate_log_prints_the_log_and_follows_new_lines_until_ctrl_c(self):
        self.start_watcher()
        shown = os.path.join(self.tmp, "log-shown.txt")
        with open(shown, "w") as out:
            follower = subprocess.Popen([sys.executable, DIFFTATE, "log"], cwd=self.repo, env=self.env,
                                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        self.addCleanup(lambda: follower.poll() is None and follower.kill())
        wait_for("the log so far", lambda: "difftate watcher started" in read(shown))

        worktree = self.add_worktree("other")
        self.assertEqual(self.difftate(folder=worktree).returncode, 0)
        wait_for("the new folder's line", lambda: any(about(line, worktree, "other") for line in read(shown).splitlines()))

        follower.send_signal(signal.SIGINT)
        self.assertEqual(follower.wait(timeout=15), 0, "Ctrl+C ends it cleanly")
        self.assertTrue(alive(self.watcher.pid), "ending the log doesn't stop the watcher")


def git(repo, env, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


class TamperingIsRoutedToTheEntryWhoseReviewWasTampered(unittest.TestCase):
    """The watcher's own wiring, on fakes: no process, no git."""

    def watcher(self):
        warned = []
        watcher = Watcher({"interval": 1}, SimpleNamespace())

        def entry(name):
            loop = SimpleNamespace(warn_tampered=lambda ids, name=name: warned.append((name, list(ids))))
            return SimpleNamespace(loop=loop)

        return watcher, entry, warned

    def test_only_the_entry_whose_review_was_tampered_is_warned(self):
        watcher, entry, warned = self.watcher()
        first, second = entry("first"), entry("second")
        watcher.folders = {"/a": first, "/b": second}

        watcher.tampered(second, ["abcdef123456"])

        self.assertEqual(warned, [("second", ["abcdef123456"])])

    def test_an_entry_with_no_loop_yet_is_not_an_error(self):
        watcher, _, warned = self.watcher()

        watcher.tampered(SimpleNamespace(loop=None), ["abcdef123456"])

        self.assertEqual(warned, [])


if __name__ == "__main__":
    unittest.main()
