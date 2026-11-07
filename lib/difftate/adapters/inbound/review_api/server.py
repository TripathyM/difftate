"""The review API: difftate's published language, served on localhost. It is
an inbound adapter: each route calls one of the core's use cases, and the
core's errors become HTTP statuses.

Viewers and scripts reach the review through it; Dispatch, inside the watcher,
reaches it through the core (ADR 0003). Every
request needs the token from the repository's difftate folder
(`<git dir>/difftate/token`, readable only by the user); a request without it
gets 401.

  GET   /api/review                     start or reuse the review of the checked-out
                                        branch: {"id", "branch", "base", "waitingForRun",
                                        "checkedOut"}. The watcher follows the branch, so
                                        they change after a checkout; until a run in
                                        progress ends, "waitingForRun" is true and
                                        "checkedOut" names the branch it moves to
  GET   /api/view                       the view viewers show: {"view"}
  PUT   /api/view                       show another view: {"view", "open"?: browser|herdr|both
                                        (also open the viewer on it)}
  GET   /api/changeset[?view=<view>]    the review's changeset in the view (default: the
                                        one viewers show), from git: {"view", "base",
                                        "commit" (where the branch left the base), "diff",
                                        "waitingForRun", "checkedOut" (as /api/review)}
  GET   /api/threads[?status=open][&view=<view>]
                                        list threads; with a view, each anchor's lines
                                        are where its code is in that view
  POST  /api/threads                    open a thread: {"anchor", "body", "author"?}
  POST  /api/threads/<id>/comments      add a comment: {"kind"?, "body"}
  PATCH /api/notes/<id>                 edit a note: {"kind", "body"}
  PATCH /api/threads/<id>/status        set thread status: {"status", "author"?}
  GET   /api/viewed                     the files the reviewer marked viewed: {"files"}
  PUT   /api/viewed                     mark a file viewed, or not: {"file", "viewed"?: true|false
                                        (default true)}: {"files"}. 404 for a file
                                        that isn't in the changeset

A thread (difftate's thread format):
  {"id",
   "anchor": {"file", "side": "old"|"new", "startLine", "endLine",
              "code" (the code when written), "commit" (the commit when written),
              "snapshot" (local store: the whole file with that code on those lines, a
              blob in git's object database), "view" (local store: the view it was
              written in; it moves with its code there)}
             or null for a general thread,
   "outdated": true when the anchored code changed after the thread was written.
               Until then the thread moves with its code (its lines change when
               only line numbers move); after, it keeps the lines and code it had,
   "status": "open"|"resolved"|"dismissed",
   "state": "waiting"|"queued"|"working"|"replied"|"failed" (null unless open),
   "comments": [{"id", "author": "reviewer"|"agent"|"difftate",
                 "kind": "comment"|"reply"|"queued"|"progress", "body", "time"}]}

A view ("" for all changes, a commit such as HEAD~2 for the commits after it, HEAD
for the uncommitted changes, staged or unstaged) shows part of the review: every
thread belongs to the review, whatever view it was written in. POST /api/threads
takes the "view" it was written in (default all changes): its lines are that
view's. A thread listed with a view has "inView": false when its code isn't in
that view (its lines are then those of the view it was written in, its anchor's
"view"). A view that isn't one gets 400.

A comment's kind says who wrote it: a comment is the reviewer's (the default), a
reply the coding agent's, and a queued or progress note difftate's. "author" says who
opens a thread or sets its status, and must be "reviewer" (the default): anyone
else gets 403. Only notes can be edited (403 otherwise). Errors are
{"error": <message>} with status 400, 403, 404, 409 or 502. While another branch is
checked out and a run keeps the watcher on this review, opening a thread or
marking a file viewed gets 409, and every thread with an anchor is listed with
"inView": false and its own lines (the code on disk is the other branch's): the
watcher moves to that branch's review once the run ends.

A viewed file belongs to the review, like a thread: it stays viewed in every
view, after a reload and after a commit, until its diff in all changes changes
(any edit to the file, even one that keeps its line counts or is inside a new
untracked file). Then it is no longer listed.

`<git dir>/difftate/api.json` says where the API runs: {"port", "pid", "root"}.

The same server serves difftate's own browser viewer (web/, beside this file), a client of
this API like any other, which never sees the token (a coding agent can read the
browser's history). The watcher opens it with a single-use launch code:
GET /?launch=<code> trades the code for an HttpOnly, SameSite=Strict cookie and
redirects to /, after which the code is refused. The page (/) and its scripts
(/app.js, /diff.js) need that cookie; API requests take it instead of the token only
with the header "X-Difftate: page" (which another site's page can't send without
asking) and, when the browser says, the API's own Origin. Anything else gets 401.
"""
import hmac
import http.cookies
import json
import os
import re
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ....core.review.model import AUTHOR_OF, DIFFTATE, Conflict, CouldNotRead, NotAllowed, NotFound
from ....viewer import OPEN_IN
from .json_format import (NOTE_KINDS, BadRequest, anchor_from_json, changeset_json, comment_json, fields, need,
                          need_bool, need_kind, need_status, need_text, thread_json)

