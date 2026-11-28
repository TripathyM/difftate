"""The review API: difftate's published language, served on localhost. It is
an inbound adapter: each route calls one of the core's use cases, and the
core's errors become HTTP statuses.

Viewers and scripts reach the review through it; Dispatch, inside the watcher,
reaches it through the core (ADR 0003). There is one watcher for the machine
(ADR 0008), on one port with one token. Every request needs the token from the
difftate folder of the home (`~/.difftate/token`, readable only by the user); a
request without it gets 401.

Every request but POST /api/stop names its folder, as a query parameter,
`?folder=<path>` (the checked-out folder it is about), and may name a base,
`&base=<branch>` (the folder's own base when none is given; the repository's
default branch for a folder the watcher serves for the first time). One without
a folder gets 400, and so does a path that is in no checked-out folder of a git
repository. The first request that names a checked-out folder adds it to what the
watcher serves. Naming another base switches the folder's review to it.

  GET   /api/review                     start or reuse the review of the folder's checked-out
                                        branch: {"id", "branch", "base", "waitingForRun",
                                        "checkedOut", "mode", "held" (as /api/mode),
                                        "folder" (the checked-out folder
                                        the watcher runs in), "warnings": [{"id", "time",
                                        "text"}] about the review (a store changed outside
                                        difftate, restored; review-path.md that can't be read as a review path)}. The watcher follows the branch, so
                                        they change after a checkout; until a run in
                                        progress ends, "waitingForRun" is true and
                                        "checkedOut" names the branch it moves to
  GET   /api/view                       the view viewers show: {"view"}
  PUT   /api/view                       show another view: {"view"}. The watcher never opens a
                                        viewer: `difftate` does
  GET   /api/changeset[?view=<view>]    the review's changeset in the view (default: the
                                        one viewers show), from git: {"view", "base",
                                        "commit" (where the branch left the base), "diff",
                                        "versions": {file: {"old", "new"}} (the version
                                        of each side the diff shows; null for none),
                                        "waitingForRun", "checkedOut" (as /api/review)}
  GET   /api/threads[?status=open][&view=<view>]
                                        list threads; with a view, each anchor's lines
                                        are where its code is in that view
  POST  /api/threads                    open a thread: {"anchor", "body", "author"?, "reviewer"?}
  POST  /api/threads/<id>/comments      add a comment: {"kind"?, "body", "reviewer"?}
  PATCH /api/notes/<id>                 edit a note: {"kind", "body"}
  PATCH /api/threads/<id>/status        set thread status: {"status", "author"?, "reviewer"?}:
                                        {"id", "status", "statusBy"}
  GET   /api/viewed                     the files the reviewer marked viewed: {"files"}
  PUT   /api/viewed                     mark a file viewed, or not: {"file", "viewed"?: true|false
                                        (default true)}: {"files"}. 404 for a file
                                        that isn't in the changeset
  GET   /api/review-path[?view=<view>]  the review path the coding agent wrote in the folder
                                        (review-path.md, read at each request): {"path": null}
                                        without one, and when the file is broken (that is a warning
                                        in /api/review), else {"path": {"stops": [{"number" ("1"),
                                        "file", "key" (★), "viewed", "in_changeset" (false: the file
                                        has no changes, the path is out of date: a warning in
                                        /api/review), "questions": [{"question",
                                        "answer"}], "ranges": [[first, last]] (none: the whole
                                        file), "specs": [{"file", "name"}], "see": [names of the
                                        path sections its answers point to], "side_files":
                                        [{"file", "viewed", "ranges", "text", "in_changeset"}],
                                        "children": [stops, numbered "1.1"]}] in reading order,
                                        "skipped": [{"file", "reason", "in_changeset"}], "not_on_the_path": [file]:
                                        the changed files it names nowhere, "sections": [{"name",
                                        "text"}]: the path sections}}. In a view (default: the one
                                        viewers show) the path is cut down to the view's files,
                                        numbers kept, and "skipped" and "not_on_the_path" are the
                                        view's files only (?view= is all changes)
  GET   /api/done                       whether the review is Done: {"done", "time", "commit" (the
                                        mark that made it Done: null when it isn't), "lastMark":
                                        {"kind": "done"|"undone"|"cleared", "time", "commit"} or
                                        null, "head" (the commit the branch is at), "openThreads",
                                        "runsInFlight" (open threads with a run queued or working)}
  PUT   /api/done                       mark the review Done at the commit its branch is at, or
                                        undo it: {"done": true|false, "author"?}: the same answer.
                                        "author" must be "reviewer" (the default): anyone else gets
                                        403. 409 while another branch is checked out
  GET   /api/mode                       the review mode: {"mode": "live"|"batched", "held" (the ids
                                        of the held threads, oldest first)}
  PUT   /api/mode                       change it: {"mode", "author"?}: {"mode", "held", "submitted"
                                        (the ids of the threads a change to live submitted: [] for
                                        none)}. "author" must be "reviewer", as for Done
  GET   /api/agent                      the agent that replies in this review: {"agent" (its name),
                                        "source" ("review": a reviewer chose it for this review;
                                        "repository"; "machine": the default), "names" (the machine's
                                        agent list)}
  PUT   /api/agent                      choose the agent for this review: {"agent": <a name on the
                                        list> or null (or "") to clear the choice, "author"?}: the
                                        same answer. "author" must be "reviewer" (the default): anyone
                                        else gets 403. 400 for a name that isn't on the list, naming the
                                        list. A run in progress keeps its agent: the next run uses it
  GET   /api/export[?reply_folder=<folder>]
                                        the review as text (text/plain), for an agent session
                                        the reviewer starts: its commit messages, every thread in
                                        full with its thread status and state, the threads that
                                        need an answer, and how to reply (with --folder <folder>
                                        in the command when a reply_folder is given). It writes
                                        no event
  POST  /api/launch                     a link to difftate's own page on the folder's review, with a
                                        new single-use launch code: {"url"}
  POST  /api/stop                       stop the watcher, after answering {"stopping": true}. Names
                                        no folder
  POST  /api/submit                     submit a batched review: {"author"?}: as PUT /api/mode, with
                                        the held threads "submitted" ([] when none was held: no
                                        run starts). They wait for one run, or queue while one is busy

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
   "statusBy": the reviewer name of the last thread status change (null for none),
   "state": "held"|"waiting"|"queued"|"working"|"replied"|"failed" (null unless open),
   "comments": [{"id", "author": "reviewer"|"agent"|"difftate",
                 "by": the reviewer name (null for a reply, a note, or no name),
                 "kind": "comment"|"reply"|"queued"|"progress", "body", "time"}]}

A view ("" for all changes, a commit such as HEAD~2 for the commits after it, HEAD
for the uncommitted changes, staged or unstaged) shows part of the review: every
thread belongs to the review, whatever view it was written in. POST /api/threads
takes the "view" it was written in (default all changes): its lines are that
view's. Its anchor may also give the "version" of the file the viewer showed (from
the changeset's "versions"): when the file changed since, the thread is written on
that version and moves with its code to where it is now, or is outdated when the
code itself changed. Without one, it is written on the file now: outdated at once
when the code on its lines isn't the code the viewer sent. A thread listed with a view has "inView": false when its code isn't in
that view (its lines are then those of the view it was written in, its anchor's
"view"). A view that isn't one gets 400.

A comment's kind says who wrote it: a comment is the reviewer's (the default), a
reply the coding agent's, and a queued or progress note difftate's. "author" says who
opens a thread or sets its status, and must be "reviewer" (the default): anyone
else gets 403. "reviewer" is the reviewer name: which reviewer writes a comment
or sets a thread status (one line of text, at most 100 characters; 400
otherwise). Without one, it is the repository's git user.name; a thread written
before reviewer names has none. The name is what the caller says: any token
holder can give any name. A reply or note has none (403 for one that gives
it). Only notes can be edited (403 otherwise). Errors are
{"error": <message>} with status 400, 403, 404, 409 or 502. While another branch is
checked out and a run keeps the watcher on this review, opening a thread or
marking a file viewed gets 409, and every thread with an anchor is listed with
"inView": false and its own lines (the code on disk is the other branch's): the
watcher moves to that branch's review once the run ends.

A review is Done at one commit (GLOSSARY.md). A new commit on its branch clears it, and the
watcher keeps the clearing; until then GET /api/done already answers that it is not Done, with
"lastMark" "cleared" by the new commit. A thread, a comment or a thread status change doesn't
clear it. Nothing but the reviewer's PUT marks or undoes it.

A viewed file belongs to the review, like a thread: it stays viewed in every
view, after a reload and after a commit, until its diff in all changes changes
(any edit to the file, even one that keeps its line counts or is inside a new
untracked file). Then it is no longer listed.

`~/.difftate/api.json` says where the API runs: {"port", "pid"}.

The same server serves difftate's own browser viewer (web/, beside this file), a client of
this API like any other, which never sees the token (a coding agent can read the
browser's history). `difftate` opens it with a single-use launch code:
GET /?launch=<code>&folder=<path> trades the code for an HttpOnly, SameSite=Strict cookie and
redirects to /?folder=<path> (the folder the link named: the page names it in every
API request), after which the code is refused. The page (/, layout D) and everything it
loads (/d/style.css, its scripts under /d/, and /diff.js and /review_path.js) need that
cookie. API requests take
the cookie instead of the token only with the header "X-Difftate: page" (which another
site's page can't send without asking) and, when the browser says, the API's own Origin.
Anything else gets 401.
"""
import hashlib
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
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ....core.review.review_path import BadReviewPath
from ....core.review.model import AUTHOR_OF, DIFFTATE, REVIEWER, Conflict, CouldNotRead, NotAllowed, NotFound
from .json_format import (NOTE_KINDS, BadRequest, agent_json, anchor_from_json, changeset_json, comment_json, done_json,
                          fields, mode_json, need, need_agent, need_bool, need_kind, need_mode, need_status, need_text,
                          review_path_json, reviewer_name, submitted_json, thread_json)

