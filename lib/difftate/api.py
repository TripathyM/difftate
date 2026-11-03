"""The review API: difftate's published language, served on localhost.

Viewers and the progress notes reach the review only through it. Every request
needs the token from the repository's difftate folder (`<git dir>/difftate/token`,
readable only by the user); a request without it gets 401.

  GET   /api/review                     start or reuse the review: {"id"} (the local
                                        store adds "branch" and "base")
  GET   /api/changeset                  the review's changeset, from git: {"base",
                                        "commit" (where the branch left the base), "diff"}
  GET   /api/threads[?status=open]      list threads
  POST  /api/threads                    open a thread: {"anchor", "body", "author"?}
  POST  /api/threads/<id>/comments      add a comment: {"kind"?, "body"}
  PATCH /api/notes/<id>                 edit a note: {"kind", "body"}
  PATCH /api/threads/<id>/status        set thread status: {"status", "author"?}

A thread (difftate's thread format):
  {"id",
   "anchor": {"file", "side": "old"|"new", "startLine", "endLine",
              "code" (the code when written), "commit" (the commit when written)}
             or null for a general thread,
   "outdated": true when the anchored code changed after the thread was written,
   "status": "open"|"resolved"|"dismissed",
   "state": "waiting"|"queued"|"working"|"replied"|"failed" (null unless open),
   "comments": [{"id", "author": "reviewer"|"agent"|"difftate",
                 "kind": "comment"|"reply"|"queued"|"progress", "body", "time"}]}

A comment's kind says who wrote it: a comment is the reviewer's (the default), a
reply the coding agent's, and a queued or progress note difftate's. "author" says who
opens a thread or sets its status, and must be "reviewer" (the default): anyone
else gets 403. Only notes can be edited (403 otherwise). Errors are
{"error": <message>} with status 400, 403, 404 or 502.

`<git dir>/difftate/api.json` says where the API runs: {"port", "pid", "root"}.
"""
import hmac
import json
import os
import re
import secrets
import socket
import threading
import urllib.parse
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .changes import ChangesError
from .store import StoreError

MAX_BODY = 1 << 20


class ApiAddress(namedtuple("ApiAddress", "url token_file")):
    """Where a client finds the review API, and the file with its token."""

    def env(self):
        return {"DT_API": self.url, "DT_TOKEN_FILE": self.token_file}


def running_watcher(folder):
    """The pid of another live watcher serving this repository's review API, or None."""
    try:
        with open(os.path.join(folder, "api.json")) as f:
            info = json.load(f)
        pid, port = int(info["pid"]), int(info["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if pid == os.getpid():
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        pass
    # The pid may have been reused: only a watcher still answers on its port
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return None
    return pid


def _write_private(path, text):
    """Write <path> readable only by the user, replacing it atomically."""
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class ReviewApi:
    def __init__(self, review, folder, root, changeset):
        self.review = review
        self.changeset = changeset  # () -> the review's changeset
        self.folder = folder
        self.root = root
        self.token = secrets.token_urlsafe(32)
        self.server = None
        self.token_file = os.path.join(folder, "token")
        self.api_file = os.path.join(folder, "api.json")

    def address(self):
        return ApiAddress(f"http://127.0.0.1:{self.server.server_address[1]}", self.token_file)

    def start(self):
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.review, self.token, self.changeset))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        _write_private(self.token_file, self.token + "\n")
        _write_private(self.api_file, json.dumps(
            {"port": self.server.server_address[1], "pid": os.getpid(), "root": self.root}) + "\n")

    def stop(self):
        if not self.server:
            return
        self.server.shutdown()
        self.server.server_close()
        self.server = None
        # Leave the files alone if another watcher has taken them over since
        try:
            with open(self.api_file) as f:
                ours = json.load(f).get("pid") == os.getpid()
        except (OSError, ValueError):
            ours = False
        if ours:
            for path in (self.api_file, self.token_file):
                try:
                    os.remove(path)
                except OSError:
                    pass


def _handler(review, token, changeset):
    expected = f"Bearer {token}".encode()

    def need(payload, key):
        if not isinstance(payload, dict) or key not in payload:
            raise StoreError(400, f"missing {key}")
        return payload[key]

    def fields(payload):
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise StoreError(400, "need a JSON object")
        return payload

    routes = [
        ("GET", r"/api/review", lambda q, p: review.review()),
        ("GET", r"/api/changeset", lambda q, p: changeset()),
        ("GET", r"/api/threads", lambda q, p: review.threads((q.get("status") or [None])[0])),
        ("POST", r"/api/threads", lambda q, p: review.open_thread(
            fields(p).get("anchor"), need(p, "body"), fields(p).get("author", "reviewer"))),
        ("POST", r"/api/threads/([^/]+)/comments",
         lambda q, p, tid: review.add_comment(tid, fields(p).get("kind", "comment"), need(p, "body"))),
        ("PATCH", r"/api/notes/([^/]+)", lambda q, p, nid: review.edit_note(nid, need(p, "kind"), need(p, "body"))),
        ("PATCH", r"/api/threads/([^/]+)/status",
         lambda q, p, tid: review.set_status(tid, need(p, "status"), fields(p).get("author", "reviewer"))),
    ]
    routes = [(m, re.compile(f"^{path}$"), fn) for m, path, fn in routes]

    class Handler(BaseHTTPRequestHandler):
        server_version = "difftate"

        def log_message(self, *args):
            pass

        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self):
            given = (self.headers.get("Authorization") or "").encode()
            if not hmac.compare_digest(given, expected):
                return self._send(401, {"error": "missing or wrong token"})
            url = urllib.parse.urlsplit(self.path)
            matches = [(m, rx.match(url.path), fn) for m, rx, fn in routes]
            matches = [(m, match, fn) for m, match, fn in matches if match]
            if not matches:
                return self._send(404, {"error": "not found"})
            for method, match, fn in matches:
                if method == self.command:
                    break
            else:
                return self._send(405, {"error": "method not allowed"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad Content-Length"})
            if length > MAX_BODY:
                return self._send(413, {"error": "request too large"})
            try:
                payload = json.loads(self.rfile.read(length) or b"null") if length else None
            except ValueError:
                return self._send(400, {"error": "bad JSON"})
            try:
                result = fn(urllib.parse.parse_qs(url.query), payload, *match.groups())
            except StoreError as e:
                return self._send(e.status, {"error": str(e)})
            except ChangesError as e:
                return self._send(502, {"error": str(e)})
            self._send(200, result)

        do_GET = do_POST = do_PATCH = _handle

    return Handler