MAX_BODY = 1 << 20
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
# The browser viewer's files: (path on disk, Content-Type). Its diff parser is the Review tab's.
PAGE_FILES = {
    "/": (os.path.join(_HERE, "web", "index.html"), "text/html; charset=utf-8"),
    "/app.js": (os.path.join(_HERE, "web", "app.js"), "text/javascript; charset=utf-8"),
    "/diff.js": (os.path.join(_REPO, "herdr", "mods", "difftate", "diff.js"), "text/javascript; charset=utf-8"),
}
# The core's errors, as HTTP statuses. A bad view is the request's fault (400),
# though the code reader says it isn't found: see a_view below.
STATUS_OF = {NotAllowed: 403, NotFound: 404, Conflict: 409, CouldNotRead: 502}
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
                               "frame-ancestors 'none'",
}


def token_file(folder):
    """Where the review API keeps its token, in the review's <folder>."""
    return os.path.join(folder, "token")


class ApiAddress(namedtuple("ApiAddress", "url token_file")):
    """Where a client finds the review API, and the file with its token."""



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


def ask_running_watcher(folder, method, path, payload=None):
    """Call the review API of the watcher serving this repository, as a viewer
    would: (status, the JSON answer)."""
    with open(os.path.join(folder, "api.json")) as f:
        port = int(json.load(f)["port"])
    with open(os.path.join(folder, "token")) as f:
        token = f.read().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        with e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None


def _write_private(path, text):
    """Write <path> readable only by the user, replacing it atomically."""
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class ShownView:
    """The view viewers show. <check>(view) gives it as a view, or raises the
    core's NotFound (the code reader has no such view); <on_switch>(view,
    open_in) runs when a request switches the view."""

    def __init__(self, view, check, on_switch=None):
        self.view = view
        self.check = check
        self.on_switch = on_switch or (lambda view, open_in: None)
        self._lock = threading.Lock()

    def current(self):
        with self._lock:
            return self.view

    def switch(self, view, open_in=None):
        """Show <view>, a view already checked."""
        with self._lock:
            self.view = view
        self.on_switch(view, open_in)
        return {"view": view}


class PageLogin:
    """How difftate's browser page gets in without the token: single-use launch
    codes, each traded once for the page's cookie."""

    def __init__(self):
        self.secret = secrets.token_urlsafe(32)  # the cookie's value: not the token
        self._codes = set()
        self._lock = threading.Lock()

    def new_code(self):
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._codes.add(code)
        return code

    def trade(self, code):
        """True once for each code made here; the code is then spent."""
        with self._lock:
            for known in self._codes:
                if hmac.compare_digest(known.encode(), code.encode()):
                    self._codes.discard(known)
                    return True
        return False

    def holds_cookie(self, name, header):
        """Whether a request's Cookie header carries the page's cookie."""
        try:
            jar = http.cookies.SimpleCookie(header or "")
        except http.cookies.CookieError:
            return False
        given = jar[name].value if name in jar else ""
        return hmac.compare_digest(given.encode(), self.secret.encode())


