"""The diffity store: an anti-corruption layer over diffity 0.9.5's local API.

Everything diffity-specific stays here: its command line, its HTTP routes, its
session ids and the text prefixes that mark notes. diffity is transitional
(ADR 0001): nothing outside this module may depend on it.

Threads still pass through in diffity's JSON; difftate's own thread format
replaces it in #16.
"""
import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import procs

START_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 5
NOTE_MARKERS = {"queued": "[dt-queued]", "progress": "[dt-status]"}
REVIEWER = {"name": "You", "type": "user"}
# The author the bash watcher writes its notes as
DIFFTATE = {"name": "Agent", "type": "agent"}
STATUSES = ("open", "resolved", "dismissed")
ID = re.compile(r"^[A-Za-z0-9-]+$")


class StoreError(Exception):
    """A request the store refused (status 4xx) or couldn't serve (502)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class DiffityStartError(Exception):
    pass


# ── The diffity process ──────────────────────────────────────────────────────
def running_port(cwd):
    """Port of the diffity already running for <cwd>'s repository, or None."""
    try:
        out = subprocess.run(["diffity", "list", "--json"], cwd=cwd, capture_output=True, text=True).stdout
        instances = json.loads(out)
    except (OSError, ValueError):
        return None
    root = os.path.realpath(cwd)
    for inst in instances:
        if os.path.realpath(inst.get("repoRoot", "")) == root:
            return inst.get("port")
    return None


class DiffityProcess:
    """The diffity server for one repository: started here, or one already running."""

    def __init__(self, port, proc=None):
        self.port = port
        self.proc = proc

    @property
    def owned(self):
        return self.proc is not None

    @classmethod
    def start(cls, ref, cwd):
        proc = subprocess.Popen(["diffity", "--base", ref, "--no-open"], cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                start_new_session=True)
        found = queue.Queue()

        def read():
            # Wait for diffity to print its URL, then keep draining so it never blocks on a full pipe
            port = None
            for line in proc.stdout:
                if port is None:
                    m = re.search(r"localhost:(\d+)", line)
                    if m:
                        port = int(m.group(1))
                        found.put(port)
            found.put(None)

        threading.Thread(target=read, daemon=True).start()
        try:
            port = found.get(timeout=START_TIMEOUT_S)
        except queue.Empty:
            port = None
        if port is None:
            procs.stop_tree(proc)
            raise DiffityStartError(f"Error: diffity failed to start. Check if the ref '{ref}' is valid.")
        return cls(port, proc)

    def alive(self):
        if self.owned:
            return self.proc.poll() is None
        try:
            DiffityStore(self.port).review()
            return True
        except StoreError:
            return False

    def stop(self):
        if self.owned and self.proc.poll() is None:
            procs.stop_tree(self.proc)


# ── The store ────────────────────────────────────────────────────────────────
def _check_id(value):
    if not isinstance(value, str) or not ID.match(value):
        raise StoreError(400, f"bad id: {value!r}")
    return value


class DiffityStore:
    """The review's threads, kept by a running diffity."""

    def __init__(self, port):
        self.url = f"http://localhost:{port}"

    def _call(self, method, path, payload=None):
        req = urllib.request.Request(
            self.url + path, method=method, headers={"Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode())
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise StoreError(e.code if 400 <= e.code < 500 else 502, f"diffity: {e.code} {e.read().decode(errors='replace')}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise StoreError(502, f"diffity is not reachable: {e}")

    def _session_id(self):
        # The current session is the one `diffity agent` uses (and the browser last loaded).
        # /api/info starts one when there is none yet.
        session = self._call("GET", "/api/sessions/current")
        if session and session.get("id"):
            return session["id"]
        info = self._call("GET", "/api/info") or {}
        if not info.get("sessionId"):
            raise StoreError(502, "diffity has no review session")
        return info["sessionId"]

    def review(self):
        """Start or reuse the review."""
        return {"id": self._session_id()}

    def threads(self, status=None):
        if status is not None and status not in STATUSES:
            raise StoreError(400, f"bad status: {status!r}")
        query = {"session": self._session_id()}
        if status:
            query["status"] = status
        return self._call("GET", "/api/threads?" + urllib.parse.urlencode(query))

    def open_thread(self, fields):
        """A reviewer opens a thread: filePath, side, startLine, endLine, body, anchorContent (optional)."""
        payload = {k: fields.get(k) for k in ("filePath", "side", "startLine", "endLine", "body")}
        if not isinstance(payload["filePath"], str) or payload["side"] not in ("old", "new") \
                or not all(isinstance(payload[k], int) for k in ("startLine", "endLine")) \
                or not isinstance(payload["body"], str) or not payload["body"].strip():
            raise StoreError(400, "need filePath, side (old|new), startLine, endLine and body")
        if isinstance(fields.get("anchorContent"), str):
            payload["anchorContent"] = fields["anchorContent"]
        payload.update(sessionId=self._session_id(), author=REVIEWER)
        return self._call("POST", "/api/threads", payload)

    def add_comment(self, thread_id, body):
        """A reviewer's comment on a thread."""
        if not isinstance(body, str) or not body.strip():
            raise StoreError(400, "need body")
        return self._call("POST", f"/api/threads/{_check_id(thread_id)}/reply", {"body": body, "author": REVIEWER})

    def add_note(self, thread_id, kind, body):
        return self._call("POST", f"/api/threads/{_check_id(thread_id)}/reply",
                          {"body": self._note_body(kind, body), "author": DIFFTATE})

    def edit_note(self, note_id, kind, body):
        return self._call("PATCH", f"/api/comments/{_check_id(note_id)}", {"body": self._note_body(kind, body)})

    def set_status(self, thread_id, status):
        if status not in STATUSES:
            raise StoreError(400, f"status must be one of {', '.join(STATUSES)}")
        return self._call("PATCH", f"/api/threads/{_check_id(thread_id)}/status", {"status": status})

    @staticmethod
    def _note_body(kind, body):
        if kind not in NOTE_MARKERS:
            raise StoreError(400, f"kind must be one of {', '.join(NOTE_MARKERS)}")
        if not isinstance(body, str) or not body.strip():
            raise StoreError(400, "need body")
        return f"{NOTE_MARKERS[kind]} {body}"
