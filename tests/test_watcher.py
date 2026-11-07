"""Seam 1: the running watcher.

Each test creates a temporary git repository, starts the real watcher with a
fake agent swapped in through `--cmd`, and drives it through the review API.
HOME points into the temporary folder, so the review history stays there too.
"""
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHER = os.path.join(ROOT, "difftate-watch.py")
FAKE_AGENT = os.path.join(ROOT, "tests", "fake_agent.py")
TIMEOUT_S = 30


def wait_for(what, check, timeout=TIMEOUT_S):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie is dead for our purposes: it only waits for its parent to reap it
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout
    return bool(state.strip()) and not state.strip().startswith("Z")


def descendants(pid):
    rows = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True).stdout.split("\n")
    children = {}
    for row in rows:
        parts = row.split()
        if len(parts) == 2:
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def git(repo, env, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


class Harness:
    """A temporary repository on the branch "feature", and the watcher on it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftate-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.tmp, "repo")
        self.agent_dir = os.path.join(self.tmp, "agent")
        bin_dir = os.path.join(self.tmp, "bin")
        for d in (self.home, self.repo, bin_dir):
            os.makedirs(d)
        # The watcher opens the review with `open`: make it a no-op
        with open(os.path.join(bin_dir, "open"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(bin_dir, "open"), 0o755)

        # Git reads its config from the test's HOME only: no signing, no hooks
        with open(os.path.join(self.home, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n")
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("CLAUDE_CONFIG_DIR", "DT_OPEN", "DT_HERDR", "XDG_CONFIG_HOME")}
        self.env.update(HOME=self.home, PATH=os.pathsep.join([bin_dir, os.environ["PATH"]]),
                        GIT_CONFIG_NOSYSTEM="1", FAKE_AGENT_DIR=self.agent_dir)

        git(self.repo, self.env, "init", "-q", "-b", "main")
        self.write("app.py", "def greet(name):\n    return 'hi ' + name\n")
        git(self.repo, self.env, "add", ".")
        git(self.repo, self.env, "commit", "-q", "-m", "first")
        git(self.repo, self.env, "checkout", "-q", "-b", "feature")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.output = []
        self.extra_args = []
        self.watcher = None
        self.agent_cmd = FAKE_AGENT

    def tearDown(self):
        if self.watcher and self.watcher.poll() is None:
            self.stop_watcher()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def write(self, path, text):
        with open(os.path.join(self.repo, path), "w") as f:
            f.write(text)

    def watcher_command(self):
        return [sys.executable, WATCHER, "--tool", "claude", "--cmd", self.agent_cmd,
                "--cwd", self.repo, "--interval", "0.2", *self.extra_args]

    def launch_watcher(self):
        self.watcher = subprocess.Popen(
            self.watcher_command(), cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(self.watcher.stdout.close)
        threading.Thread(target=self._read_output, daemon=True).start()

    def start_watcher(self):
        self.launch_watcher()
        api_file = os.path.join(self.repo, ".git", "difftate", "api.json")
        def served():
            # This watcher's own api.json: one killed earlier leaves its own behind
            try:
                with open(api_file) as f:
                    info = json.load(f)
            except (OSError, ValueError):
                return None
            return info if info.get("pid") == self.watcher.pid else None

        wait_for("the review API", lambda: served() or self.watcher.poll() is not None)
        self.assertIsNone(self.watcher.poll(), "watcher exited:\n" + self.terminal())
        self.port = served()["port"]
        with open(os.path.join(self.repo, ".git", "difftate", "token")) as f:
            self.token = f.read().strip()

    def _read_output(self):
        for line in self.watcher.stdout:
            self.output.append(line)

    def terminal(self):
        return "".join(self.output)

    def stop_watcher(self):
        self.watcher.send_signal(signal.SIGINT)
        try:
            self.watcher.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.watcher.kill()
            raise

    def api(self, method, path, payload=None, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers,
                                     data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"null")

    def read(self, path):
        with open(os.path.join(self.repo, path)) as f:
            return f.read()

    def open_thread(self, body, line=2, file="app.py", end=None, anchor_code=None, **payload):
        """A thread on <file>'s lines <line>..<end> (new side), with the code on them
        on disk now, or <anchor_code>."""
        end = end or line
        code = anchor_code or "\n".join(self.read(file).split("\n")[line - 1:end])
        return self.api("POST", "/api/threads", dict({
            "anchor": {"file": file, "side": "new", "startLine": line, "endLine": end, "code": code},
            "body": body}, **payload))

    def thread(self, tid):
        return next(t for t in self.api("GET", "/api/threads") if t["id"] == tid)

    def comments(self, tid):
        return [(c["kind"], c["body"]) for c in self.thread(tid)["comments"]]

    def bodies(self, tid):
        return [body for _, body in self.comments(tid)]

    def note(self, tid, kind, containing=""):
        """The body of the thread's first note of <kind> that contains <containing>, or None."""
        return next((b for k, b in self.comments(tid) if k == kind and containing in b), None)

    def state(self, tid):
        return self.thread(tid)["state"]

    def release_agent(self):
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(os.path.join(self.agent_dir, "go"), "w"):
            pass

    def silence_agent(self, silent=True, runs=()):
        """The coding agent replies to no thread (in every run, or only in <runs>)."""
        path = os.path.join(self.agent_dir, "silent")
        if silent:
            os.makedirs(self.agent_dir, exist_ok=True)
            with open(path, "w") as f:
                f.write(",".join(str(n) for n in runs))
        else:
            os.remove(path)

    def prompts(self):
        """The prompt of every run so far."""
        try:
            with open(os.path.join(self.agent_dir, "prompts")) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def agent_args(self):
        """The command-line arguments of the latest run."""
        with open(os.path.join(self.agent_dir, "args")) as f:
            return json.load(f)

    def dispatches(self):
        return self.terminal().count("New/changed threads detected")

    def refused(self, method, path, payload):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.api(method, path, payload)
        refused.exception.close()
        return refused.exception.code


class WatcherTest(Harness, unittest.TestCase):

    def test_comment_gets_working_note_then_reply(self):
        self.start_watcher()
        thread = self.open_thread("Why an f-string here?")
        tid = thread["id"]
        self.assertIn(thread["state"], ("waiting", "working"), "the watcher may dispatch it at once")
        self.assertEqual(thread["comments"][0]["author"], "reviewer")

        working = wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        self.assertIn("`Read app.py`", working)
        self.assertEqual(self.state(tid), "working")

        self.release_agent()
        wait_for("the done note and the reply", lambda: self.note(tid, "progress", "Done") and self.note(tid, "reply"))
        self.assertEqual([k for k, _ in self.comments(tid)], ["comment", "progress", "reply"],
                         "comment, one progress note (edited in place), reply")
        self.assertTrue(self.bodies(tid)[1].startswith("✅ **Done** in "), self.bodies(tid))
        self.assertEqual(self.bodies(tid)[2], f"Fake answer to {tid[:8]}.")
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertEqual([c["author"] for c in self.thread(tid)["comments"]], ["reviewer", "difftate", "agent"])

        out = self.terminal()
        self.assertRegex(out, r"\[\d\d:\d\d:\d\d\] New/changed threads detected — dispatching to claude")
        self.assertIn("🔧 Read  app.py", out)
        self.assertRegex(out, r"✅ done in \d+s, \$0\.0123")

    def test_the_agent_answers_with_dt_reply_and_difftate_marks_it_a_reply(self):
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]

        wait_for("the replied state", lambda: self.state(tid) == "replied")

        reply = self.thread(tid)["comments"][-1]
        self.assertEqual((reply["author"], reply["kind"], reply["body"]),
                         ("agent", "reply", f"Fake answer to {tid[:8]}."),
                         "the coding agent wrote only its answer: no marker")
        self.assertRegex(self.prompts()[0], r"\S*dt-reply <thread> \"<answer>\"")

    def test_each_claude_run_may_not_write_the_store_or_read_the_token(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))

        args = self.agent_args()
        settings = json.loads(args[args.index("--settings") + 1])
        sandbox = settings["sandbox"]["filesystem"]
        with open(os.path.join(self.agent_dir, "run_dir")) as f:
            run_dir = f.read()
        store = os.path.realpath(os.path.join(self.repo, ".git", "difftate"))
        self.assertTrue(run_dir and os.path.isdir(run_dir), "the run has its own folder")
        self.assertEqual(sandbox["allowWrite"], [run_dir])
        self.assertEqual(sandbox["denyWrite"], [store])
        self.assertEqual(sandbox["denyRead"], [os.path.join(store, "token")])
        # The sandbox binds only Bash: Claude's own file tools need permission rules
        self.assertEqual(settings["permissions"]["deny"],
                         [f"Edit(/{store}/**)", f"Read(/{os.path.join(store, 'token')})"])
        self.assertFalse(os.path.realpath(run_dir).startswith(store + os.sep), "the run's folder is outside the store")

        self.release_agent()
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertFalse(os.path.exists(run_dir), "the run's folder goes when the run ends")

    def test_a_coding_agent_that_cant_start_fails_its_threads_and_the_watcher_keeps_going(self):
        self.agent_cmd = os.path.join(self.tmp, "agent.py")
        shutil.copy(FAKE_AGENT, self.agent_cmd)
        os.chmod(self.agent_cmd, 0o755)
        self.release_agent()
        self.start_watcher()
        os.chmod(self.agent_cmd, 0o644)  # it can't start any more

        tid = self.open_thread("Why an f-string here?")["id"]

        final = wait_for("the failed progress note", lambda: self.note(tid, "progress", "no reply"))
        self.assertTrue(final.startswith("❌ **Failed** after "), final)
        self.assertIn("could not start", final)
        self.assertIn("could not start claude", self.terminal())
        self.assertIsNone(self.watcher.poll(), "the watcher keeps going:\n" + self.terminal())

        os.chmod(self.agent_cmd, 0o755)
        self.api("POST", f"/api/threads/{tid}/comments", {"body": "Please try again."})
        wait_for("the replied state", lambda: self.state(tid) == "replied")

    def test_a_reply_to_a_thread_outside_the_run_is_not_posted(self):
        self.release_agent()
        self.start_watcher()
        done = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(done) == "replied")
        self.api("PATCH", f"/api/threads/{done}/status", {"status": "resolved"})
        with open(os.path.join(self.agent_dir, "rogue"), "w") as f:
            f.write(done)

        tid = self.open_thread("Rename greet to welcome?", line=1)["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        time.sleep(0.5)  # a few polls

        self.assertNotIn("A reply nobody asked for.", self.bodies(done))
        self.assertNotIn("A reply nobody asked for.", self.bodies(tid))

    def test_thread_written_during_a_run_is_queued_then_answered_next(self):
        self.start_watcher()
        first = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(first, "progress", "Working"))

        second = self.open_thread("Rename greet to welcome?", line=1)["id"]
        queued = wait_for("a queued note", lambda: self.note(second, "queued"))
        self.assertEqual(queued, "🕒 **Queued** — agent is busy with another comment, will pick this up next.")
        self.assertEqual(self.state(second), "queued")
        self.assertIn(f"Queued thread {second[:8]} (agent busy)", self.terminal())

        self.release_agent()
        wait_for("the done note and the reply",
                 lambda: self.note(second, "progress", "Done") and self.note(second, "reply"))
        self.assertEqual([k for k, _ in self.comments(second)], ["comment", "progress", "reply"],
                         "the queued note becomes the progress note")
        wait_for("both threads replied", lambda: self.state(first) == self.state(second) == "replied")

    def test_a_queued_note_followed_by_another_comment_says_it_was_picked_up(self):
        self.start_watcher()
        first = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(first, "progress", "Working"))
        second = self.open_thread("Rename greet to welcome?", line=1)["id"]
        wait_for("a queued note", lambda: self.note(second, "queued"))
        self.api("POST", f"/api/threads/{second}/comments", {"body": "Or to hello?"})

        self.release_agent()
        wait_for("the replied state", lambda: self.state(second) == "replied")

        self.assertEqual(self.comments(second), [
            ("comment", "Rename greet to welcome?"),
            ("queued", "🕒 **Queued** — picked up by the next run (below)."),
            ("comment", "Or to hello?"),
            ("progress", self.note(second, "progress")),
            ("reply", f"Fake answer to {second[:8]}."),
        ])
        self.assertTrue(self.note(second, "progress").startswith("✅ **Done** in "))

    def test_a_run_whose_coding_agent_crashes_fails_its_reused_queued_note_and_leaves_the_last_runs_note(self):
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        done = self.note(tid, "progress")
        self.assertTrue(done.startswith("✅ **Done** in "), done)

        # A follow-up while another thread's run is busy: the thread gets a queued note
        os.remove(os.path.join(self.agent_dir, "go"))
        other = self.open_thread("Rename greet to welcome?", line=1)["id"]
        wait_for("a working progress note", lambda: self.note(other, "progress", "Working"))
        self.api("POST", f"/api/threads/{tid}/comments", {"body": "And why not str.format?"})
        wait_for("a queued note", lambda: self.note(tid, "queued"))

        # The next run reuses that queued note, and its coding agent crashes at once
        with open(os.path.join(self.agent_dir, "crash"), "w") as f:
            f.write("3")
        self.release_agent()
        wait_for("a third run", lambda: len(self.prompts()) == 3)
        wait_for("the failed progress note", lambda: "no reply" in self.bodies(tid)[-1].lower())
        self.assertEqual(self.state(tid), "failed")

        comments = self.comments(tid)
        self.assertEqual([k for k, _ in comments], ["comment", "progress", "reply", "comment", "progress"])
        self.assertEqual(comments[1][1], done, "the last run's note is unchanged")
        self.assertRegex(comments[4][1], r"^❌ \*\*Failed\*\* after \d+s\n\nAgent exited without finishing — "
                                         r"check the watcher terminal\.\n\nNo reply\.$")

    def test_a_follow_up_during_a_run_on_the_same_thread_is_answered_in_the_next_run(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))

        self.api("POST", f"/api/threads/{tid}/comments", {"body": "And why not str.format?"})
        self.assertEqual(self.state(tid), "working")
        self.release_agent()

        wait_for("a second run", lambda: len(self.prompts()) == 2)
        self.assertNotIn("And why not str.format?", self.prompts()[0])
        self.assertIn("reviewer (new): And why not str.format?", self.prompts()[1])
        self.assertIn("reviewer: Why an f-string here?", self.prompts()[1])
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertEqual([k for k, _ in self.comments(tid)],
                         ["comment", "progress", "comment", "reply", "progress", "reply"])

    def test_a_run_sent_only_a_follow_up_fails_when_it_doesnt_reply(self):
        self.silence_agent(runs=[2])
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        self.api("POST", f"/api/threads/{tid}/comments", {"body": "And why not str.format?"})
        self.release_agent()

        wait_for("a second run", lambda: len(self.prompts()) == 2)
        final = wait_for("the failed progress note", lambda: self.note(tid, "progress", "no reply"))
        self.assertTrue(final.startswith("❌ **Failed** after "), final)
        self.assertEqual(self.state(tid), "failed")
        self.assertEqual([k for k, _ in self.comments(tid)], ["comment", "progress", "comment", "reply", "progress"])

    def test_a_run_with_no_reply_leaves_the_thread_failed_until_a_new_comment(self):
        self.silence_agent()
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]

        final = wait_for("the failed progress note", lambda: self.note(tid, "progress", "no reply"))
        self.assertEqual(self.state(tid), "failed")
        self.assertTrue(final.startswith("❌ **Failed** after "), final)
        self.assertIn("no reply", final)
        self.assertIn(f"No reply to thread {tid[:8]}", self.terminal())
        time.sleep(1.5)  # several polls
        self.assertEqual((self.dispatches(), len(self.prompts())), (1, 1), "not dispatched again")
        self.assertEqual(self.state(tid), "failed")

        self.silence_agent(False)
        self.api("POST", f"/api/threads/{tid}/comments", {"body": "Please try again."})
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertEqual(self.dispatches(), 2)
        self.assertIn("reviewer (new): Please try again.", self.prompts()[1])
        self.assertIn("reviewer: Why an f-string here?", self.prompts()[1])

    def test_a_run_that_fails_keeps_the_coding_agents_error_and_says_no_reply(self):
        self.silence_agent()
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(os.path.join(self.agent_dir, "error"), "w") as f:
            f.write("The model is overloaded.")
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]

        final = wait_for("the failed progress note", lambda: self.note(tid, "progress", "No reply"))
        self.assertRegex(final, r"^❌ \*\*Failed\*\* after \d+s\n- ✅ `Read app\.py`\n\nThe model is overloaded\.\n\nNo reply\.$")
        self.assertEqual(self.state(tid), "failed")

    def test_a_failed_thread_stays_failed_after_a_restart(self):
        self.silence_agent()
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the failed progress note", lambda: self.note(tid, "progress", "no reply"))
        self.stop_watcher()

        self.output.clear()
        self.start_watcher()
        time.sleep(1.5)  # several polls

        self.assertEqual(self.state(tid), "failed")
        self.assertEqual((self.dispatches(), len(self.prompts())), (0, 1), "not dispatched again")

    def test_a_run_stopped_by_ctrl_c_leaves_its_threads_failed(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        self.stop_watcher()

        self.start_watcher()
        self.assertEqual(self.state(tid), "failed")
        final = self.note(tid, "progress")
        self.assertTrue(final.startswith("❌ **Failed** after "), final)
        self.assertRegex(final, r"[Nn]o reply \(the watcher stopped\)")

    def test_closing_the_terminal_stops_the_run_and_every_process_it_started(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: any("Working" in b for b in self.bodies(tid)))
        started = descendants(self.watcher.pid)

        self.watcher.send_signal(signal.SIGHUP)
        self.watcher.wait(timeout=15)

        wait_for("every started process to stop", lambda: not [p for p in started if alive(p)], timeout=10)

    def second_watcher(self, *args):
        command = self.watcher_command()
        command[command.index("--tool"):command.index("--tool")] = list(args)
        return subprocess.run(command, cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)

    def test_a_second_watcher_start_switches_the_running_watchers_view_and_exits(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.start_watcher()
        first = (self.watcher, self.port, self.token)

        second = self.second_watcher("--ref", "HEAD~1")

        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn(f"difftate is already running for this repository (pid {self.watcher.pid})", second.stdout)
        self.assertIn("switched it to the commits after HEAD~1", second.stdout)
        self.assertEqual(self.api("GET", "/api/view"), {"view": "HEAD~1"})
        self.assertEqual(self.api("GET", "/api/changeset")["view"], "HEAD~1")
        wait_for("the switch in the terminal", lambda: "Showing the commits after HEAD~1" in self.terminal())
        self.assertIsNone(self.watcher.poll(), "the running watcher keeps going")
        self.assertEqual((self.watcher, self.port, self.token), first)
        with open(os.path.join(self.repo, ".git", "difftate", "token")) as f:
            self.assertEqual(f.read().strip(), self.token, "the first watcher's token is kept")
        self.assertEqual(self.api("GET", "/api/threads"), [])

        # No view: all changes. A view that isn't one changes nothing
        self.assertEqual(self.second_watcher().returncode, 0)
        started = {"view": ""}
        self.assertEqual(self.api("GET", "/api/view"), started)
        bad = self.second_watcher("--ref", "nope")
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("no view 'nope'", bad.stdout)
        self.assertEqual(self.api("GET", "/api/view"), started)

    def test_an_interval_that_is_not_a_positive_finite_number_is_refused(self):
        for value in ["-1", "0", "inf", "nan"]:
            with self.subTest(value=value):
                command = self.watcher_command()
                command[command.index("--interval") + 1] = value
                run = subprocess.run(command, cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn(f"Error: --interval must be a number of seconds, not '{value}'",
                              run.stdout + run.stderr)

    def test_only_a_reviewer_opens_a_thread_or_changes_its_status(self):
        self.silence_agent()  # keep the coding agent out of the thread
        self.start_watcher()
        anchor = {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2}
        for author in ("agent", "difftate"):
            self.assertEqual(self.refused("POST", "/api/threads",
                                          {"anchor": anchor, "body": "Hi", "author": author}), 403, author)
        self.assertEqual(self.api("GET", "/api/threads"), [])

        tid = self.open_thread("Why an f-string here?", author="reviewer")["id"]
        for author in ("agent", "difftate"):
            self.assertEqual(self.refused("PATCH", f"/api/threads/{tid}/status",
                                          {"status": "resolved", "author": author}), 403, author)
        self.assertEqual(self.thread(tid)["status"], "open")

        self.api("PATCH", f"/api/threads/{tid}/status", {"status": "resolved"})
        self.assertEqual((self.thread(tid)["status"], self.thread(tid)["state"]), ("resolved", None))

    def test_only_notes_can_be_edited_as_notes(self):
        self.start_watcher()
        thread = self.open_thread("Why an f-string here?")
        comment_id = thread["comments"][0]["id"]

        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.api("PATCH", f"/api/notes/{comment_id}", {"kind": "progress", "body": "✅ **Done**"})
        refused.exception.close()

        self.assertEqual(refused.exception.code, 403)
        self.assertEqual(self.bodies(thread["id"])[0], "Why an f-string here?", "the comment is unchanged")

    def test_review_api_refuses_requests_without_the_token(self):
        self.start_watcher()
        token_file = os.path.join(self.repo, ".git", "difftate", "token")
        self.assertEqual(os.stat(token_file).st_mode & 0o777, 0o600, "only the user can read the token")

        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": self.token}):
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/threads", headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(req, timeout=10)
            refused.exception.close()
            self.assertEqual(refused.exception.code, 401, headers)
        self.assertEqual(self.api("GET", "/api/threads"), [])

    def test_ctrl_c_stops_the_watcher_the_run_and_every_process_it_started(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: any("Working" in b for b in self.bodies(tid)))
        started = descendants(self.watcher.pid)
        with open(os.path.join(self.agent_dir, "pid")) as f:
            agent_pid = int(f.read())
        self.assertIn(agent_pid, started)

        self.stop_watcher()

        self.assertEqual(self.watcher.returncode, 0)
        wait_for("every started process to stop", lambda: not [p for p in started if alive(p)], timeout=10)
        out = self.terminal()
        self.assertIn("Stopping watcher...", out)
        self.assertIn("Stopping running agent (pid ", out)
        self.assertTrue(out.rstrip().endswith("Done."), out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "difftate", "api.json")))

    def test_a_thread_the_agent_answered_stays_replied_when_ctrl_c_stops_the_run(self):
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(os.path.join(self.agent_dir, "linger"), "w"):
            pass
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the reply", lambda: self.note(tid, "reply"))
        self.assertEqual(self.state(tid), "working", "the run hasn't ended")

        self.stop_watcher()
        self.output.clear()
        self.start_watcher()
        time.sleep(1.5)  # several polls

        self.assertEqual(self.state(tid), "replied")
        self.assertEqual((self.dispatches(), len(self.prompts())), (0, 1), "not dispatched again")
        self.assertEqual([k for k, _ in self.comments(tid)], ["comment", "progress", "reply"])
        self.assertTrue(self.note(tid, "progress").startswith("⏹ **Stopped** after "), self.note(tid, "progress"))

    def events_file(self):
        reviews = os.path.join(self.repo, ".git", "difftate", "reviews")
        [review] = os.listdir(reviews)
        return os.path.join(reviews, review, "events.jsonl")

    def kill_watcher(self):
        """kill -9: the watcher gets no chance to stop its run. Its processes
        are stopped here, as the terminal would."""
        started = descendants(self.watcher.pid)
        self.watcher.kill()
        self.watcher.wait(timeout=15)
        for pid in started:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_a_watcher_killed_during_a_run_doesnt_send_its_threads_again(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))

        self.kill_watcher()
        self.output.clear()
        self.release_agent()
        self.start_watcher()
        time.sleep(1.5)  # several polls

        self.assertEqual(self.state(tid), "failed")
        self.assertEqual((self.dispatches(), len(self.prompts())), (0, 1), "not dispatched again")
        self.assertRegex(self.note(tid, "progress"), r"^❌ \*\*Failed\*\* — no reply \(the watcher stopped\)")
        with open(self.events_file()) as f:
            runs = [e for e in map(json.loads, f) if e["type"] in ("run", "run-ended")]
        self.assertEqual([(e["type"], e.get("outcome")) for e in runs], [("run", None), ("run-ended", "interrupted")])

        self.api("POST", f"/api/threads/{tid}/comments", {"body": "Please try again."})
        wait_for("the replied state", lambda: self.state(tid) == "replied")

    def test_a_thread_answered_before_the_watcher_was_killed_stays_replied(self):
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(os.path.join(self.agent_dir, "linger"), "w"):
            pass
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the reply", lambda: self.note(tid, "reply"))

        self.kill_watcher()
        self.output.clear()
        self.start_watcher()
        time.sleep(1.5)  # several polls

        self.assertEqual(self.state(tid), "replied")
        self.assertEqual((self.dispatches(), len(self.prompts())), (0, 1), "not dispatched again")

    def opened_urls(self):
        try:
            with open(os.path.join(self.tmp, "opened")) as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []

    def page(self, path, cookie=None, headers=None):
        """(status, headers, body) of a GET of the browser viewer's <path>, with no
        redirect followed."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers=dict(headers or {}, **({"Cookie": cookie} if cookie else {})))
            r = conn.getresponse()
            return r.status, r.headers, r.read().decode()
        finally:
            conn.close()

    def launch_page(self, link):
        """Open <link> as the browser would: its launch code for the page's cookie."""
        status, headers, _ = self.page(link[len(f"http://127.0.0.1:{self.port}"):])
        self.assertEqual((status, headers["Location"]), (303, "/"))
        cookie = headers["Set-Cookie"]
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie)
        return cookie.split(";")[0]

    def test_open_browser_opens_difftates_own_page_with_a_launch_code(self):
        # A fake `open` that records what it was asked to open
        with open(os.path.join(self.tmp, "bin", "open"), "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {os.path.join(self.tmp, "opened")}\n')
        self.env["DT_OPEN"] = "browser"
        self.start_watcher()

        [link] = wait_for("the browser to open", self.opened_urls)
        self.assertRegex(link, rf"^http://127\.0\.0\.1:{self.port}/\?launch=[\w-]+$")
        self.assertNotIn(self.token, link, "the review token never leaves its file")
        self.assertIn(link, self.terminal(), "the terminal shows the link too")
        cookie = self.launch_page(link)
        self.assertNotIn(self.token, cookie)

        status, headers, html = self.page("/", cookie)
        self.assertEqual((status, headers["Content-Type"]), (200, "text/html; charset=utf-8"))
        self.assertNotIn(self.token, html)
        scripts = re.findall(r'<script[^>]* src="([^"]+)"', html)
        self.assertTrue(scripts, html)
        for src in [*scripts, "diff.js"]:
            status, headers, _ = self.page("/" + src, cookie)
            self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript; charset=utf-8"), src)
        # The page calls the API with its cookie, and a header no other site's page can send
        status, _, body = self.page("/api/view", cookie, {"X-Difftate": "page"})
        self.assertEqual((status, json.loads(body)), (200, {"view": ""}))

        # A second `difftate --open browser` opens it again, with a new launch code
        self.assertEqual(self.second_watcher("--open", "browser").returncode, 0)
        links = wait_for("the browser to open again", lambda: len(self.opened_urls()) == 2 and self.opened_urls())
        self.assertNotEqual(links[1], link)
        self.launch_page(links[1])

    def test_a_used_launch_code_is_refused(self):
        with open(os.path.join(self.tmp, "bin", "open"), "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {os.path.join(self.tmp, "opened")}\n')
        self.env["DT_OPEN"] = "browser"
        self.start_watcher()
        [link] = wait_for("the browser to open", self.opened_urls)
        self.launch_page(link)

        status, headers, body = self.page(link[len(f"http://127.0.0.1:{self.port}"):])
        self.assertEqual(status, 401)
        self.assertIsNone(headers["Set-Cookie"], "no cookie for a used code")
        self.assertNotIn("<script", body)

    def test_the_browser_viewer_refuses_requests_without_its_cookie(self):
        with open(os.path.join(self.tmp, "bin", "open"), "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> {os.path.join(self.tmp, "opened")}\n')
        self.env["DT_OPEN"] = "browser"
        self.start_watcher()
        cookie = self.launch_page(wait_for("the browser to open", self.opened_urls)[0])
        name = cookie.split("=")[0]

        for path in ("/", "/?launch=wrong", f"/?token={self.token}", "/app.js", "/diff.js"):
            for given in (None, f"{name}=wrong"):
                status, headers, body = self.page(path, given)
                self.assertEqual(status, 401, (path, given))
                self.assertIsNone(headers["Set-Cookie"], path)
                self.assertNotIn("<script", body, path)
        # The API takes the cookie only with the page's header, and only from its own origin
        for headers in ({}, {"X-Difftate": "page", "Origin": "http://127.0.0.1:1"}):
            status, _, _ = self.page("/api/view", cookie, headers)
            self.assertEqual(status, 401, headers)

    def test_a_thread_survives_a_commit(self):
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")

        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.assertEqual(self.state(tid), "replied")
        self.stop_watcher()
        self.start_watcher()

        self.assertEqual(self.state(tid), "replied")
        self.assertEqual(self.bodies(tid)[0], "Why an f-string here?")

    def viewed(self):
        return self.api("GET", "/api/viewed")["files"]

    def mark_viewed(self, file, viewed=True):
        return self.api("PUT", "/api/viewed", {"file": file, "viewed": viewed})["files"]

    def test_a_viewed_file_stays_viewed_after_a_restart_and_a_commit(self):
        self.write("other.py", "x = 1\n")
        self.start_watcher()

        self.assertEqual(self.viewed(), [])
        self.assertEqual(self.mark_viewed("app.py"), ["app.py"])
        self.stop_watcher()
        self.start_watcher()
        self.assertEqual(self.viewed(), ["app.py"])

        git(self.repo, self.env, "add", "app.py")
        git(self.repo, self.env, "commit", "-q", "-m", "Say hello")
        self.assertEqual(self.viewed(), ["app.py"], "a commit doesn't change the file's diff")

        self.assertEqual(self.mark_viewed("app.py", False), [])

    def test_an_edit_that_keeps_the_line_counts_clears_the_viewed_mark(self):
        self.write("other.py", "x = 1\n")
        self.start_watcher()
        self.mark_viewed("app.py")
        self.mark_viewed("other.py")

        self.write("app.py", "def greet(name):\n    return f'hey {name}'\n")

        self.assertEqual(self.viewed(), ["other.py"], "same line counts, other code: no longer viewed")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.assertEqual(self.viewed(), ["other.py"], "the mark was cleared: undoing the edit doesn't bring it back")

    def test_an_edit_inside_a_new_untracked_file_clears_the_viewed_mark(self):
        self.write("new.py", "x = 1\n")
        self.start_watcher()
        self.assertEqual(self.mark_viewed("new.py"), ["new.py"])

        self.write("new.py", "x = 2\n")

        self.assertEqual(self.viewed(), [])

    def test_only_a_file_in_the_changeset_can_be_marked_viewed(self):
        self.start_watcher()
        status = self.refused("PUT", "/api/viewed", {"file": "nope.py", "viewed": True})
        self.assertEqual(status, 404)

    def test_the_base_is_the_default_branch_unless_base_says_otherwise(self):
        # The remote's default branch is "trunk", one commit behind
        git(self.repo, self.env, "update-ref", "refs/remotes/origin/trunk", "main")
        git(self.repo, self.env, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.write("new.py", "print('new')\n")
        self.start_watcher()

        review = self.api("GET", "/api/review")
        self.assertEqual((review["branch"], review["base"]), ("feature", "origin/trunk"))
        changeset = self.api("GET", "/api/changeset")
        self.assertEqual(changeset["base"], "origin/trunk")
        self.assertIn("+    return f'hello {name}'", changeset["diff"])
        self.assertIn("+++ b/new.py", changeset["diff"], "new untracked files are in the changeset")
        self.stop_watcher()

        self.extra_args = ["--base", "main"]
        self.start_watcher()
        other = self.api("GET", "/api/review")
        self.assertEqual(other["base"], "main")
        self.assertNotEqual(other["id"], review["id"], "another base is another review")

    # ── Views ────────────────────────────────────────────────────────────────
    def two_commits_then_edits(self):
        """On feature: commit "one" (app.py), commit "two" (two.py), then staged.py
        staged, app.py edited and new.py untracked."""
        git(self.repo, self.env, "commit", "-q", "-am", "one")
        self.write("two.py", "two = 2\n")
        git(self.repo, self.env, "add", "two.py")
        git(self.repo, self.env, "commit", "-q", "-m", "two")
        self.write("staged.py", "staged = 1\n")
        git(self.repo, self.env, "add", "staged.py")
        self.write("app.py", self.read("app.py") + "greet('you')\n")
        self.write("new.py", "new = 1\n")

    def files_in(self, view=None):
        query = "" if view is None else "?view=" + urllib.parse.quote(view)
        changeset = self.api("GET", "/api/changeset" + query)
        return changeset["view"], sorted(re.findall(r"^\+\+\+ b/(\S+)", changeset["diff"], re.M))

    def test_the_api_returns_the_changeset_for_each_view(self):
        self.two_commits_then_edits()
        self.start_watcher()

        self.assertEqual(self.files_in(), ("", ["app.py", "new.py", "staged.py", "two.py"]), "all changes")
        self.assertEqual(self.files_in(""), ("", ["app.py", "new.py", "staged.py", "two.py"]))
        self.assertEqual(self.files_in("HEAD~1"), ("HEAD~1", ["app.py", "new.py", "staged.py", "two.py"]))
        self.assertEqual(self.files_in("HEAD"), ("HEAD", ["app.py", "new.py", "staged.py"]), "uncommitted")
        self.assertEqual(self.files_in("staged"), ("staged", ["staged.py"]))
        self.assertEqual(self.files_in("unstaged"), ("unstaged", ["app.py", "new.py"]))
        self.assertNotIn("+    return f'hello {name}'", self.api("GET", "/api/changeset?view=HEAD")["diff"],
                         "the HEAD view starts after the last commit")
        self.assertEqual(self.refused("GET", "/api/changeset?view=nope", None), 400)

    def placed(self, tid, view):
        thread = next(t for t in self.api("GET", "/api/threads?view=" + urllib.parse.quote(view)) if t["id"] == tid)
        return thread["anchor"]["startLine"], thread.get("inView", True)

    def test_threads_written_in_the_head_1_view_are_in_the_all_changes_view_too(self):
        self.two_commits_then_edits()
        self.release_agent()
        self.extra_args = ["--ref", "HEAD~1"]
        self.start_watcher()

        tid = self.open_thread("Why two?", line=1, file="two.py", view="HEAD~1")["id"]

        self.assertEqual(self.api("GET", "/api/view"), {"view": "HEAD~1"})
        self.assertIn(tid, [t["id"] for t in self.api("GET", "/api/threads")])
        self.assertEqual(self.placed(tid, ""), (1, True))
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertFalse(self.thread(tid)["outdated"])

    def test_a_thread_sits_by_its_code_in_every_view(self):
        self.write("long.py", self.LONG)
        git(self.repo, self.env, "add", "long.py")
        self.write("long.py", "import os\nimport re\nimport sys\n" + self.LONG + "tail = 1\n")
        self.release_agent()
        self.start_watcher()

        # Line 12 of the staged file is line 15 on disk
        tid = self.open_thread("Why 12?", line=12, file="long.py", view="staged",
                               anchor_code="line_12 = 12")["id"]
        time.sleep(0.5)  # a few polls
        self.assertFalse(self.thread(tid)["outdated"], "written on the staged code")
        self.assertEqual(self.placed(tid, "staged"), (12, True))
        self.assertEqual(self.placed(tid, "unstaged"), (15, True))
        self.assertEqual(self.placed(tid, ""), (15, True))

        # The last line is only on disk: not in the staged view
        tail = self.open_thread("Why a tail?", line=24, file="long.py")["id"]
        self.assertEqual(self.placed(tail, "staged"), (24, False))
        self.assertEqual(self.placed(tail, "HEAD"), (24, True))

    def test_an_old_side_thread_in_a_commit_view_follows_its_code_in_that_view(self):
        self.two_commits_then_edits()
        self.release_agent()
        self.start_watcher()

        # Before HEAD~1's commits, line 2 is the branch's own f-string: not in the base
        tid = self.api("POST", "/api/threads", {"body": "Why an f-string?", "view": "HEAD~1", "anchor": {
            "file": "app.py", "side": "old", "startLine": 2, "endLine": 2, "code": "    return f'hello {name}'"}})["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")

        self.assertFalse(self.thread(tid)["outdated"], "its code didn't change")
        self.assertEqual(self.placed(tid, "HEAD~1"), (2, True))
        self.assertFalse(self.placed(tid, "")[1], "the base doesn't have that code")
        self.assertIn(tid, [t["id"] for t in self.api("GET", "/api/threads?view=")])

    def test_the_watchers_argument_is_its_starting_view(self):
        self.two_commits_then_edits()
        self.extra_args = ["--ref", "staged"]
        self.start_watcher()

        self.assertEqual(self.files_in(), ("staged", ["staged.py"]))
        self.assertEqual(self.api("GET", "/api/view"), {"view": "staged"})

    def test_two_watchers_started_at_the_same_moment_cant_both_run(self):
        first, second = (subprocess.Popen(self.watcher_command(), cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                         for _ in range(2))
        watchers = [first, second]
        for w in watchers:
            self.addCleanup(w.stdout.close)
            self.addCleanup(lambda w=w: w.poll() is None and (w.kill(), w.wait()))

        ended = wait_for("one watcher to exit", lambda: [w for w in watchers if w.poll() is not None])
        time.sleep(1)  # the other keeps running
        self.assertEqual(len(ended), 1, "exactly one exits")
        [running] = [w for w in watchers if w.poll() is None]
        self.assertEqual(ended[0].returncode, 0)
        self.assertIn(f"already running for this repository (pid {running.pid})", ended[0].stdout.read())
        with open(os.path.join(self.repo, ".git", "difftate", "api.json")) as f:
            self.assertEqual(json.load(f)["pid"], running.pid)
        running.send_signal(signal.SIGINT)
        running.wait(timeout=15)

    def test_stored_lines_go_to_the_review_history_with_repository_and_branch(self):
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")

        def stored_lines():
            with open(self.events_file()) as f:
                return [json.loads(line) for line in f]
        stored = wait_for("the run's final note stored", lambda: (lines := stored_lines())[-1]["type"] == "note" and lines)
        history_dir = os.path.join(self.home, ".difftate", "history")

        def history_lines():
            # The review history is recorded just after the store keeps the lines
            months = os.listdir(history_dir) if os.path.isdir(history_dir) else []
            if not months:
                return []
            with open(os.path.join(history_dir, months[0])) as f:
                return [json.loads(line) for line in f]
        history = wait_for("the review history to catch up", lambda: len(lines := history_lines()) >= len(stored) and lines)
        self.assertEqual(len(os.listdir(history_dir)), 1)
        self.assertEqual([e["type"] for e in stored], ["opened", "comment", "run", "comment", "run-ended", "note"])
        self.assertEqual([{k: v for k, v in h.items() if k in e} for h, e in zip(history, stored)], stored)
        self.assertEqual({(h["repo"]["path"], h["branch"]) for h in history}, {(os.path.realpath(self.repo), "feature")})

    def test_an_edit_to_stored_lines_the_watcher_didnt_make_is_warned_about_and_restored(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        with open(self.events_file()) as f:
            kept = f.read()

        # The coding agent, with its sandbox off, rewrites the reviewer's comment and forges a reply
        forged = kept.replace("Why an f-string here?", "Looks great.") + json.dumps(
            {"type": "comment", "thread": tid, "id": "forged", "author": "agent", "kind": "reply",
             "body": "Forged.", "time": "2026-01-01T00:00:00.000Z", "seq": 99}) + "\n"
        with open(self.events_file(), "w") as f:
            f.write(forged)

        wait_for("the warning", lambda: "changed outside difftate" in self.terminal())
        self.assertIn(tid[:8], self.terminal())
        with open(self.events_file()) as f:
            self.assertEqual(f.read(), kept, "restored")
        self.assertEqual(self.bodies(tid)[0], "Why an f-string here?")

        self.release_agent()
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.assertIn("changed outside difftate", self.note(tid, "progress"))
        self.assertNotIn("Forged.", self.bodies(tid))

    # ── Threads follow their code, or become outdated ────────────────────────
    LONG = "".join(f"line_{n} = {n}\n" for n in range(1, 21))

    def anchor(self, tid):
        a = self.thread(tid)["anchor"]
        return a["startLine"], a["endLine"]

    def test_lines_added_above_a_thread_move_it_and_keep_it_current(self):
        self.write("long.py", self.LONG)
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why 12?", line=12, file="long.py")["id"]

        self.write("long.py", "import os\nimport re\nimport sys\n" + self.LONG)

        wait_for("the thread to move", lambda: self.anchor(tid) == (15, 15))
        thread = self.thread(tid)
        self.assertFalse(thread["outdated"])
        self.assertEqual(thread["anchor"]["code"], "line_12 = 12")
        self.assertEqual(self.read("long.py").split("\n")[14], "line_12 = 12", "it sits next to its code")

    def test_changing_a_threads_line_makes_it_outdated_with_its_original_code(self):
        self.write("long.py", self.LONG)
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why 12 and 13?", line=12, end=13, file="long.py")["id"]

        self.write("long.py", "import os\n" + self.LONG.replace("line_13 = 13", "line_13 = 'thirteen'"))

        wait_for("the outdated thread", lambda: self.thread(tid)["outdated"])
        anchor = self.thread(tid)["anchor"]
        self.assertEqual(anchor["code"], "line_12 = 12\nline_13 = 13", "it keeps the code it was written on")
        self.assertEqual((anchor["startLine"], anchor["endLine"]), (12, 13))
        self.assertIn(f"Thread {tid[:8]} is outdated", self.terminal())

        # Outdated stays outdated, also after a restart
        self.write("long.py", self.LONG)
        self.stop_watcher()
        self.start_watcher()
        time.sleep(0.5)  # a few polls
        self.assertTrue(self.thread(tid)["outdated"])

    def test_the_same_code_twice_never_moves_a_thread_to_the_wrong_copy(self):
        twice = "def hi(name):\n    return 'hi ' + name\n\n\ndef hey(name):\n    return 'hi ' + name\n"
        self.write("changed.py", twice)
        self.write("moved.py", twice)
        self.release_agent()
        self.start_watcher()
        changed = self.open_thread("Why the same as hi?", line=6, file="changed.py")["id"]
        moved = self.open_thread("Why the same as hi?", line=6, file="moved.py")["id"]

        # The second copy changes, the first is still there: outdated, not moved to the first copy
        self.write("changed.py", twice[:twice.rindex("'hi '")] + "'hey ' + name\n")
        # The first copy goes: the thread on the second copy follows it, to line 2
        self.write("moved.py", "def hey(name):\n    return 'hi ' + name\n")

        wait_for("the outdated thread", lambda: self.thread(changed)["outdated"])
        self.assertEqual(self.anchor(changed), (6, 6))
        wait_for("the thread to move", lambda: self.anchor(moved) == (2, 2))
        self.assertFalse(self.thread(moved)["outdated"])

    def test_a_comment_on_an_outdated_thread_is_dispatched_marked_outdated_with_its_original_code(self):
        self.write("long.py", self.LONG)
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why 12?", line=12, file="long.py")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        self.write("long.py", self.LONG.replace("line_12 = 12", "line_12 = 'twelve'"))
        wait_for("the outdated thread", lambda: self.thread(tid)["outdated"])

        self.api("POST", f"/api/threads/{tid}/comments", {"body": "Is it better now?"})

        wait_for("the second reply", lambda: len(self.prompts()) == 2 and self.state(tid) == "replied")
        thread = self.prompts()[1].split("## Reply to these threads")[1]
        self.assertIn(f"### Thread {tid[:8]} — long.py:12 — outdated: its code changed after the thread was written",
                      thread)
        self.assertIn("Code when the thread was written:\n```\nline_12 = 12\n```", thread)
        self.assertIn("reviewer (new): Is it better now?", thread)

    def test_an_old_side_thread_follows_its_code_in_the_base(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.release_agent()
        self.start_watcher()
        tid = self.api("POST", "/api/threads", {"body": "Why was this a concatenation?", "anchor": {
            "file": "app.py", "side": "old", "startLine": 2, "endLine": 2, "code": "    return 'hi ' + name"}})["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")

        # The base gets an import on top (in another worktree: a checkout of main would move
        # the watcher to main's review), and the branch is rebased onto it
        base = os.path.join(self.tmp, "base")
        git(self.repo, self.env, "worktree", "add", "-q", base, "main")
        with open(os.path.join(base, "app.py")) as f:
            old = f.read()
        with open(os.path.join(base, "app.py"), "w") as f:
            f.write("import os\n\n" + old)
        git(base, self.env, "commit", "-q", "-am", "Import os")
        git(self.repo, self.env, "rebase", "-q", "main")

        wait_for("the thread to move", lambda: self.anchor(tid) == (4, 4))
        self.assertFalse(self.thread(tid)["outdated"])

    def test_a_thread_written_on_code_no_longer_there_is_outdated_at_once(self):
        self.start_watcher()
        thread = self.api("POST", "/api/threads", {"body": "Why an f-string here?", "anchor": {
            "file": "app.py", "side": "new", "startLine": 2, "endLine": 2, "code": "    return 'hi ' + name"}})

        self.assertTrue(thread["outdated"], "the file changed since the viewer showed that code")
        self.assertEqual(thread["anchor"]["code"], "    return 'hi ' + name")

    def test_a_thread_written_before_snapshots_existed_starts_following_its_code(self):
        self.write("long.py", self.LONG)
        self.start_watcher()
        tid = self.open_thread("Why 12?", line=12, file="long.py")["id"]
        self.stop_watcher()
        # A thread an older difftate wrote: its anchor has no snapshot
        with open(self.events_file()) as f:
            events = [json.loads(line) for line in f]
        for e in events:
            if e["type"] == "opened":
                del e["anchor"]["snapshot"]
        with open(self.events_file(), "w") as f:
            f.write("".join(json.dumps(e) + "\n" for e in events))

        self.start_watcher()
        time.sleep(0.5)  # a few polls
        self.assertFalse(self.thread(tid)["outdated"], "its code is still on its lines")
        self.write("long.py", "import os\nimport re\nimport sys\n" + self.LONG)

        wait_for("the thread to move", lambda: self.anchor(tid) == (15, 15))
        self.assertFalse(self.thread(tid)["outdated"])

    def test_a_file_that_isnt_utf8_is_followed_too(self):
        latin = "".join(f"caf\xe9_{n} = {n}\n" for n in range(1, 21)).encode("latin-1")
        with open(os.path.join(self.repo, "latin.py"), "wb") as f:
            f.write(latin)
        self.release_agent()
        self.start_watcher()
        tid = self.api("POST", "/api/threads", {"body": "Why 12?", "anchor": {
            "file": "latin.py", "side": "new", "startLine": 12, "endLine": 12}})["id"]

        with open(os.path.join(self.repo, "latin.py"), "wb") as f:
            f.write(b"import os\n" + latin.replace(b"_12 = 12", b"_12 = 'twelve'"))

        wait_for("the outdated thread", lambda: self.thread(tid)["outdated"])
        self.assertIsNone(self.watcher.poll(), "the watcher keeps going:\n" + self.terminal())

    # ── Following the checked-out branch ─────────────────────────────────────
    def checkout(self, *args):
        """Check out another branch, and wait for the watcher to show its review."""
        git(self.repo, self.env, "checkout", "-q", *args)
        branch = subprocess.run(["git", "-C", self.repo, "symbolic-ref", "--short", "HEAD"],
                                capture_output=True, text=True, env=self.env).stdout.strip()
        wait_for(f"the review of {branch}", lambda: self.api("GET", "/api/review")["branch"] == branch)

    def test_switching_branches_shows_that_branchs_review_and_switching_back_restores_the_first(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.release_agent()
        self.start_watcher()
        first = self.api("GET", "/api/review")
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")
        before = self.thread(tid)

        self.checkout("-b", "other", "main")
        other = self.api("GET", "/api/review")
        self.assertNotEqual(other["id"], first["id"])
        self.assertEqual(self.api("GET", "/api/threads"), [], "a new branch starts a new, empty review")
        self.write("other.py", "x = 1\n")
        theirs = self.open_thread("Why 1?", line=1, file="other.py")["id"]
        wait_for("the reply on the other branch", lambda: self.state(theirs) == "replied")
        self.assertIn("The review of other against main", self.terminal())

        os.remove(os.path.join(self.repo, "other.py"))
        self.checkout("feature")
        self.assertEqual(self.api("GET", "/api/review")["id"], first["id"])
        self.assertEqual(self.api("GET", "/api/threads"), [before], "the first review, untouched")

    def test_a_run_in_progress_during_a_switch_finishes_on_its_own_threads(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.start_watcher()
        first = self.api("GET", "/api/review")["id"]
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))

        git(self.repo, self.env, "checkout", "-q", "-b", "other", "main")
        self.release_agent()
        wait_for("the review of other", lambda: self.api("GET", "/api/review")["branch"] == "other")
        self.assertEqual(self.api("GET", "/api/threads"), [], "the reply stays on its own thread")

        self.checkout("feature")
        self.assertEqual(self.api("GET", "/api/review")["id"], first)
        self.assertEqual(self.state(tid), "replied")
        self.assertEqual([k for k, _ in self.comments(tid)], ["comment", "progress", "reply"])
        self.assertTrue(self.bodies(tid)[1].startswith("✅ **Done** in "), self.bodies(tid))
        self.assertFalse(self.thread(tid)["outdated"], "the other branch's code didn't make it outdated")

    def test_while_a_run_keeps_the_watcher_on_its_branch_the_other_branchs_files_change_nothing(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.start_watcher()
        self.assertEqual(self.mark_viewed("app.py"), ["app.py"])
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))

        git(self.repo, self.env, "checkout", "-q", "-b", "other", "main")
        self.write("app.py", "def greet(name):\n    return 'hey ' + name\n")
        time.sleep(1)  # several polls of the run with the other branch checked out
        self.assertEqual(self.viewed(), ["app.py"], "the other branch's diff doesn't clear a mark")
        self.assertEqual(self.refused("PUT", "/api/viewed", {"file": "app.py"}), 409)
        self.assertEqual(self.refused("POST", "/api/threads", {"body": "On which branch?"}), 409)
        self.assertFalse(self.thread(tid)["outdated"])

        self.release_agent()
        wait_for("the review of other", lambda: self.api("GET", "/api/review")["branch"] == "other")
        git(self.repo, self.env, "checkout", "-q", "--", "app.py")
        self.checkout("feature")
        self.assertEqual(self.viewed(), ["app.py"])
        self.assertEqual(self.state(tid), "replied")

    def test_while_a_run_holds_the_old_review_no_thread_is_placed_in_the_new_branchs_code(self):
        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        self.assertEqual(self.api("GET", "/api/review")["waitingForRun"], False)

        # The same code one line lower on the other branch: placing it there would move the thread
        git(self.repo, self.env, "checkout", "-q", "-b", "other", "main")
        self.write("app.py", "# other\n" + "def greet(name):\n    return f'hello {name}'\n")
        review = wait_for("the review waiting for its run", lambda: (r := self.api("GET", "/api/review"))["waitingForRun"] and r)
        self.assertEqual((review["branch"], review["checkedOut"]), ("feature", "other"))
        changeset = self.api("GET", "/api/changeset")
        self.assertEqual((changeset["waitingForRun"], changeset["checkedOut"]), (True, "other"))
        for view in ("", "HEAD"):
            [t] = self.api("GET", "/api/threads?view=" + view)
            self.assertEqual((t["inView"], t["anchor"]["startLine"], t["anchor"]["endLine"]), (False, 2, 2), view)

        self.release_agent()
        wait_for("the review of other", lambda: self.api("GET", "/api/review")["branch"] == "other")
        review = self.api("GET", "/api/review")
        self.assertEqual((review["waitingForRun"], review["checkedOut"]), (False, "other"))

    def test_a_review_on_the_base_branch_lasts_one_commit(self):
        git(self.repo, self.env, "checkout", "-q", "main")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.release_agent()
        self.start_watcher()
        review = self.api("GET", "/api/review")
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("the replied state", lambda: self.state(tid) == "replied")

        git(self.repo, self.env, "commit", "-q", "-am", "Say hello")
        wait_for("a new review", lambda: self.api("GET", "/api/review")["id"] != review["id"])
        self.assertEqual(self.api("GET", "/api/threads"), [], "ADR 0002: the commit stood in for the branch")

    def test_a_view_the_new_branch_doesnt_have_falls_back_to_all_changes(self):
        for n in range(3):
            self.write(f"f{n}.py", f"n = {n}\n")
            git(self.repo, self.env, "add", ".")
            git(self.repo, self.env, "commit", "-q", "-m", f"commit {n}")
        self.extra_args = ["--ref", "HEAD~3"]
        self.start_watcher()
        git(self.repo, self.env, "checkout", "-q", "--orphan", "lone")
        git(self.repo, self.env, "commit", "-q", "-m", "only one")
        wait_for("the review of lone", lambda: self.api("GET", "/api/review")["branch"] == "lone")
        self.assertEqual(self.api("GET", "/api/view")["view"], "")


if __name__ == "__main__":
    unittest.main()
