"""Seam: the review API, difftate's published language, over HTTP.

A scripted review goes through every route: the review, the view, the
changeset in each view, threads (opened, listed by status and in each view,
moved with their code and outdated), comments, replies and notes, thread
status, viewed files, the thread states a run gives, the review while another
branch is checked out, the review mode and submit, and the errors each route
answers. Each answer (status
and JSON) is compared with tests/fixtures/review_api_script.json, recorded
from the review API before it ran on the new core (#66). Ids, times and
hashes are named by where they first appear, so the same review gives the
same transcript.

DT_RECORD=1 writes the fixture again instead of comparing: only when the
published language changes on purpose.

The repository, the review's folder and HOME are temporary; git reads no
config but the test's own.

What a script on git can't show runs on fakes (TheReviewApiOnFakes): a code
reader or a store that fails, a final note, and requests that come at once.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.inbound.review_api import ReviewApi, ShownView  # noqa: E402
from difftate.adapters.outbound import git  # noqa: E402
from difftate.adapters.outbound.coding_agents.reply_channel import DT_REPLY  # noqa: E402
from difftate.adapters.outbound.history_files import HistoryFiles  # noqa: E402
from difftate.adapters.outbound.local_store import LocalStore  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import CouldNotRead, NotFound  # noqa: E402
from difftate.main import bind_review  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "review_api_script.json")
LONG = "".join(f"line_{n} = {n}\n" for n in range(1, 21))


def serve(repo, folder, history):
    """The review API on the review of "feature" against "main" in <repo>, and
    what Dispatch does to that review (runs, threads moving with their code).
    The one place this test knows how the API is built: as the watcher builds
    it, over the local store, the review history files and git."""
    store = LocalStore.open(folder, "feature", "main")
    about = store.review()
    review = bind_review(store, git.GitCodeReader(repo, "main", "feature", about["id"]),
                         HistoryFiles({"review": about["id"]}, history), about)
    shown = ShownView("", lambda view: git.need_view(repo, view))
    entry = SimpleNamespace(review=review, shown=shown, root=repo, shown_warnings=lambda: [])
    api = ReviewApi(lambda given, base: entry, os.path.join(os.path.dirname(history), "watcher-home"),
                    default_reviewer=git.user_name)
    api.test_folder = repo

    class Served:
        def start_run(self, thread_ids):
            review.start_run([t.thread for t in review.list_threads() if t.thread.id in thread_ids])

        def end_run(self, outcome):
            review.end_run(outcome)

        def move_with_code(self):
            review.move_with_code()

    served = Served()
    served.api = api
    return served


def answer_of(response):
    """What the API answered: its JSON, or its text for a text/plain answer (the export)."""
    data = response.read()
    if response.headers.get_content_type() == "text/plain":
        return data.decode("utf-8")
    return json.loads(data or b"null")


def wait_until(check, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def with_folder(path, folder):
    return path + ("&" if "?" in path else "?") + "folder=" + urllib.parse.quote(folder, safe="")


def ask(api, method, path, payload=None, token=True, body=None, folder=True):
    """Call the review API as a viewer would, about the folder it serves (<folder> False: naming none,
    or a string: that one): (status, the JSON answer, or the text of the export)."""
    if folder:
        path = with_folder(path, api.test_folder if folder is True else folder)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {api.token}"
    data = body if body is not None else (None if payload is None else json.dumps(payload).encode())
    req = urllib.request.Request(api.address().url + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, answer_of(r)
    except urllib.error.HTTPError as e:
        with e:
            return e.code, answer_of(e)


# ── Naming what differs from run to run ──────────────────────────────────────
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HASH = re.compile(r"\b[0-9a-f]{40}\b")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
INDEX = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+", re.M)


class Names:
    """Each id and hash named by its first appearance: <id-1>, <hash-1>, …"""

    def __init__(self, paths=None):
        self.seen = {}
        self.paths = dict(paths or {})  # path: its name, for a machine's own paths in the answers

    def _name(self, kind, found):
        return self.seen.setdefault(found, f"<{kind}-{sum(1 for v in self.seen.values() if v.startswith('<' + kind)) + 1}>")

    def text(self, s):
        s = INDEX.sub("index <blob>..<blob>", s)
        s = UUID.sub(lambda m: self._name("id", m[0]), s)
        s = HASH.sub(lambda m: self._name("hash", m[0]), s)
        # The export names a thread by the first 8 characters of its id
        for found, name in list(self.seen.items()):
            if UUID.fullmatch(found):
                s = s.replace(found[:8], name[:-1] + ":8>")
        for path, name in self.paths.items():
            s = s.replace(path, name)
        return TIME.sub("<time>", s)

    def json(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json(v) for v in value]
        if isinstance(value, dict):
            return {self.text(k): self.json(v) for k, v in value.items()}
        return value


class TheReviewApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftate-review-api-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        with open(os.path.join(home, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n[commit]\n\tgpgsign = false\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(HOME=home, XDG_CONFIG_HOME=os.path.join(home, ".config"), GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=os.path.join(home, ".gitconfig"))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "def greet(name):\n    return 'hi ' + name\n")
        self.write("README.md", "# demo\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "first")
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.write("long.py", LONG)
        self.git("add", ".")
        self.git("commit", "-q", "-m", "second")
        # Uncommitted: README.md staged, long.py not
        self.write("README.md", "# demo\nMore.\n")
        self.git("add", "README.md")
        self.write("long.py", LONG.replace("line_18 = 18", "line_18 = 180"))

        self.served = serve(self.repo, os.path.join(self.repo, ".git", "difftate"),
                            os.path.join(self.tmp, "history"))
        self.served.api.start()
        self.addCleanup(self.served.api.stop)
        self.names = Names({DT_REPLY: "<dt-reply>", self.repo: "<repo>"})
        self.transcript = []

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True)

    def write(self, path, text):
        with open(os.path.join(self.repo, path), "w") as f:
            f.write(text)

    def call(self, method, path, payload=None, token=True, body=None):
        """Ask the API, and keep the answer in the transcript: the JSON."""
        status, answer = ask(self.served.api, method, path, payload, token, body)
        self.transcript.append({"request": self.names.json([method, path, payload]),
                                "status": status, "answer": self.names.json(answer)})
        return answer

    def anchor(self, file, start, end=None, side="new", code=None):
        end = end or start
        if code is None:
            with open(os.path.join(self.repo, file)) as f:
                code = "\n".join(f.read().split("\n")[start - 1:end])
        return {"file": file, "side": side, "startLine": start, "endLine": end, "code": code}

    def script(self):
        """Every route, as a viewer, Dispatch and the formatter use it."""
        call = self.call
        # The review, the view and the changeset in each view
        call("GET", "/api/review")
        call("GET", "/api/view")
        for query in ("", "?view=", "?view=HEAD~1", "?view=HEAD", "?view=staged", "?view=unstaged", "?view=nope"):
            call("GET", "/api/changeset" + query)
        call("GET", "/api/threads")

        # Threads: on a line, general, in another view, on code that changed, on the old side
        on_line = call("POST", "/api/threads", {"anchor": self.anchor("app.py", 2), "body": "Why an f-string?"})["id"]
        general = call("POST", "/api/threads", {"anchor": None, "body": "Is this ready?", "author": "reviewer"})["id"]
        call("POST", "/api/threads", {"anchor": self.anchor("long.py", 18), "body": "Why 180?", "view": "unstaged"})
        call("POST", "/api/threads", {"anchor": self.anchor("app.py", 1, code="def greet(nam):"), "body": "Typo?"})
        old_side = call("POST", "/api/threads", {"anchor": self.anchor("app.py", 2, side="old",
                                                                       code="    return 'hi ' + name"),
                                                 "body": "Why was this concatenated?"})["id"]
        call("POST", "/api/threads", {"anchor": self.anchor("long.py", 5, 6), "body": "Why 5 and 6?"})
        call("POST", "/api/threads", {"anchor": {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2},
                                      "body": "No code sent"})
        for refused in ({"anchor": self.anchor("app.py", 2), "body": "Mine", "author": "agent"},
                        {"anchor": None, "body": "Mine", "author": "difftate"},
                        {"anchor": {"file": "app.py", "side": "middle", "startLine": 2, "endLine": 2}, "body": "Hi"},
                        {"anchor": {"file": "app.py", "side": "new", "startLine": 3, "endLine": 2}, "body": "Hi"},
                        {"anchor": {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2, "code": 5},
                         "body": "Hi"},
                        {"anchor": None}, {"anchor": None, "body": "  "}, {"anchor": None, "body": "Hi", "view": "nope"},
                        ["not", "an", "object"]):
            call("POST", "/api/threads", refused)

        # Comments, replies and notes
        call("POST", f"/api/threads/{on_line}/comments", {"body": "And the name?"})
        call("POST", f"/api/threads/{general}/comments", {"kind": "comment", "body": "Still?"})
        progress = call("POST", f"/api/threads/{on_line}/comments", {"kind": "progress", "body": "⏳ Thinking…"})["id"]
        queued = call("POST", f"/api/threads/{old_side}/comments", {"kind": "queued", "body": "🕒 Queued"})["id"]
        for refused in ({"kind": "note", "body": "Hi"}, {"kind": "comment"}, {"body": ""}):
            call("POST", f"/api/threads/{on_line}/comments", refused)
        call("POST", "/api/threads/no-such-thread/comments", {"body": "Hello?"})
        call("PATCH", f"/api/notes/{progress}", {"kind": "progress", "body": "⏳ Read app.py"})
        call("PATCH", f"/api/notes/{queued}", {"kind": "progress", "body": "⏳ Picked up"})
        first_comment = self.served_thread(on_line)["comments"][0]["id"]
        for path, refused in ((f"/api/notes/{first_comment}", {"kind": "progress", "body": "Overwritten"}),
                              (f"/api/notes/{progress}", {"kind": "reply", "body": "A reply now"}),
                              (f"/api/notes/{progress}", {"body": "No kind"}),
                              (f"/api/notes/{progress}", {"kind": "progress", "body": " "}),
                              ("/api/notes/no-such-note", {"kind": "progress", "body": "Hello?"})):
            call("PATCH", path, refused)

        # Runs: working, queued, replied and failed
        self.served.start_run([on_line])
        call("GET", "/api/threads")
        call("POST", f"/api/threads/{on_line}/comments", {"kind": "reply", "body": "It reads better."})
        call("POST", "/api/threads", {"anchor": None, "body": "Opened during a run"})
        self.served.end_run("done")
        call("GET", "/api/threads?status=open")
        self.served.start_run([general])
        self.served.end_run("failed")
        call("GET", "/api/threads")

        # Thread status
        call("PATCH", f"/api/threads/{general}/status", {"status": "resolved"})
        call("PATCH", f"/api/threads/{old_side}/status", {"status": "dismissed", "author": "reviewer"})
        for path, refused in ((f"/api/threads/{on_line}/status", {"status": "resolved", "author": "agent"}),
                              (f"/api/threads/{on_line}/status", {"status": "closed"}),
                              (f"/api/threads/{on_line}/status", {}),
                              ("/api/threads/no-such-thread/status", {"status": "resolved"})):
            call("PATCH", path, refused)
        for query in ("?status=open", "?status=resolved", "?status=dismissed", "?status=closed"):
            call("GET", "/api/threads" + query)
        call("PATCH", f"/api/threads/{old_side}/status", {"status": "open"})

        # Each thread where its code is in each view
        for query in ("?view=", "?view=HEAD~1", "?view=HEAD", "?view=staged", "?view=unstaged",
                      "?view=staged&status=open", "?view=nope"):
            call("GET", "/api/threads" + query)

        # Viewed files
        call("GET", "/api/viewed")
        call("PUT", "/api/viewed", {"file": "long.py"})
        call("PUT", "/api/viewed", {"file": "app.py", "viewed": True})
        call("PUT", "/api/viewed", {"file": "README.md"})
        call("PUT", "/api/viewed", {"file": "README.md", "viewed": False})
        for refused in ({"file": "nope.py"}, {}, {"file": ""}, {"file": "app.py", "viewed": "yes"}):
            call("PUT", "/api/viewed", refused)
        call("GET", "/api/viewed")

        # Threads move with their code, or are outdated; an edit clears a viewed mark
        self.write("long.py", "# top\n# more\n" + LONG.replace("line_18 = 18", "line_18 = 180"))
        self.served.move_with_code()
        call("GET", "/api/threads")
        call("GET", "/api/threads?view=staged")  # the lines above aren't staged: lines 7-8 are 5-6 there
        call("GET", "/api/viewed")
        self.write("long.py", "# top\n# more\n" + LONG.replace("line_18 = 18", "line_18 = 180")
                   .replace("line_5 = 5", "line_5 = 50"))
        self.served.move_with_code()
        call("GET", "/api/threads?view=unstaged")

        # The view viewers show
        call("PUT", "/api/view", {"view": "HEAD"})
        call("GET", "/api/view")
        call("GET", "/api/changeset")
        for refused in ({"view": "nope"}, {"view": 5}):
            call("PUT", "/api/view", refused)
        call("PUT", "/api/view", {})
        call("GET", "/api/view")

        # Another branch checked out: the review waits for the run, and reads none of its code
        self.git("checkout", "-q", "-b", "other")
        call("GET", "/api/review")
        call("GET", "/api/changeset")
        call("GET", "/api/threads?view=")
        call("POST", "/api/threads", {"anchor": None, "body": "On which branch?"})
        call("PUT", "/api/viewed", {"file": "app.py"})
        call("GET", "/api/viewed")
        self.git("checkout", "-q", "feature")
        call("GET", "/api/review")

        # A thread on the version of the file the viewer showed: it moves with code that only moved since
        shown = call("GET", "/api/changeset")["versions"]["app.py"]["new"]
        self.write("app.py", "import os\n\ndef greet(name):\n    return f'hello {name}'\n")
        call("POST", "/api/threads", {"anchor": dict(self.anchor("app.py", 4), startLine=2, endLine=2,
                                                     version=shown), "body": "Shown before the import"})
        for refused in (5, ""):
            call("POST", "/api/threads", {"anchor": dict(self.anchor("app.py", 4), version=refused), "body": "Hi"})

        # The review mode: batched holds comments until submit; changing to live submits too
        call("GET", "/api/mode")
        call("PUT", "/api/mode", {"mode": "batched"})
        call("POST", "/api/threads", {"anchor": None, "body": "Held until I submit"})
        call("POST", f"/api/threads/{on_line}/comments", {"body": "A follow-up, held too"})
        call("GET", "/api/review")
        call("GET", "/api/threads?status=open")
        for path, refused in (("/api/mode", {"mode": "pending"}), ("/api/mode", {}),
                              ("/api/mode", {"mode": "live", "author": "agent"})):
            call("PUT", path, refused)
        call("POST", "/api/submit", {"author": "agent"})
        call("POST", "/api/submit", {})
        call("GET", "/api/threads?status=open")
        call("POST", "/api/submit")
        call("PUT", "/api/mode", {"mode": "batched"})
        call("POST", "/api/threads", {"anchor": None, "body": "Held, then live"})
        # The export: held threads by their state, the folder in the reply command when one was given
        call("GET", "/api/export")
        call("GET", f"/api/export?reply_folder={urllib.parse.quote(self.repo)}")
        call("PUT", "/api/mode", {"mode": "live", "author": "reviewer"})
        call("GET", "/api/mode")
        call("GET", "/api/export")
        call("POST", "/api/export", {})

        # What isn't a route, a method, a token or JSON
        call("GET", "/api/nope")
        call("POST", "/api/review", {})
        call("GET", "/api/threads", token=False)
        call("POST", "/api/threads", body=b"{not json")

    def served_thread(self, tid):
        """A thread as the API lists it, outside the transcript."""
        return next(t for t in ask(self.served.api, "GET", "/api/threads")[1] if t["id"] == tid)

    def test_every_route_answers_a_scripted_review_as_it_did_before(self):
        self.script()

        if os.environ.get("DT_RECORD"):
            os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
            with open(FIXTURE, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.transcript, indent=1, ensure_ascii=False) + "\n")
            self.skipTest(f"recorded {FIXTURE}")
        with open(FIXTURE, encoding="utf-8") as f:
            recorded = json.load(f)
        for n, (now, before) in enumerate(zip(self.transcript, recorded)):
            with self.subTest(step=n, request=before["request"]):
                self.assertEqual(now, before)
        self.assertEqual(len(self.transcript), len(recorded))



VIEWS = ("", "HEAD", "staged", "unstaged")


def a_fake_view(view):
    """The view check, as the git adapter's need_view: NotFound for no view."""
    if view not in VIEWS:
        raise NotFound(f"no view '{view}'")
    return view


