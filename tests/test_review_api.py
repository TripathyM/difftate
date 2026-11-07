"""Seam: the review API, difftate's published language, over HTTP.

A scripted review goes through every route: the review, the view, the
changeset in each view, threads (opened, listed by status and in each view,
moved with their code and outdated), comments, replies and notes, thread
status, viewed files, the thread states a run gives, the review while another
branch is checked out, and the errors each route answers. Each answer (status
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
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory, UnreadableCode  # noqa: E402
from difftate.adapters.inbound.review_api import ReviewApi, ShownView  # noqa: E402
from difftate.adapters.outbound import git  # noqa: E402
from difftate.adapters.outbound.history_files import HistoryFiles  # noqa: E402
from difftate.adapters.outbound.local_store import LocalStore  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import CouldNotRead, NotFound  # noqa: E402
from difftate.watcher import bind_review  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "review_api_script.json")
LONG = "".join(f"line_{n} = {n}\n" for n in range(1, 21))


def serve(repo, folder, history):
    """The review API on the review of "feature" against "main" in <repo>, and
    what Dispatch does to that review (runs, threads moving with their code).
    The one place this test knows how the API is built: as the watcher builds
    it, over the local store, the review history files and git."""
    store = LocalStore.open(folder, "feature", "main")
    about = store.review()
    review = bind_review(store, git.GitCodeReader(repo, "main", "feature"),
                         HistoryFiles({"review": about["id"]}, history), about)
    shown = ShownView("", lambda view: git.need_view(repo, view))
    api = ReviewApi(review, folder, repo, shown)

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


def ask(api, method, path, payload=None, token=True, body=None):
    """Call the review API as a viewer would: (status, the JSON answer)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {api.token}"
    data = body if body is not None else (None if payload is None else json.dumps(payload).encode())
    req = urllib.request.Request(api.address().url + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        with e:
            return e.code, json.loads(e.read() or b"null")


# ── Naming what differs from run to run ──────────────────────────────────────
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HASH = re.compile(r"\b[0-9a-f]{40}\b")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
INDEX = re.compile(r"^index [0-9a-f]+\.\.[0-9a-f]+", re.M)


class Names:
    """Each id and hash named by its first appearance: <id-1>, <hash-1>, …"""

    def __init__(self):
        self.seen = {}

    def _name(self, kind, found):
        return self.seen.setdefault(found, f"<{kind}-{sum(1 for v in self.seen.values() if v.startswith('<' + kind)) + 1}>")

    def text(self, s):
        s = INDEX.sub("index <blob>..<blob>", s)
        s = UUID.sub(lambda m: self._name("id", m[0]), s)
        s = HASH.sub(lambda m: self._name("hash", m[0]), s)
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
        self.names = Names()
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
        for refused in ({"view": "nope"}, {"view": 5}, {"view": "", "open": "elsewhere"}):
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


class TheReviewApiOnFakes(unittest.TestCase):
    """The review API on the use cases as the watcher binds them, over the
    memory store and a fake code reader."""

    def serve(self, store=None, code=None, view=""):
        tmp = tempfile.mkdtemp(prefix="difftate-review-api-fakes-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.review = bind_review(store or MemoryStore(), code or FakeCode({"app.py": "x = 1\n"}),
                                  FakeHistory(), {"id": "r", "branch": "feature", "base": "main"})
        self.api = ReviewApi(self.review, tmp, tmp, ShownView(view, a_fake_view))
        self.api.start()
        self.addCleanup(self.api.stop)

    def ask(self, *args, **kwargs):
        return ask(self.api, *args, **kwargs)

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
