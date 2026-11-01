"""The diffity store: an anti-corruption layer over diffity 0.9.5's local API.

Everything diffity-specific stays here: its command line, its HTTP routes, its
session ids, its viewer's address, and the text prefixes that mark notes.
diffity is transitional (ADR 0001): nothing outside this module may depend on it.

Threads still pass through in diffity's JSON; difftate's own thread format
replaces it in #16.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import procs
from .store import NOTE_KINDS, THREAD_STATUSES, StoreError, need_text

START_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 5
NOTE_MARKERS = {"queued": "[dt-queued]", "progress": "[dt-status]"}
assert set(NOTE_MARKERS) == set(NOTE_KINDS)
REVIEWER = {"name": "You", "type": "user"}
# The author the bash watcher writes its notes as
DIFFTATE = {"name": "Agent", "type": "agent"}
ID = re.compile(r"^[A-Za-z0-9-]+$")


class DiffityStartError(Exception):
    pass


# ── The diffity process ──────────────────────────────────────────────────────
def _running_port(cwd):
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


def launch(ref, cwd):
    """Reuse the diffity running for this repository, or start one."""
    if not shutil.which("diffity"):
        raise DiffityStartError("Error: diffity not found. Install with: npm install -g diffity")
    port = _running_port(cwd)
    if port:
        print(f"Diffity already running for this repo on port {port}")
        process = DiffityProcess(port)
    else:
        print(f"Starting diffity --base {ref} ...")
        process = DiffityProcess.start(ref, cwd)
    print(f"Diffity running on port {process.port}")
    return process


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
        except BaseException:
            # Ctrl+C while diffity starts: it has its own session, so stop it here
            procs.stop_tree(proc)
            raise
        if port is None:
            procs.stop_tree(proc)
            raise DiffityStartError(f"Error: diffity failed to start. Check if the ref '{ref}' is valid.")
        return cls(port, proc)

    def store(self):
        return DiffityStore(self.port)

    def viewer_url(self, ref):
        return f"http://localhost:{self.port}/diff?ref={ref}"

    def _alive(self):
        if self.owned:
            return self.proc.poll() is None
        try:
            self.store().review()
            return True
        except StoreError:
            return False

    def problem(self):
        """None while diffity runs, else why the watcher must exit."""
        if self._alive():
            return None
        return "Diffity process died. Exiting." if self.owned else "Diffity is no longer reachable. Exiting."

    def stop(self, say=True):
        if self.owned and self.proc.poll() is None:
            if say:
                print(f"Killing diffity (pid {self.proc.pid})...")
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
        if status is not None and status not in THREAD_STATUSES:
            raise StoreError(400, f"bad status: {status!r}")
        query = {"session": self._session_id()}
        if status:
            query["status"] = status
        return self._call("GET", "/api/threads?" + urllib.parse.urlencode(query))

    def open_thread(self, fields):
        """A reviewer opens a thread: filePath, side, startLine, endLine, body, anchorContent (optional)."""
        payload = {k: fields.get(k) for k in ("filePath", "side", "startLine", "endLine", "body")}
        if not isinstance(payload["filePath"], str) or payload["side"] not in ("old", "new") \
                or not all(isinstance(payload[k], int) for k in ("startLine", "endLine")):
            raise StoreError(400, "need filePath, side (old|new), startLine, endLine and body")
        need_text(payload["body"])
        if isinstance(fields.get("anchorContent"), str):
            payload["anchorContent"] = fields["anchorContent"]
        payload.update(sessionId=self._session_id(), author=REVIEWER)
        return self._call("POST", "/api/threads", payload)

    def add_comment(self, thread_id, body):
        """A reviewer's comment on a thread."""
        return self._call("POST", f"/api/threads/{_check_id(thread_id)}/reply",
                          {"body": need_text(body), "author": REVIEWER})

    def add_note(self, thread_id, kind, body):
        return self._call("POST", f"/api/threads/{_check_id(thread_id)}/reply",
                          {"body": self._note_body(kind, body), "author": DIFFTATE})

    def edit_note(self, note_id, kind, body):
        """Edit a note. Comments and replies can't be edited this way."""
        _check_id(note_id)
        new_body = self._note_body(kind, body)
        found = next((c for t in self.threads() for c in t.get("comments") or [] if c.get("id") == note_id), None)
        if found is None:
            raise StoreError(404, f"no note {note_id}")
        if not any((found.get("body") or "").startswith(m) for m in NOTE_MARKERS.values()):
            raise StoreError(403, f"{note_id} is not a note")
        return self._call("PATCH", f"/api/comments/{note_id}", {"body": new_body})

    def set_status(self, thread_id, status):
        if status not in THREAD_STATUSES:
            raise StoreError(400, f"status must be one of {', '.join(THREAD_STATUSES)}")
        return self._call("PATCH", f"/api/threads/{_check_id(thread_id)}/status", {"status": status})

    @staticmethod
    def _note_body(kind, body):
        if kind not in NOTE_MARKERS:
            raise StoreError(400, f"kind must be one of {', '.join(NOTE_KINDS)}")
        return f"{NOTE_MARKERS[kind]} {need_text(body)}"
