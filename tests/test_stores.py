"""Seam 2: one test suite for every store.

Each store keeps the review's threads in difftate's own thread format, so
switching stores (and later removing diffity) is safe. The diffity store runs
against a real diffity 0.9.5 in a temporary repository, and is skipped when
diffity isn't installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate import diffity  # noqa: E402
from difftate.memory import MemoryStore  # noqa: E402
from difftate.store import StoreError  # noqa: E402

ANCHOR = {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2, "code": "    return f'hello {name}'"}


class StoreContract:
    """The behaviour every store shares. Subclasses set self.store in setUp."""

    def test_a_thread_opens_with_the_reviewers_comment(self):
        opened = self.store.open_thread(ANCHOR, "Why an f-string here?")

        [thread] = self.store.threads()
        self.assertEqual(thread, opened)
        self.assertEqual(thread["status"], "open")
        self.assertFalse(thread["outdated"])
        anchor = dict(thread["anchor"])
        self.assertIn("commit", anchor)
        del anchor["commit"]
        self.assertEqual(anchor, ANCHOR)
        [comment] = thread["comments"]
        self.assertEqual((comment["author"], comment["kind"], comment["body"]),
                         ("reviewer", "comment", "Why an f-string here?"))
        self.assertTrue(comment["id"] and comment["time"])

    def test_a_general_thread_has_no_anchor(self):
        self.store.open_thread(None, "Looks good overall.")

        [thread] = self.store.threads()
        self.assertIsNone(thread["anchor"])
        self.assertEqual(thread["comments"][0]["body"], "Looks good overall.")

    def test_each_kind_of_comment_has_its_author_and_keeps_its_body(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        added = [self.store.add_comment(tid, kind, body) for kind, body in (
            ("progress", "⏳ **Working…**"), ("reply", "It reads better."), ("comment", "OK, and the name?"),
            ("queued", "🕒 **Queued**"))]

        comments = self.store.threads()[0]["comments"]
        self.assertEqual(comments[1:], added)
        self.assertEqual([(c["author"], c["kind"], c["body"]) for c in comments], [
            ("reviewer", "comment", "Why an f-string here?"),
            ("difftate", "progress", "⏳ **Working…**"),
            ("agent", "reply", "It reads better."),
            ("reviewer", "comment", "OK, and the name?"),
            ("difftate", "queued", "🕒 **Queued**"),
        ])

    def test_a_note_is_edited_in_place_and_may_change_kind(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        note = self.store.add_comment(tid, "queued", "🕒 **Queued**")

        edited = self.store.edit_note(note["id"], "progress", "✅ **Done** in 3s")

        comments = self.store.threads()[0]["comments"]
        self.assertEqual(len(comments), 2)
        self.assertEqual(comments[1], edited)
        self.assertEqual((edited["id"], edited["kind"], edited["body"]), (note["id"], "progress", "✅ **Done** in 3s"))

    def test_status_changes_and_filters_threads(self):
        first = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        second = self.store.open_thread(dict(ANCHOR, startLine=1, endLine=1), "Rename greet?")["id"]

        self.store.set_status(first, "resolved")

        self.assertEqual([t["id"] for t in self.store.threads("open")], [second])
        self.assertEqual([(t["id"], t["status"]) for t in self.store.threads("resolved")], [(first, "resolved")])
        self.assertEqual([t["id"] for t in self.store.threads()], [first, second])

    def test_a_thread_can_be_dismissed_and_reopened(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]

        self.store.set_status(tid, "dismissed")
        self.assertEqual([t["id"] for t in self.store.threads("dismissed")], [tid])

        self.store.set_status(tid, "open")
        self.assertEqual([(t["id"], t["status"]) for t in self.store.threads("open")], [(tid, "open")])
        self.assertEqual(self.store.threads("dismissed"), [])

    def test_unknown_threads_and_notes_are_not_found(self):
        for call in (lambda: self.store.add_comment("no-such-thread", "comment", "Hello?"),
                     lambda: self.store.set_status("no-such-thread", "resolved"),
                     lambda: self.store.edit_note("no-such-note", "progress", "✅")):
            with self.assertRaises(StoreError) as refused:
                call()
            self.assertEqual(refused.exception.status, 404)


class MemoryStoreTest(StoreContract, unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(shutil.which("diffity"), "diffity 0.9.5 is not installed")
class DiffityStoreTest(StoreContract, unittest.TestCase):
    """A real diffity per test, in a temporary repository. HOME points into the
    temporary folder, so diffity's data stays there too."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="difftate-store-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.repo = os.path.join(tmp, "repo")
        home = os.path.join(tmp, "home")
        os.makedirs(self.repo)
        os.makedirs(home)
        with open(os.path.join(home, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n")
        for key, value in (("HOME", home), ("GIT_CONFIG_NOSYSTEM", "1")):
            self.addCleanup(os.environ.__setitem__, key, os.environ[key]) if key in os.environ \
                else self.addCleanup(os.environ.pop, key, None)
            os.environ[key] = value

        git(self.repo, "init", "-q", "-b", "main")
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("def greet(name):\n    return 'hi ' + name\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "first")
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("def greet(name):\n    return f'hello {name}'\n")
        self.head = git(self.repo, "rev-parse", "HEAD").strip()

        process = diffity.DiffityProcess.start("HEAD", self.repo)
        self.addCleanup(process.stop, False)
        self.store = process.store()

    def test_an_anchor_records_the_commit_it_was_written_on(self):
        self.store.open_thread(ANCHOR, "Why an f-string here?")

        self.assertEqual(self.store.threads()[0]["anchor"]["commit"], self.head)

    def test_a_reviewing_agents_comment_counts_as_the_reviewers(self):
        subprocess.run(["diffity", "agent", "comment", "--file", "app.py", "--line", "2",
                        "--body", "Missing a type hint."], cwd=self.repo, check=True, capture_output=True)

        [thread] = self.store.threads()
        self.assertEqual([(c["author"], c["kind"], c["body"]) for c in thread["comments"]],
                         [("reviewer", "comment", "Missing a type hint.")])


if __name__ == "__main__":
    unittest.main()