class ServedOnFakes:
    """The review API on the use cases as the watcher binds them, over the
    memory store and a fake code reader."""

    def serve(self, store=None, code=None, view="", default_reviewer=None):
        tmp = tempfile.mkdtemp(prefix="difftate-review-api-fakes-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.review = bind_review(store or MemoryStore(), code or FakeCode({"app.py": "x = 1\n"}),
                                  FakeHistory(), {"id": "r", "branch": "feature", "base": "main"})
        self.agents = ["personal", "work"]  # the machine's agent list; its default is the first
        self.repository_agent = ""

        def agent():
            chosen = self.review.read_agent_override()
            return SimpleNamespace(name=chosen or self.repository_agent or self.agents[0], names=self.agents,
                                   source="review" if chosen else "repository" if self.repository_agent else "machine")

        def check_agent(name):
            if name not in self.agents:
                raise NotFound(f"no agent '{name}' in the agent list: {', '.join(self.agents)}")

        self.warnings = []
        entry = SimpleNamespace(review=self.review, shown=ShownView(view, a_fake_view), root=tmp,
                                who_replies=agent, check_agent=check_agent,
                                shown_warnings=lambda: list(self.warnings))

        def folders(folder, base):
            if folder != tmp:
                raise NotFound(f"{folder} is not a checked-out folder of a git repository")
            self.asked_base = base
            return entry

        self.stopped = []
        self.api = ReviewApi(folders, tmp, default_reviewer=default_reviewer, on_stop=lambda: self.stopped.append(1))
        self.api.test_folder = tmp
        self.api.start()
        self.addCleanup(self.api.stop)

    def ask(self, *args, **kwargs):
        return ask(self.api, *args, **kwargs)


