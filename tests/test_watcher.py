"""Seam 1: the running watcher.

Each test creates a temporary git repository, starts the real watcher with a
fake agent swapped in through `--cmd`, and drives it through the review API.
HOME points into the temporary folder, so diffity's data stays there too.
"""
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


@unittest.skipUnless(shutil.which("diffity"), "diffity 0.9.5 is not installed")
class WatcherTest(unittest.TestCase):
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
        self.env.update(HOME=self.home, PATH=bin_dir + os.pathsep + os.environ["PATH"],
                        GIT_CONFIG_NOSYSTEM="1", FAKE_AGENT_DIR=self.agent_dir)

        git(self.repo, self.env, "init", "-q", "-b", "main")
        self.write("app.py", "def greet(name):\n    return 'hi ' + name\n")
        git(self.repo, self.env, "add", ".")
        git(self.repo, self.env, "commit", "-q", "-m", "first")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.output = []
        self.watcher = None

    def tearDown(self):
        if self.watcher and self.watcher.poll() is None:
            self.stop_watcher()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def write(self, path, text):
        with open(os.path.join(self.repo, path), "w") as f:
            f.write(text)

    def watcher_command(self):
        return [sys.executable, WATCHER, "--ref", "HEAD", "--tool", "claude", "--cmd", FAKE_AGENT,
                "--cwd", self.repo, "--interval", "0.2"]

    def launch_watcher(self):
        self.watcher = subprocess.Popen(
            self.watcher_command(), cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(self.watcher.stdout.close)
        threading.Thread(target=self._read_output, daemon=True).start()

    def start_watcher(self):
        self.launch_watcher()
        api_file = os.path.join(self.repo, ".git", "difftate", "api.json")
        wait_for("the review API", lambda: os.path.exists(api_file) or self.watcher.poll() is not None)
        self.assertIsNone(self.watcher.poll(), "watcher exited:\n" + self.terminal())
        with open(api_file) as f:
            self.port = json.load(f)["port"]
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

    def open_thread(self, body, line=2, **payload):
        return self.api("POST", "/api/threads", dict({
            "anchor": {"file": "app.py", "side": "new", "startLine": line, "endLine": line,
                       "code": "    return f'hello {name}'"}, "body": body}, **payload))

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
        """The agent replies to no thread (in every run, or only in <runs>)."""
        path = os.path.join(self.agent_dir, "silent")
        if silent:
            os.makedirs(self.agent_dir, exist_ok=True)
            with open(path, "w") as f:
                f.write(",".join(str(n) for n in runs))
        else:
            os.remove(path)

    def agent_edits(self, files):
        """The agent writes <files> ({path: text}) in its run."""
        os.makedirs(self.agent_dir, exist_ok=True)
        with open(os.path.join(self.agent_dir, "edits"), "w") as f:
            json.dump(files, f)

    def prompts(self):
        """The prompt of every run so far."""
        try:
            with open(os.path.join(self.agent_dir, "prompts")) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def dispatches(self):
        return self.terminal().count("New/changed threads detected")

    # ── Tests ────────────────────────────────────────────────────────────────
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
        wait_for("the done note", lambda: self.note(tid, "progress", "Done"))
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

    def test_the_final_progress_note_lists_the_files_changed_during_the_run(self):
        # app.py already has the reviewer's uncommitted edit; util.py is new
        self.agent_edits({"app.py": "def greet(name: str):\n    return f'hello {name}'\n",
                          "util.py": "def shout(s):\n    return s.upper()\n"})
        self.write("notes.txt", "the reviewer's own file, untouched by the run\n")
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Add a type hint?")["id"]

        wait_for("the replied state", lambda: self.state(tid) == "replied")
        final = wait_for("the changed files", lambda: self.note(tid, "progress", "Changed during this run"))
        self.assertTrue(final.startswith("✅ **Done** in "), final)
        self.assertTrue(final.endswith("**Changed during this run:**\n- `app.py`\n- `util.py`"), final)
        self.assertRegex(self.terminal(), r"\[\d\d:\d\d:\d\d\] Changed during this run:\n  - app.py\n  - util.py\n")

    def test_a_run_that_changes_nothing_lists_no_changed_files(self):
        self.release_agent()
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]

        wait_for("the replied state", lambda: self.state(tid) == "replied")
        time.sleep(0.5)  # the watcher has finished with the run
        self.assertRegex(self.note(tid, "progress"), r"^✅ \*\*Done\*\* in \d+s$")
        self.assertNotIn("Changed during this run", self.terminal())

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
        wait_for("the done note", lambda: self.note(second, "progress", "Done"))
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

    def test_a_reviewing_agents_comment_is_dispatched_like_the_users(self):
        self.release_agent()
        self.start_watcher()

        # A separate reviewing agent writes its findings to diffity as an agent
        subprocess.run(["diffity", "agent", "comment", "--file", "app.py", "--line", "2",
                        "--body", "Missing a type hint."], cwd=self.repo, env=self.env, check=True,
                       capture_output=True)
        [thread] = self.api("GET", "/api/threads")
        self.assertEqual(thread["comments"][0]["author"], "reviewer")

        wait_for("the replied state", lambda: self.state(thread["id"]) == "replied")
        self.assertIn("reviewer (new): Missing a type hint.", self.prompts()[0])

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

    def test_ctrl_c_while_diffity_starts_stops_diffity(self):
        # A diffity that never says where it listens, so the watcher is still waiting for it
        bin_dir = os.path.join(self.tmp, "slow-bin")
        os.makedirs(bin_dir)
        pid_file = os.path.join(self.tmp, "diffity.pid")
        with open(os.path.join(bin_dir, "diffity"), "w") as f:
            f.write(f'#!/bin/sh\n[ "$1" = list ] && {{ echo "[]"; exit 0; }}\necho $$ > {pid_file}\nexec sleep 60\n')
        os.chmod(os.path.join(bin_dir, "diffity"), 0o755)
        self.env["PATH"] = bin_dir + os.pathsep + self.env["PATH"]

        self.launch_watcher()
        wait_for("diffity to start", lambda: os.path.exists(pid_file) and open(pid_file).read().strip())
        with open(pid_file) as f:
            diffity_pid = int(f.read())
        self.stop_watcher()

        wait_for("diffity to stop", lambda: not alive(diffity_pid), timeout=10)

    def test_a_second_watcher_on_the_same_repository_is_refused(self):
        self.start_watcher()
        first = (self.watcher, self.port, self.token)

        second = subprocess.run(self.watcher_command(), cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30)

        self.assertEqual(second.returncode, 1, second.stdout)
        self.assertIn("already running for this repository", second.stdout)
        self.assertEqual((self.watcher, self.port, self.token), first)
        with open(os.path.join(self.repo, ".git", "difftate", "token")) as f:
            self.assertEqual(f.read().strip(), self.token, "the first watcher's token is kept")
        self.assertEqual(self.api("GET", "/api/threads"), [])

    def refused(self, method, path, payload):
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.api(method, path, payload)
        refused.exception.close()
        return refused.exception.code

    def test_only_a_reviewer_opens_a_thread_or_changes_its_status(self):
        self.silence_agent()  # keep the agent out of the thread
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
        self.assertIn("Killing diffity (pid ", out)
        self.assertTrue(out.rstrip().endswith("Done."), out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "difftate", "api.json")))


if __name__ == "__main__":
    unittest.main()
