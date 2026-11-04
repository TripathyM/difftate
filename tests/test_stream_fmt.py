"""Seam: the formatter (lib/stream_fmt.py) against the review API.

The test runs the real formatter as a process, feeds it a coding agent's event
stream, and points it at a fake review API that records the progress note's
edits in the order it applies them.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAM_FMT = os.path.join(ROOT, "lib", "stream_fmt.py")
NOTE_ID = "note-1"
HOLD_S = 2  # under the formatter's 3s request timeout, so a held edit still counts


class FakeReviewApi(ThreadingHTTPServer):
    """Applies note edits in parallel, like the real review API.

    Once `hold` is set, the next in-progress edit is held until a finished edit
    arrives (or HOLD_S passes): a slow request that would land late.
    """

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.lock = threading.Lock()
        self.applied = []  # note bodies, in the order they were applied
        self.hold = threading.Event()
        self.holding = threading.Event()
        self.finished = threading.Event()
        self.released = threading.Event()

    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    def do_PATCH(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["body"]
        api = self.server
        held = api.hold.is_set() and not api.holding.is_set() and body.startswith("⏳")
        if held:
            api.holding.set()
            api.finished.wait(HOLD_S)
        with api.lock:
            api.applied.append(body)
        if body.startswith(("✅", "❌")):
            api.finished.set()
        if held:
            api.released.set()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


class ProgressNoteTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeReviewApi()
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        tmp = tempfile.mkdtemp()
        token_file = os.path.join(tmp, "token")
        with open(token_file, "w") as f:
            f.write("secret")
        env = dict(os.environ, DT_NOTES=json.dumps({"thread-1": NOTE_ID}),
                   DT_API=self.api.url(), DT_TOKEN_FILE=token_file)
        env.pop("DT_RUN_END", None)
        self.proc = subprocess.Popen([sys.executable, "-u", STREAM_FMT, "claude"], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
        self.addCleanup(self.proc.kill)

    def send(self, event):
        self.proc.stdin.write(json.dumps(event) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, what, check, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check():
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {what}")

    def test_a_late_in_progress_edit_does_not_overwrite_the_finished_line(self):
        self.wait_for("the first edit", lambda: self.api.applied)
        self.send({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})
        self.wait_for("the step's edit", lambda: len(self.api.applied) >= 2)
        # The next idle refresh is slow to reach the API; the run finishes meanwhile
        self.api.hold.set()
        self.wait_for("a slow in-progress edit", self.api.holding.is_set)
        self.send({"type": "result", "total_cost_usd": 0.01})
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.wait_for("the slow edit to land", self.api.released.is_set)

        self.assertTrue(self.api.applied[-1].startswith("✅ **Done**"), self.api.applied[-1])


if __name__ == "__main__":
    unittest.main()
