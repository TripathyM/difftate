"""The diffity store: an anti-corruption layer over diffity 0.9.5's local API.

Everything diffity-specific stays here: its command line, its HTTP routes, its
session ids, its viewer's address, and the text prefixes that mark notes.
diffity is transitional (ADR 0001): nothing outside this module may depend on it.

The store turns diffity's threads into difftate's thread format (store.py), and
difftate's comment kinds into the text prefixes diffity needs to tell them apart.
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
from .store import AUTHOR_OF, StoreError

START_TIMEOUT_S = 10
REQUEST_TIMEOUT_S = 5
# The text prefix that marks each kind of comment except the reviewer's
MARKERS = {"reply": "[dt-reply]", "queued": "[dt-queued]", "progress": "[dt-status]"}
assert set(MARKERS) | {"comment"} == set(AUTHOR_OF)
REVIEWER = {"name": "You", "type": "user"}
# The author difftate writes replies and notes as (the one `diffity agent reply` uses)
AGENT = {"name": "Agent", "type": "agent"}
GENERAL = "__general__"  # diffity's file path for a general thread
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


def _comment(c):
    """A diffity comment in difftate's format. Only a text prefix tells a reply or
    a note from a comment; anything without one is a reviewer's, whoever wrote it
    (a reviewing agent writes to diffity with diffity's agent author, but no prefix)."""
    body = c.get("body") or ""
    kind = next((k for k, m in MARKERS.items() if body == m or body.startswith(m + " ")), "comment")
    if kind != "comment":
        body = body[len(MARKERS[kind]):].lstrip(" ")
    return {"id": c.get("id"), "author": AUTHOR_OF[kind], "kind": kind, "body": body, "time": c.get("createdAt")}


def _thread(t, commit):
    general = t.get("filePath") == GENERAL
    anchor = None if general else {
        "file": t.get("filePath"), "side": t.get("side"), "startLine": t.get("startLine"),
        "endLine": t.get("endLine"), "code": t.get("anchorContent"), "commit": commit}
    # diffity doesn't know when a thread's code changed: its threads are never outdated
    return {"id": t.get("id"), "anchor": anchor, "outdated": False, "status": t.get("status"),
            "comments": [_comment(c) for c in t.get("comments") or []]}


class DiffityStore:
    """The review's threads, kept by a running diffity. A review is diffity's
    current session (one ref at one HEAD commit)."""

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

    def _session(self):
        # The current session is the one `diffity agent` uses (and the browser last loaded).
        # /api/info starts one when there is none yet.
        session = self._call("GET", "/api/sessions/current")
        if not (session and session.get("id")):
            self._call("GET", "/api/info")
            session = self._call("GET", "/api/sessions/current")
        if not (session and session.get("id")):
            raise StoreError(502, "diffity has no review session")
        return session

    def _raw_threads(self, session, status=None):
        query = {"session": session["id"]}
        if status:
            query["status"] = status
        return self._call("GET", "/api/threads?" + urllib.parse.urlencode(query)) or []

    def _find_thread(self, thread_id):
        _check_id(thread_id)
        session = self._session()
        for t in self._raw_threads(session):
            if t.get("id") == thread_id:
                return t, session
        raise StoreError(404, f"no thread {thread_id}")

    def review(self):
        return {"id": self._session()["id"]}

    def threads(self, status=None):
        session = self._session()
        return [_thread(t, session.get("headHash")) for t in self._raw_threads(session, status)]

    def open_thread(self, anchor, body):
        session = self._session()
        where = {"filePath": GENERAL, "side": "new", "startLine": 0, "endLine": 0} if anchor is None else {
            "filePath": anchor["file"], "side": anchor["side"], "startLine": anchor["startLine"],
            "endLine": anchor["endLine"]}
        if anchor is not None and anchor.get("code") is not None:
            where["anchorContent"] = anchor["code"]
        created = self._call("POST", "/api/threads", dict(where, sessionId=session["id"], body=body, author=REVIEWER))
        return _thread(created, session.get("headHash"))

    def add_comment(self, thread_id, kind, body):
        self._find_thread(thread_id)
        author = REVIEWER if kind == "comment" else AGENT
        text = body if kind == "comment" else f"{MARKERS[kind]} {body}"
        return _comment(self._call("POST", f"/api/threads/{thread_id}/reply", {"body": text, "author": author}))

    def edit_note(self, note_id, kind, body, final=False):
        """diffity keeps every edit: <final> changes nothing."""
        _check_id(note_id)
        session = self._session()
        found = next((c for t in self._raw_threads(session) for c in t.get("comments") or []
                      if c.get("id") == note_id), None)
        if found is None:
            raise StoreError(404, f"no note {note_id}")
        text = f"{MARKERS[kind]} {body}"
        self._call("PATCH", f"/api/comments/{note_id}", {"body": text})
        return _comment(dict(found, body=text))

    # diffity has no place for runs: the Review finds them from the progress notes
    def record_run(self, run):
        pass

    def record_run_end(self, run_id, outcome):
        pass

    def runs(self):
        return None

    def set_status(self, thread_id, status):
        self._find_thread(thread_id)
        self._call("PATCH", f"/api/threads/{thread_id}/status", {"status": status})
        return {"id": thread_id, "status": status}