MAX_BODY = 1 << 20
_HERE = os.path.dirname(os.path.abspath(__file__))
# The browser viewer's files: (path on disk, Content-Type).
PAGE_FILES = {
    "/": (os.path.join(_HERE, "web", "d", "index.html"), "text/html; charset=utf-8"),
    "/diff.js": (os.path.join(_HERE, "web", "diff.js"), "text/javascript; charset=utf-8"),
    "/review_path.js": (os.path.join(_HERE, "web", "review_path.js"), "text/javascript; charset=utf-8"),
    "/d/style.css": (os.path.join(_HERE, "web", "d", "style.css"), "text/css; charset=utf-8"),
    **{f"/d/{name}.js": (os.path.join(_HERE, "web", "d", f"{name}.js"), "text/javascript; charset=utf-8")
       for name in ("actions", "api", "banners", "conversation", "cursor", "diff_rows", "dom", "draw_conversation",
                    "draw_files", "draw_header", "draw_markdown", "draw_settings", "draw_threads", "draw_toasts",
                    "draw_tree", "draw_views", "draw_vim", "drafts", "file_tree", "files_changed", "keymap", "keys", "main",
                    "markdown", "page", "picker", "poll", "scroll", "settings", "state", "submit", "tabs", "threads",
                    "toasts", "views", "vim", "words")},
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


class PlainText(str):
    """An answer that is text, not JSON (the export)."""


def token_file(folder):
    """Where the review API keeps its token, in the watcher's <folder>."""
    return os.path.join(folder, "token")


class ApiAddress(namedtuple("ApiAddress", "url token_file")):
    """Where a client finds the review API, and the file with its token."""



def running_watcher(home):
    """The pid of the live watcher serving the review API from <home> (the
    difftate folder of the machine), or None."""
    try:
        with open(os.path.join(home, "api.json")) as f:
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


def _answer(response):
    """What the review API answered: JSON, or text for a text/plain answer."""
    data = response.read()
    if response.headers.get_content_type() == "text/plain":
        return data.decode("utf-8")
    return json.loads(data or b"null")


def ask_running_watcher(home, method, path, payload=None):
    """Call the review API of the watcher serving from <home>, as a viewer
    would: (status, the JSON answer, or the text of a text/plain one)."""
    with open(os.path.join(home, "api.json")) as f:
        port = int(json.load(f)["port"])
    with open(os.path.join(home, "token")) as f:
        token = f.read().strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, _answer(r)
    except urllib.error.HTTPError as e:
        with e:
            try:
                return e.code, _answer(e)
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
    core's NotFound (the code reader has no such view); <on_switch>(view) runs
    when a request switches the view."""

    def __init__(self, view, check, on_switch=None):
        self.view = view
        self.check = check
        self.on_switch = on_switch or (lambda view: None)
        self._lock = threading.Lock()

    def current(self):
        with self._lock:
            return self.view

    def switch(self, view):
        """Show <view>, a view already checked."""
        with self._lock:
            self.view = view
        self.on_switch(view)
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
    """The review API of the one watcher: <folders>(folder, base) is what it
    serves for a checked-out folder: an object with review (the use cases of
    the review served now, with its ports bound: main.bind_review: about
    ({"id", "branch", "base"}), list_threads, open_thread, add_comment,
    edit_note, set_status, mark_viewed, list_viewed, read_review_path, review_path_problem (None, or why
    review-path.md can't be used: a warning), set_done, read_done,
    set_mode, read_mode, set_agent_override, read_agent_override, submit,
    export, changeset and checked_out), shown (a ShownView), root (the
    folder's top), who_replies() (who replies: see agent_json) and check_agent(name)
    (raises the core's NotFound for a name not on the list). It raises the core's NotFound for a
    folder it won't serve, or a base that isn't one.

    It writes its token and where it runs (api.json: port, pid) to <home>, the
    difftate folder of the machine. <default_reviewer>(root) is the reviewer
    name of a reviewer's comment or status change that names none (None for no
    name). <on_stop>() runs after POST /api/stop answers."""

    def __init__(self, folders, home, default_reviewer=None, on_stop=None):
        self.folders = folders
        self.default_reviewer = default_reviewer or (lambda root: None)
        self.on_stop = on_stop or (lambda: None)
        self.home = home
        self.token = secrets.token_urlsafe(32)
        self.login = PageLogin()
        self.server = None
        self.token_file = token_file(home)
        self.api_file = os.path.join(home, "api.json")

    def routes(self):
        """Each route the started API has: (method, the compiled pattern of its path)."""
        return self.server.RequestHandlerClass.routes

    def address(self):
        return ApiAddress(f"http://127.0.0.1:{self.server.server_address[1]}", self.token_file)

    def page_url(self, root):
        """A link to the browser viewer on the review of the folder <root>, with
        a new single-use launch code."""
        return f"{self.address().url}/?launch={self.login.new_code()}&folder={urllib.parse.quote(root, safe='')}"

    def start(self):
        os.makedirs(self.home, mode=0o700, exist_ok=True)
        os.chmod(self.home, 0o700)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self.folders, self.token, self.login, self.default_reviewer,
                                                                  self.page_url, self.on_stop))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        _write_private(self.token_file, self.token + "\n")
        _write_private(self.api_file, json.dumps({"port": self.server.server_address[1], "pid": os.getpid()}) + "\n")

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


def _handler(folders, token, login, default_reviewer, page_url, on_stop):
    """<folders>(folder, base): see ReviewApi. <default_reviewer>(root), <page_url>(root)
    and <on_stop>(): see ReviewApi."""
    expected = f"Bearer {token}".encode()

    def a_view(s, given):
        """<given> as a view. The code reader raises NotFound for one that isn't
        a view, and today's published language answers 400 for it: a bad view
        is the request's fault, not a missing thread."""
        try:
            return s.shown.check(given)
        except NotFound as e:
            raise BadRequest(str(e)) from e

    def waiting_for_run(review):
        """While another branch is checked out, the watcher moves to its review
        once the run in progress ends."""
        checkout = review.checked_out()
        return {"waitingForRun": not checkout.on_review_branch, "checkedOut": checkout.branch}

    def get_review(s, q, p):
        review = s.review
        about = {"id": review.about["id"], "branch": review.about["branch"], "base": review.about["base"]}
        return dict(about, **waiting_for_run(review), **mode_json(review.read_mode()), folder=s.root,
                    warnings=s.shown_warnings() + review_path_warnings(review))

    def review_path_warnings(review):
        """A review-path.md that can't be read as a review path, as a warning
        about the review. Derived at each request, so a fixed file has none on
        the next. Its id comes from its text: a viewer shows it once."""
        problem = review.review_path_problem()
        if problem is None:
            return []
        return [{"id": "review-path-" + hashlib.sha1(problem.encode()).hexdigest()[:8], "text": problem,
                 "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}]

    def get_review_path(s, q, p):
        # Given, even empty (all changes), the view is the viewer's: the Neovim viewer shows all changes
        # while the browser shows the staged view
        view = a_view(s, q["view"][0]) if "view" in q else s.shown.current()
        try:
            return review_path_json(s.review.read_review_path(view))
        except BadReviewPath:
            return {"path": None}  # the problem is a warning in /api/review; the viewers use the changeset's order
        except NotFound as e:  # the view shown is no view now
            raise BadRequest(str(e)) from e

    def switch_view(s, q, p):
        return s.shown.switch(a_view(s, fields(p).get("view", "")))

    def get_changeset(s, q, p):
        review = s.review
        view = a_view(s, q["view"][0]) if q.get("view") else s.shown.current()
        try:
            changeset = review.changeset(view)
        except NotFound as e:  # the view shown is no view now
            raise BadRequest(str(e)) from e
        return dict(changeset_json(changeset), **waiting_for_run(review))

    def get_threads(s, q, p):
        view = a_view(s, q["view"][0]) if "view" in q else None
        status = (q.get("status") or [None])[0]
        if status is not None:
            need_status(status)
        return [thread_json(t) for t in s.review.list_threads(status, view)]

    def a_reviewer(s, p, has_name=True):
        """The request's reviewer name; the default only for a reviewer's write."""
        return reviewer_name(p, default_reviewer(s.root) if has_name else None)

    def post_thread(s, q, p):
        given, body = fields(p).get("anchor"), need(p, "body")
        author = fields(p).get("author", "reviewer")
        anchor = anchor_from_json(given, a_view(s, fields(p).get("view", "")))
        by = a_reviewer(s, p, author == REVIEWER)
        return thread_json(s.review.open_thread(author, need_text(body), anchor, by=by))

    def post_comment(s, q, p, thread_id):
        kind, body = fields(p).get("kind", "comment"), need(p, "body")
        need_kind(kind)
        # A comment's kind says who wrote it
        author = AUTHOR_OF[kind]
        by = a_reviewer(s, p, author == REVIEWER)
        return comment_json(s.review.add_comment(author, thread_id, kind, need_text(body), by=by))

    def patch_note(s, q, p, note_id):
        kind, body = need(p, "kind"), need(p, "body")
        need_kind(kind, NOTE_KINDS)
        return comment_json(s.review.edit_note(DIFFTATE, note_id, kind, need_text(body)))

    def patch_status(s, q, p, thread_id):
        status, author = need(p, "status"), fields(p).get("author", "reviewer")
        by = a_reviewer(s, p, author == REVIEWER)
        thread = s.review.set_status(author, thread_id, need_status(status), by=by)
        return {"id": thread.id, "status": thread.status, "statusBy": thread.status_by}

    def put_viewed(s, q, p):
        file, viewed = need(p, "file"), fields(p).get("viewed", True)
        return {"files": s.review.mark_viewed(need_text(file, "file"), need_bool(viewed, "viewed"))}

    def put_done(s, q, p):
        done, author = need_bool(need(p, "done"), "done"), fields(p).get("author", "reviewer")
        return done_json(s.review.set_done(author, done))

    def put_mode(s, q, p):
        mode, author = need_mode(need(p, "mode")), fields(p).get("author", "reviewer")
        return submitted_json(s.review.set_mode(author, mode))

    def put_agent(s, q, p):
        agent, author = need_agent(need(p, "agent")), fields(p).get("author", "reviewer")
        if agent:
            try:
                s.check_agent(agent)
            except NotFound as e:  # a name that isn't on the list is the request's fault
                raise BadRequest(str(e)) from e
        s.review.set_agent_override(author, agent)
        return agent_json(s.who_replies())

    def get_export(s, q, p):
        folder = (q.get("reply_folder") or [None])[0]
        if folder is not None and not folder.strip():
            raise BadRequest("reply_folder must be a path")
        return PlainText(s.review.export(folder))

    def post_submit(s, q, p):
        return submitted_json(s.review.submit(fields(p).get("author", "reviewer")))

    def post_launch(s, q, p):
        return {"url": page_url(s.root)}

    def post_stop(s, q, p):
        stopping.append(True)  # answered first, then the watcher stops
        return {"stopping": True}

    stopping = []

    # (method, path, handler, whether it is about a folder)
    routes = [
        ("GET", r"/api/review", get_review, True),
        ("GET", r"/api/view", lambda s, q, p: {"view": s.shown.current()}, True),
        ("PUT", r"/api/view", switch_view, True),
        ("GET", r"/api/changeset", get_changeset, True),
        ("GET", r"/api/threads", get_threads, True),
        ("POST", r"/api/threads", post_thread, True),
        ("POST", r"/api/threads/([^/]+)/comments", post_comment, True),
        ("PATCH", r"/api/notes/([^/]+)", patch_note, True),
        ("PATCH", r"/api/threads/([^/]+)/status", patch_status, True),
        ("GET", r"/api/viewed", lambda s, q, p: {"files": s.review.list_viewed()}, True),
        ("PUT", r"/api/viewed", put_viewed, True),
        ("GET", r"/api/review-path", get_review_path, True),
        ("GET", r"/api/done", lambda s, q, p: done_json(s.review.read_done()), True),
        ("PUT", r"/api/done", put_done, True),
        ("GET", r"/api/mode", lambda s, q, p: mode_json(s.review.read_mode()), True),
        ("PUT", r"/api/mode", put_mode, True),
        ("GET", r"/api/agent", lambda s, q, p: agent_json(s.who_replies()), True),
        ("PUT", r"/api/agent", put_agent, True),
        ("POST", r"/api/submit", post_submit, True),
        ("GET", r"/api/export", get_export, True),
        ("POST", r"/api/launch", post_launch, True),
        ("POST", r"/api/stop", post_stop, False),
    ]
    routes = [(m, re.compile(f"^{path}$"), fn, about) for m, path, fn, about in routes]

    def served(q):
        """What the watcher serves for the folder (and base) the request names;
        400 when it names none, or one that can't be served."""
        folder = (q.get("folder") or [""])[0].strip()
        if not folder:
            raise BadRequest("folder is required: name the checked-out folder this request is about "
                             "(?folder=<path>)")
        if not os.path.isabs(folder):
            raise BadRequest(f"folder must be an absolute path, not '{folder}'")
        base = (q.get("base") or [""])[0].strip()
        try:
            return folders(folder, base)
        except NotFound as e:
            raise BadRequest(str(e)) from e

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
                folder = urllib.parse.parse_qs(url.query).get("folder", [""])[0]
                where = "/?folder=" + urllib.parse.quote(folder, safe="") if folder else "/"
                return text(303, "text/plain; charset=utf-8", "", [("Location", where), ("Set-Cookie", cookie)])
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
            matches = [(m, rx.match(url.path), fn, about) for m, rx, fn, about in routes]
            matches = [(m, match, fn, about) for m, match, fn, about in matches if match]
            if not matches:
                return self._send(404, {"error": "not found"})
            for method, match, fn, about in matches:
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
                query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
                result = fn(served(query) if about else None, query, payload, *match.groups())
            except BadRequest as e:
                return self._send(400, {"error": str(e)})
            except tuple(STATUS_OF) as e:
                status = next(STATUS_OF[kind] for kind in type(e).__mro__ if kind in STATUS_OF)
                return self._send(status, {"error": str(e)})
            if isinstance(result, PlainText):
                return self._send_bytes(200, "text/plain; charset=utf-8", result.encode())
            self._send(200, result)
            if stopping:
                on_stop()

        do_GET = do_POST = do_PATCH = do_PUT = _handle

    Handler.routes = [(method, path) for method, path, _, _ in routes]
    return Handler
