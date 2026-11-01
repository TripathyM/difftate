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

    def open_thread(self, body, line=2):
        return self.api("POST", "/api/threads", {
            "filePath": "app.py", "side": "new", "startLine": line, "endLine": line, "body": body,
            "anchorContent": "    return f'hello {name}'"})

    def thread(self, tid):
        return next(t for t in self.api("GET", "/api/threads") if t["id"] == tid)

    def bodies(self, tid):
        return [c["body"] for c in self.thread(tid)["comments"]]

    def release_agent(self):
        with open(os.path.join(self.agent_dir, "go"), "w"):
            pass

    # ── Tests ────────────────────────────────────────────────────────────────
    def test_comment_gets_working_note_then_reply(self):
        self.start_watcher()
        tid = self.open_thread("Why an f-string here?")["id"]

        working = wait_for("a working progress note", lambda: next(
            (b for b in self.bodies(tid) if b.startswith("[dt-status]") and "Working" in b), None))
        self.assertIn("`Read app.py`", working)

        self.release_agent()
        wait_for("the agent's reply", lambda: any(b.startswith("[dt-reply]") for b in self.bodies(tid)))
        final = wait_for("the done note", lambda: next(
            (b for b in self.bodies(tid) if b.startswith("[dt-status]") and "Done" in b), None))
        self.assertTrue(final.startswith("[dt-status] ✅ **Done** in "), final)
        self.assertEqual(len(self.bodies(tid)), 3, "comment, one progress note (edited in place), reply")

        out = self.terminal()
        self.assertRegex(out, r"\[\d\d:\d\d:\d\d\] New/changed threads detected — dispatching to claude")
        self.assertIn("🔧 Read  app.py", out)
        self.assertRegex(out, r"✅ done in \d+s, \$0\.0123")

    def test_thread_written_during_a_run_is_queued_then_answered_next(self):
        self.start_watcher()
        first = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: any("Working" in b for b in self.bodies(first)))

        second = self.open_thread("Rename greet to welcome?", line=1)["id"]
        queued = wait_for("a queued note", lambda: next(
            (b for b in self.bodies(second) if b.startswith("[dt-queued]")), None))
        self.assertEqual(queued, "[dt-queued] 🕒 **Queued** — agent is busy with another comment, "
                                 "will pick this up next.")
        self.assertIn(f"Queued thread {second[:8]} (agent busy)", self.terminal())

        self.release_agent()
        wait_for("a reply on the queued thread", lambda: any(b.startswith("[dt-reply]") for b in self.bodies(second)))
        wait_for("the done note", lambda: any("Done" in b for b in self.bodies(second)))
        bodies = self.bodies(second)
        self.assertEqual(len(bodies), 3, f"the queued note becomes the progress note: {bodies}")
        self.assertTrue(bodies[1].startswith("[dt-status] ✅ **Done**"), bodies)

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