class TheReviewApiOnFakes(ServedOnFakes, unittest.TestCase):
    def test_a_review_comes_with_its_warnings_each_with_an_id_and_a_time(self):
        self.serve()
        self.assertEqual(self.ask("GET", "/api/review")[1]["warnings"], [])
        warning = {"id": "w1", "time": "2026-01-02T03:04:05+00:00", "text": "the store was restored"}
        self.warnings.append(warning)

        self.assertEqual(self.ask("GET", "/api/review")[1]["warnings"], [warning])

    def test_every_request_must_name_its_folder(self):
        self.serve()

        for method, path in (("GET", "/api/review"), ("GET", "/api/threads"), ("PUT", "/api/view"),
                             ("POST", "/api/submit"), ("GET", "/api/export")):
            with self.subTest(path=path):
                status, answer = self.ask(method, path, {} if method != "GET" else None, folder=False)
                self.assertEqual(status, 400)
                self.assertIn("folder is required", answer["error"])
        status, answer = self.ask("GET", "/api/threads?folder=", folder=False)
        self.assertEqual((status, "folder is required" in answer["error"]), (400, True), "an empty folder names none")

    def test_a_path_the_watcher_wont_serve_is_refused(self):
        self.serve()

        status, answer = self.ask("GET", "/api/threads", folder="/not/a/checkout")

        self.assertEqual(status, 400)
        self.assertIn("/not/a/checkout is not a checked-out folder", answer["error"])

    def test_a_base_the_request_names_goes_to_the_watcher_and_none_means_the_folders_own(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/review?base=develop")[0], 200)
        self.assertEqual(self.asked_base, "develop")
        self.assertEqual(self.ask("GET", "/api/review")[0], 200)
        self.assertEqual(self.asked_base, "")

    def test_a_view_request_no_longer_opens_a_viewer(self):
        self.serve()

        status, answer = self.ask("PUT", "/api/view", {"view": "", "open": "browser"})

        self.assertEqual((status, answer), (200, {"view": ""}), "the watcher never opens a viewer: open is ignored")

    def test_stop_asks_the_watcher_to_stop_after_it_answers_and_names_no_folder(self):
        self.serve()

        self.assertEqual(self.ask("POST", "/api/stop", {}, token=False, folder=False)[0], 401)
        self.assertEqual(self.stopped, [])
        status, answer = self.ask("POST", "/api/stop", {}, folder=False)

        self.assertEqual((status, answer), (200, {"stopping": True}))
        wait_until(lambda: self.stopped)

    def test_a_launch_gives_a_link_to_the_page_naming_the_folder_with_a_single_use_code(self):
        self.serve()

        status, answer = self.ask("POST", "/api/launch", {})

        self.assertEqual(status, 200)
        self.assertRegex(answer["url"], rf"^http://127\.0\.0\.1:\d+/\?launch=[\w-]+&folder={urllib.parse.quote(self.api.test_folder, safe='')}$")

    def test_code_that_cannot_be_read_is_502(self):
        self.serve(code=UnreadableCode())
        anchor = {"file": "app.py", "side": "new", "startLine": 1, "endLine": 1}

        for method, path, payload in (("POST", "/api/threads", {"anchor": anchor, "body": "Why?"}),
                                      ("GET", "/api/changeset", None), ("GET", "/api/viewed", None),
                                      ("PUT", "/api/viewed", {"file": "app.py"})):
            with self.subTest(path=path):
                status, answer = self.ask(method, path, payload)
                self.assertEqual((status, set(answer)), (502, {"error"}))

    def test_a_change_the_store_cannot_keep_is_502(self):
        self.serve(store=StoreThatCannotWrite())

        self.assertEqual(self.ask("POST", "/api/threads", {"body": "Is this ready?"}),
                         (502, {"error": "could not write the review"}))
        self.assertEqual(self.ask("GET", "/api/threads"), (200, []))

    def test_a_final_note_is_409(self):
        self.serve()
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]
        note = self.review.add_comment("difftate", tid, "progress", "Thinking…")
        self.review.edit_note("difftate", note.id, "progress", "✅ Done in 3s", final=True)

        self.assertEqual(self.ask("PATCH", f"/api/notes/{note.id}", {"kind": "progress", "body": "Late"}),
                         (409, {"error": f"the note {note.id} is final"}))

    def test_a_view_shown_that_is_no_view_now_is_400_not_404(self):
        self.serve(view="HEAD~3")  # its commit is gone since it was shown

        status, answer = self.ask("GET", "/api/changeset")

        self.assertEqual((status, answer), (400, {"error": "no view 'HEAD~3'"}))

    def test_comments_sent_at_once_each_keep_their_own_place(self):
        self.serve(store=SlowStore())
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]

        def comment(n):
            self.ask("POST", f"/api/threads/{tid}/comments", {"body": f"Comment {n}"})
        senders = [threading.Thread(target=comment, args=(n,)) for n in range(8)]
        for sender in senders:
            sender.start()
        for sender in senders:
            sender.join()

        [thread] = self.review.list_threads()
        self.assertEqual(sorted(c.body for c in thread.thread.comments[1:]), [f"Comment {n}" for n in range(8)])
        self.assertEqual([c.seq for c in thread.thread.comments], list(range(1, 10)), "each its own place")