class ReviewApi:
    """The review API on <review>: the use cases of one review, with its ports
    bound (watcher.bind_review): about ({"id", "branch", "base"}),
    list_threads, open_thread, add_comment, edit_note, set_status,
    mark_viewed, list_viewed, changeset and checked_out."""

    def __init__(self, review, folder, root, shown):
        self.review = review
        self.shown = shown
        self.folder = folder
        self.root = root
        self.token = secrets.token_urlsafe(32)
        self.login = PageLogin()
        self.server = None
        self.token_file = token_file(folder)
        self.api_file = os.path.join(folder, "api.json")

    def switch_review(self, review):
        """Serve <review> from now on: the watcher follows the checked-out branch."""
        self.review = review

    def address(self):
        return ApiAddress(f"http://127.0.0.1:{self.server.server_address[1]}", self.token_file)

    def page_url(self):
        """A link to the browser viewer, with a new single-use launch code."""
        return f"{self.address().url}/?launch={self.login.new_code()}"

    def start(self):
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(lambda: self.review, self.token, self.shown, self.login))
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


def _handler(current, token, shown, login):
    """<current>() is the review the API serves now: the watcher follows the
    checked-out branch."""
    expected = f"Bearer {token}".encode()

    def a_view(given):
        """<given> as a view. The code reader raises NotFound for one that isn't
        a view, and today's published language answers 400 for it: a bad view
        is the request's fault, not a missing thread."""
        try:
            return shown.check(given)
        except NotFound as e:
            raise BadRequest(str(e)) from e

    def waiting_for_run(review):
        """While another branch is checked out, the watcher moves to its review
        once the run in progress ends."""
        checkout = review.checked_out()
        return {"waitingForRun": not checkout.on_review_branch, "checkedOut": checkout.branch}

    def open_in(payload):
        where = fields(payload).get("open")
        if where is not None and where not in OPEN_IN:
            raise BadRequest("open must be browser, herdr or both")
        return where

    def get_review(q, p):
        review = current()
        about = {"id": review.about["id"], "branch": review.about["branch"], "base": review.about["base"]}
        return dict(about, **waiting_for_run(review))

    def switch_view(q, p):
        where = open_in(p)
        return shown.switch(a_view(fields(p).get("view", "")), where)

    def get_changeset(q, p):
        review = current()
        view = a_view(q["view"][0]) if q.get("view") else shown.current()
        try:
            changeset = review.changeset(view)
        except NotFound as e:  # the view shown is no view now
            raise BadRequest(str(e)) from e
        return dict(changeset_json(changeset), **waiting_for_run(review))

    def get_threads(q, p):
        view = a_view(q["view"][0]) if "view" in q else None
        status = (q.get("status") or [None])[0]
        if status is not None:
            need_status(status)
        return [thread_json(t) for t in current().list_threads(status, view)]

    def post_thread(q, p):
        given, body = fields(p).get("anchor"), need(p, "body")
        author = fields(p).get("author", "reviewer")
        anchor = anchor_from_json(given, a_view(fields(p).get("view", "")))
        return thread_json(current().open_thread(author, need_text(body), anchor))

    def post_comment(q, p, thread_id):
        kind, body = fields(p).get("kind", "comment"), need(p, "body")
        need_kind(kind)
        # A comment's kind says who wrote it
        return comment_json(current().add_comment(AUTHOR_OF[kind], thread_id, kind, need_text(body)))

    def patch_note(q, p, note_id):
        kind, body = need(p, "kind"), need(p, "body")
        need_kind(kind, NOTE_KINDS)
        return comment_json(current().edit_note(DIFFTATE, note_id, kind, need_text(body)))

    def patch_status(q, p, thread_id):
        status, author = need(p, "status"), fields(p).get("author", "reviewer")
        thread = current().set_status(author, thread_id, need_status(status))
        return {"id": thread.id, "status": thread.status}

    def put_viewed(q, p):
        file, viewed = need(p, "file"), fields(p).get("viewed", True)
        return {"files": current().mark_viewed(need_text(file, "file"), need_bool(viewed, "viewed"))}

    routes = [
        ("GET", r"/api/review", get_review),
        ("GET", r"/api/view", lambda q, p: {"view": shown.current()}),
        ("PUT", r"/api/view", switch_view),
        ("GET", r"/api/changeset", get_changeset),
        ("GET", r"/api/threads", get_threads),
        ("POST", r"/api/threads", post_thread),
        ("POST", r"/api/threads/([^/]+)/comments", post_comment),
        ("PATCH", r"/api/notes/([^/]+)", patch_note),
        ("PATCH", r"/api/threads/([^/]+)/status", patch_status),
        ("GET", r"/api/viewed", lambda q, p: {"files": current().list_viewed()}),
        ("PUT", r"/api/viewed", put_viewed),
    ]
    routes = [(m, re.compile(f"^{path}$"), fn) for m, path, fn in routes]

    class Handler(BaseHTTPRequestHandler):
        server_version = "difftate"

        def log_message(self, *args):
            pass

        def _send(self, status, payload):
            self._send_bytes(status, "application/json", json.dumps(payload).encode())

        def _send_bytes(self, status, content_type, data, headers=()):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def _cookie_name(self):
            # Cookies don't keep ports apart: one name per watcher's port
            return f"difftate-{self.server.server_address[1]}"

        def _page_cookie(self):
            return login.holds_cookie(self._cookie_name(), self.headers.get("Cookie"))

        def _from_page(self):
            """An API request from difftate's own page: its cookie, its header, and
            no other site's origin."""
            origin = self.headers.get("Origin")
            own = f"http://127.0.0.1:{self.server.server_address[1]}"
            return (self.headers.get("X-Difftate") == "page" and origin in (None, own)
                    and self._page_cookie())

        def _page(self, url):
            """The browser viewer's files, for the page's cookie; a launch code gets it."""
            def text(status, content_type, body, headers=()):
                self._send_bytes(status, content_type, body.encode(), [*PAGE_HEADERS.items(), *headers])

            refused = "difftate: open the link a running difftate prints (each link opens the page once).\n"
            code = urllib.parse.parse_qs(url.query).get("launch")
            if url.path == "/" and code and self.command == "GET":
                if not login.trade(code[0]):
                    return text(401, "text/plain; charset=utf-8", refused)
                cookie = f"{self._cookie_name()}={login.secret}; Path=/; HttpOnly; SameSite=Strict"
                return text(303, "text/plain; charset=utf-8", "", [("Location", "/"), ("Set-Cookie", cookie)])
            if not self._page_cookie():
                return text(401, "text/plain; charset=utf-8", refused)
            if url.path not in PAGE_FILES:
                return text(404, "text/plain; charset=utf-8", "not found\n")
            if self.command != "GET":
                return text(405, "text/plain; charset=utf-8", "method not allowed\n")
            path, content_type = PAGE_FILES[url.path]
            with open(path, encoding="utf-8") as f:
                text(200, content_type, f.read())

        def _handle(self):
            url = urllib.parse.urlsplit(self.path)
            if not url.path.startswith("/api/"):
                return self._page(url)
            given = (self.headers.get("Authorization") or "").encode()
            if not hmac.compare_digest(given, expected) and not self._from_page():
                return self._send(401, {"error": "missing or wrong token"})
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
                result = fn(urllib.parse.parse_qs(url.query, keep_blank_values=True), payload, *match.groups())
            except BadRequest as e:
                return self._send(400, {"error": str(e)})
            except tuple(STATUS_OF) as e:
                status = next(STATUS_OF[kind] for kind in type(e).__mro__ if kind in STATUS_OF)
                return self._send(status, {"error": str(e)})
            self._send(200, result)

        do_GET = do_POST = do_PATCH = do_PUT = _handle

    return Handler