class TheDoneRoutes(ServedOnFakes, unittest.TestCase):
    """GET and PUT /api/done: whether the review is Done, and the reviewer's mark."""

    def serve(self, code=None, **kwargs):
        self.code = code or FakeCode({"app.py": "x = 1\n"}, commit="commit-1")
        super().serve(code=self.code, **kwargs)

    def test_a_review_nobody_marked_is_not_done(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/done"), (200, {
            "done": False, "time": None, "commit": None, "lastMark": None, "head": "commit-1",
            "openThreads": 0, "runsInFlight": 0}))

    def test_the_reviewer_marks_it_done_at_the_head_commit_and_the_answer_says_so(self):
        self.serve()

        status, answer = self.ask("PUT", "/api/done", {"done": True})

        self.assertEqual(status, 200)
        mark = {"kind": "done", "time": answer["time"], "commit": "commit-1"}
        self.assertRegex(answer["time"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual(answer, {"done": True, "time": answer["time"], "commit": "commit-1", "lastMark": mark,
                                  "head": "commit-1", "openThreads": 0, "runsInFlight": 0})
        self.assertEqual(self.ask("GET", "/api/done"), (200, answer))

    def test_it_counts_the_open_threads_and_those_with_a_run_in_flight(self):
        self.serve()
        first = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]
        self.ask("POST", "/api/threads", {"body": "And this?"})
        self.review.start_run([t.thread for t in self.review.list_threads() if t.thread.id == first])

        answer = self.ask("GET", "/api/done")[1]

        self.assertEqual((answer["openThreads"], answer["runsInFlight"]), (2, 2))

    def test_the_reviewer_undoes_it(self):
        self.serve()
        self.ask("PUT", "/api/done", {"done": True})

        status, answer = self.ask("PUT", "/api/done", {"done": False})

        self.assertEqual((status, answer["done"], answer["commit"], answer["lastMark"]["kind"]),
                         (200, False, None, "undone"))

    def test_a_new_commit_clears_it(self):
        self.serve()
        self.ask("PUT", "/api/done", {"done": True})
        self.code.commit = "commit-2"

        answer = self.ask("GET", "/api/done")[1]

        self.assertEqual((answer["done"], answer["head"], answer["lastMark"]["kind"], answer["lastMark"]["commit"]),
                         (False, "commit-2", "cleared", "commit-2"))

    def test_a_new_thread_does_not_clear_it(self):
        self.serve()
        self.ask("PUT", "/api/done", {"done": True})

        self.ask("POST", "/api/threads", {"body": "One more thing"})

        answer = self.ask("GET", "/api/done")[1]
        self.assertEqual((answer["done"], answer["openThreads"]), (True, 1))

    def test_only_a_reviewer_marks_or_undoes_it(self):
        self.serve()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                status, answer = self.ask("PUT", "/api/done", {"done": True, "author": author})
                self.assertEqual((status, set(answer)), (403, {"error"}))
        self.assertFalse(self.ask("GET", "/api/done")[1]["done"])
        self.ask("PUT", "/api/done", {"done": True})
        self.assertEqual(self.ask("PUT", "/api/done", {"done": False, "author": "agent"})[0], 403)
        self.assertTrue(self.ask("GET", "/api/done")[1]["done"])

    def test_a_request_that_does_not_say_done_or_not_is_400(self):
        self.serve()

        for payload in (None, {}, {"done": "yes"}, {"done": 1}, [True]):
            with self.subTest(payload=payload):
                status, answer = self.ask("PUT", "/api/done", payload)
                self.assertEqual((status, set(answer)), (400, {"error"}))
        self.assertFalse(self.ask("GET", "/api/done")[1]["done"])

    def test_while_another_branch_is_checked_out_marking_it_is_409(self):
        self.serve()
        self.code.checked_out = False

        status, answer = self.ask("PUT", "/api/done", {"done": True})

        self.assertEqual((status, set(answer)), (409, {"error"}))

    def test_a_branch_the_repository_does_not_have_cannot_be_marked(self):
        self.serve()
        self.code.commit = None

        status, answer = self.ask("PUT", "/api/done", {"done": True})

        self.assertEqual((status, set(answer)), (502, {"error"}))

    def test_a_mark_the_store_cannot_keep_is_502(self):
        self.serve(store=StoreThatCannotWrite())

        status, answer = self.ask("PUT", "/api/done", {"done": True})

        self.assertEqual((status, answer), (502, {"error": "could not write the review"}))
        self.assertFalse(self.ask("GET", "/api/done")[1]["done"])

    def test_the_watcher_records_the_clearing_a_new_commit_makes(self):
        self.serve()
        self.ask("PUT", "/api/done", {"done": True})
        self.code.commit = "commit-2"

        self.review.clear_done()

        self.assertEqual(self.ask("GET", "/api/done")[1]["lastMark"]["kind"], "cleared")


class TheExportRoute(ServedOnFakes, unittest.TestCase):
    """GET /api/export: the review as text for an agent session the reviewer
    starts. It writes no event."""

    def a_thread(self, body="Is this ready?"):
        return self.ask("POST", "/api/threads", {"body": body})[1]["id"]

    def test_answers_the_review_as_text_with_its_commits_threads_states_and_how_to_reply(self):
        self.serve(code=FakeCode({"app.py": "x = 1\n"}, messages=["Start with x"]))
        self.ask("PUT", "/api/mode", {"mode": "batched"})
        tid = self.a_thread("Why x?")

        status, text = self.ask("GET", "/api/export")

        self.assertEqual(status, 200)
        self.assertIn("Start with x", text)
        self.assertIn(f"### Thread {tid[:8]} — general thread (not tied to a line) — open (held)\nreviewer: Why x?",
                      text)
        self.assertRegex(text, r'Reply to a thread with: \S*dt-reply <thread> "<answer>"')

    def test_names_the_folder_in_the_reply_command_when_one_is_given(self):
        self.serve()

        text = self.ask("GET", "/api/export?reply_folder=" + urllib.parse.quote("/work/my demo"))[1]

        self.assertRegex(text, r"dt-reply --folder '/work/my demo' <thread> ")

    def test_writes_no_event_and_changes_no_thread(self):
        store = MemoryStore()
        self.serve(store=store)
        tid = self.a_thread()
        events = list(store.load())

        self.ask("GET", "/api/export")

        self.assertEqual(store.load(), events)
        self.assertEqual(self.ask("GET", "/api/threads")[1][0]["state"], "waiting")
        self.assertEqual(self.ask("GET", "/api/threads")[1][0]["id"], tid)

    def test_needs_the_token(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/export", token=False), (401, {"error": "missing or wrong token"}))

    def test_commit_messages_that_cannot_be_read_are_502_not_an_export_without_them(self):
        class UnreadableCommits(FakeCode):
            def commit_messages(self):
                raise CouldNotRead("could not read the review's commits")

        self.serve(code=UnreadableCommits({"app.py": "x = 1\n"}))

        self.assertEqual(self.ask("GET", "/api/export"), (502, {"error": "could not read the review's commits"}))

    def test_is_for_reading_only(self):
        self.serve()

        self.assertEqual(self.ask("POST", "/api/export", {})[0], 405)


class TheAgentRoutes(ServedOnFakes, unittest.TestCase):
    """GET and PUT /api/agent: who replies in this review, and the reviewer's
    choice of another agent from the machine's list."""

    def test_it_names_the_agent_where_it_comes_from_and_the_list(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/agent"),
                         (200, {"agent": "personal", "source": "machine", "names": ["personal", "work"]}))
        self.repository_agent = "work"
        self.assertEqual(self.ask("GET", "/api/agent"),
                         (200, {"agent": "work", "source": "repository", "names": ["personal", "work"]}))

    def test_a_reviewer_chooses_an_agent_for_the_review_and_clears_the_choice(self):
        self.serve()
        self.repository_agent = "work"

        self.assertEqual(self.ask("PUT", "/api/agent", {"agent": "personal"}),
                         (200, {"agent": "personal", "source": "review", "names": ["personal", "work"]}))
        self.assertEqual(self.ask("GET", "/api/agent")[1]["source"], "review")
        self.assertEqual(self.review.read_agent_override(), "personal")

        for clear in (None, ""):
            self.ask("PUT", "/api/agent", {"agent": "personal"})
            self.assertEqual(self.ask("PUT", "/api/agent", {"agent": clear}),
                             (200, {"agent": "work", "source": "repository", "names": ["personal", "work"]}))
            self.assertEqual(self.review.read_agent_override(), "")

    def test_a_name_that_is_not_on_the_list_is_400_naming_the_list_and_changes_nothing(self):
        self.serve()
        self.ask("PUT", "/api/agent", {"agent": "work"})

        status, answer = self.ask("PUT", "/api/agent", {"agent": "wrok"})

        self.assertEqual(status, 400)
        self.assertIn("no agent 'wrok'", answer["error"])
        self.assertIn("personal, work", answer["error"])
        self.assertEqual(self.review.read_agent_override(), "work")

    def test_only_a_reviewer_chooses_it(self):
        self.serve()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                self.assertEqual(self.ask("PUT", "/api/agent", {"agent": "work", "author": author})[0], 403)
        self.assertEqual(self.review.read_agent_override(), "")

    def test_a_request_that_names_no_agent_is_400(self):
        self.serve()

        for payload in (None, {}, {"agent": 1}, {"agent": ["work"]}):
            with self.subTest(payload=payload):
                self.assertEqual(self.ask("PUT", "/api/agent", payload)[0], 400)

    def test_it_needs_the_token(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/agent", token=False)[0], 401)
        self.assertEqual(self.ask("PUT", "/api/agent", {"agent": "work"}, token=False)[0], 401)


class TheModeRoutes(ServedOnFakes, unittest.TestCase):
    """GET and PUT /api/mode and POST /api/submit: the review mode, held
    threads, and the reviewer's submit."""

    def a_thread(self, body="Is this ready?"):
        return self.ask("POST", "/api/threads", {"body": body})[1]["id"]

    def state(self, tid):
        return next(t for t in self.ask("GET", "/api/threads")[1] if t["id"] == tid)["state"]

    def test_a_new_review_is_live_with_nothing_held(self):
        self.serve()

        self.assertEqual(self.ask("GET", "/api/mode"), (200, {"mode": "live", "held": []}))
        answer = self.ask("GET", "/api/review")[1]
        self.assertEqual((answer["mode"], answer["held"]), ("live", []))

    def test_the_review_names_the_folder_the_watcher_runs_in_so_a_viewer_can_export_it(self):
        self.serve()

        folder = self.ask("GET", "/api/review")[1]["folder"]
        status, text = self.ask("GET", f"/api/export?reply_folder={urllib.parse.quote(folder)}")
        self.assertEqual(status, 200)
        self.assertIn(f"dt-reply --folder {folder}", text)

    def test_in_a_batched_review_a_comment_is_held_and_the_review_says_which(self):
        self.serve()

        self.assertEqual(self.ask("PUT", "/api/mode", {"mode": "batched"}),
                         (200, {"mode": "batched", "held": [], "submitted": []}))
        tid = self.a_thread()

        self.assertEqual(self.state(tid), "held")
        self.assertEqual(self.ask("GET", "/api/mode"), (200, {"mode": "batched", "held": [tid]}))
        self.assertEqual(self.ask("GET", "/api/review")[1]["held"], [tid])

    def test_submit_names_the_threads_it_sent_and_they_wait_for_a_run(self):
        self.serve()
        self.ask("PUT", "/api/mode", {"mode": "batched"})
        tid = self.a_thread()

        self.assertEqual(self.ask("POST", "/api/submit", {}),
                         (200, {"mode": "batched", "held": [], "submitted": [tid]}))
        self.assertEqual(self.state(tid), "waiting")

    def test_submit_with_nothing_held_says_it_sent_none(self):
        self.serve()
        self.ask("PUT", "/api/mode", {"mode": "batched"})

        self.assertEqual(self.ask("POST", "/api/submit"), (200, {"mode": "batched", "held": [], "submitted": []}))

    def test_changing_to_live_submits_the_held_threads(self):
        self.serve()
        self.ask("PUT", "/api/mode", {"mode": "batched"})
        tid = self.a_thread()

        self.assertEqual(self.ask("PUT", "/api/mode", {"mode": "live", "author": "reviewer"}),
                         (200, {"mode": "live", "held": [], "submitted": [tid]}))
        self.assertEqual(self.state(tid), "waiting")

    def test_only_a_reviewer_changes_the_mode_or_submits(self):
        self.serve()
        self.ask("PUT", "/api/mode", {"mode": "batched"})
        self.a_thread()

        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                for method, path, payload in (("PUT", "/api/mode", {"mode": "live", "author": author}),
                                              ("POST", "/api/submit", {"author": author})):
                    status, answer = self.ask(method, path, payload)
                    self.assertEqual((status, set(answer)), (403, {"error"}), path)
        self.assertEqual(self.ask("GET", "/api/mode")[1]["mode"], "batched")
        self.assertEqual(len(self.ask("GET", "/api/mode")[1]["held"]), 1)

    def test_a_request_that_names_no_mode_is_400(self):
        self.serve()

        for payload in (None, {}, {"mode": "pending"}, {"mode": 1}, ["batched"]):
            with self.subTest(payload=payload):
                status, answer = self.ask("PUT", "/api/mode", payload)
                self.assertEqual((status, set(answer)), (400, {"error"}))
        self.assertEqual(self.ask("GET", "/api/mode")[1]["mode"], "live")

    def test_a_change_the_store_cannot_keep_is_502(self):
        self.serve(store=StoreThatCannotWrite())

        status, answer = self.ask("PUT", "/api/mode", {"mode": "batched"})

        self.assertEqual((status, answer), (502, {"error": "could not write the review"}))


class TheReviewerName(ServedOnFakes, unittest.TestCase):
    """The reviewer name the review API takes ("reviewer"), and gives back on
    each comment ("by") and on a thread's last status change ("statusBy")."""

    def serve(self, default_reviewer=lambda root: "Ada"):
        super().serve(default_reviewer=default_reviewer)

    def thread(self, tid):
        return next(t for t in self.ask("GET", "/api/threads")[1] if t["id"] == tid)

    def test_two_reviewers_comment_on_one_thread_and_the_one_who_resolves_it_is_named(self):
        self.serve()
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?", "reviewer": "security-bot"})[1]["id"]
        status, comment = self.ask("POST", f"/api/threads/{tid}/comments", {"body": "Tests?", "reviewer": "docs-bot"})
        self.assertEqual((status, comment["by"]), (200, "docs-bot"))

        status, answer = self.ask("PATCH", f"/api/threads/{tid}/status", {"status": "resolved", "reviewer": "docs-bot"})

        self.assertEqual((status, answer), (200, {"id": tid, "status": "resolved", "statusBy": "docs-bot"}))
        thread = self.thread(tid)
        self.assertEqual([(c["author"], c["by"], c["body"]) for c in thread["comments"]],
                         [("reviewer", "security-bot", "Is this ready?"), ("reviewer", "docs-bot", "Tests?")])
        self.assertEqual(thread["statusBy"], "docs-bot")

    def test_without_a_name_the_reviewer_is_the_default_reviewer(self):
        self.serve(default_reviewer=lambda root: "Ada")
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]
        self.ask("POST", f"/api/threads/{tid}/comments", {"body": "Tests?"})
        self.ask("PATCH", f"/api/threads/{tid}/status", {"status": "dismissed"})

        thread = self.thread(tid)

        self.assertEqual([c["by"] for c in thread["comments"]], ["Ada", "Ada"])
        self.assertEqual(thread["statusBy"], "Ada")

    def test_with_no_name_and_no_default_a_comment_has_none(self):
        self.serve(default_reviewer=lambda root: None)
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]

        thread = self.thread(tid)

        self.assertEqual(([c["by"] for c in thread["comments"]], thread["statusBy"]), ([None], None))

    def test_a_thread_written_before_reviewer_names_shows_no_name(self):
        self.serve()
        tid = self.review.open_thread("reviewer", "Written before names").thread.id
        self.review.add_comment("agent", tid, "reply", "It is ready.")

        thread = self.thread(tid)

        self.assertEqual([c["by"] for c in thread["comments"]], [None, None])
        self.assertIsNone(thread["statusBy"])

    def test_a_reply_or_note_has_no_reviewer_name_and_gets_none_by_default(self):
        self.serve()
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]

        self.assertEqual(self.ask("POST", f"/api/threads/{tid}/comments", {"kind": "reply", "body": "Yes."})[1]["by"],
                         None)
        status, answer = self.ask("POST", f"/api/threads/{tid}/comments",
                                  {"kind": "reply", "body": "Yes.", "reviewer": "security-bot"})
        self.assertEqual((status, set(answer)), (403, {"error"}))

    def test_a_name_that_is_not_one_line_of_text_is_400(self):
        self.serve()
        tid = self.ask("POST", "/api/threads", {"body": "Is this ready?"})[1]["id"]

        for name in ("", "  ", 7, None, "two\nlines", "x" * 101):
            with self.subTest(name=name):
                for method, path, payload in (("POST", "/api/threads", {"body": "Hi"}),
                                              ("POST", f"/api/threads/{tid}/comments", {"body": "Hi"}),
                                              ("PATCH", f"/api/threads/{tid}/status", {"status": "resolved"})):
                    status, answer = self.ask(method, path, dict(payload, reviewer=name))
                    self.assertEqual((status, set(answer)), (400, {"error"}), path)
        self.assertEqual(len(self.thread(tid)["comments"]), 1)

    def test_a_name_is_kept_without_the_spaces_around_it(self):
        self.serve()

        thread = self.ask("POST", "/api/threads", {"body": "Is this ready?", "reviewer": "  security-bot "})[1]

        self.assertEqual(thread["comments"][0]["by"], "security-bot")


class StoreThatCannotWrite(MemoryStore):
    """A store on a full disk: it keeps nothing."""

    def append(self, events):
        raise CouldNotRead("could not write the review")


class SlowStore(MemoryStore):
    """A store that takes its time to load, as a big events file does: two
    requests at once would both load before either appends."""

    def load(self):
        events = super().load()
        time.sleep(0.02)
        return events


if __name__ == "__main__":
    unittest.main()
