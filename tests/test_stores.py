"""Seam 2: one test suite for every store.

Each store keeps the review's threads in difftate's own thread format, so
switching stores (and later removing diffity) is safe. The diffity store runs
against a real diffity 0.9.5 in a temporary repository, and is skipped when
diffity isn't installed.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate import diffity  # noqa: E402
from difftate.local import LocalStore  # noqa: E402
from difftate.memory import MemoryStore  # noqa: E402
from difftate.store import StoreError  # noqa: E402

ANCHOR = {"file": "app.py", "side": "new", "startLine": 2, "endLine": 2, "code": "    return f'hello {name}'"}


class StoreContract:
    """The behaviour every store shares. Subclasses set self.store in setUp."""
    KEEPS_RUNS = True  # diffity has no place for runs
    FOLLOWS_CODE = True  # diffity's threads never move and are never outdated

    def test_a_thread_moves_with_its_code_and_stays_outdated_once_it_changed(self):
        tid = self.store.open_thread(dict(ANCHOR, snapshot="a" * 40), "Why an f-string here?")["id"]

        self.store.move_thread(tid, 5, 6, "b" * 40)
        moved = self.store.threads()[0]
        self.store.mark_outdated(tid)
        [outdated] = self.store.threads()

        if not self.FOLLOWS_CODE:
            self.assertEqual((outdated["anchor"]["startLine"], outdated["outdated"]), (2, False))
            return
        self.assertEqual({k: moved["anchor"][k] for k in ("startLine", "endLine", "code", "snapshot")},
                         {"startLine": 5, "endLine": 6, "code": ANCHOR["code"], "snapshot": "b" * 40})
        self.assertFalse(moved["outdated"])
        self.assertTrue(outdated["outdated"])
        self.assertEqual(outdated["anchor"], moved["anchor"], "an outdated thread keeps its anchor")

    def test_a_run_is_kept_with_what_it_was_sent_until_it_ends(self):
        if not self.KEEPS_RUNS:
            self.assertIsNone(self.store.runs())
            return
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        comment = self.store.threads()[0]["comments"][0]["id"]
        run = {"id": "run-1", "threads": [tid], "sent": [comment], "repliesBefore": {tid: []}}

        self.store.record_run(run)
        self.assertEqual(self.store.runs(), [dict(run, outcome=None)])

        self.store.record_run_end("run-1", "done")
        self.assertEqual(self.store.runs(), [dict(run, outcome="done")])

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


def temp_repo(test):
    """A git repository with one commit, in a temporary folder the test removes."""
    tmp = tempfile.mkdtemp(prefix="difftate-store-test-")
    test.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write("def greet(name):\n    return 'hi ' + name\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "first")
    return tmp, repo


class LocalStoreTest(StoreContract, unittest.TestCase):
    """difftate's own store, in a temporary repository's git folder, with its
    review history in a temporary home folder."""

    def setUp(self):
        self.tmp, self.repo = temp_repo(self)
        self.folder = os.path.join(self.repo, ".git", "difftate")
        self.history = os.path.join(self.tmp, "home", ".difftate", "history")
        self.warnings = []
        self.store = self.open_store()

    def open_store(self):
        return LocalStore.open(self.folder, self.repo, branch="feature", base="main", history=self.history,
                               on_tamper=self.warnings.append)

    def events_file(self):
        [review] = os.listdir(os.path.join(self.folder, "reviews"))
        return os.path.join(self.folder, "reviews", review, "events.jsonl")

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def history_lines(self):
        lines = []
        for name in sorted(os.listdir(self.history)):
            with open(os.path.join(self.history, name)) as f:
                lines += [json.loads(line) for line in f]
        return lines

    def test_the_review_is_one_branch_against_its_base(self):
        review = self.store.review()

        self.assertEqual((review["branch"], review["base"]), ("feature", "main"))
        self.assertEqual(self.open_store().review()["id"], review["id"], "reused")
        other = LocalStore.open(self.folder, self.repo, branch="feature", base="develop", history=self.history)
        self.assertNotEqual(other.review()["id"], review["id"], "another base is another review")

    def test_the_review_is_kept_and_read_back_in_order(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        self.store.add_comment(tid, "reply", "It reads better.")
        self.store.set_status(tid, "resolved")
        self.store.move_thread(tid, 5, 5, "b" * 40)
        self.store.mark_outdated(tid)

        [thread] = self.open_store().threads()
        self.assertEqual(thread, self.store.threads()[0])
        self.assertEqual(thread["status"], "resolved")
        self.assertEqual((thread["anchor"]["startLine"], thread["anchor"]["snapshot"], thread["outdated"]),
                         (5, "b" * 40, True))
        self.assertEqual(thread["anchor"]["commit"], git(self.repo, "rev-parse", "HEAD").strip())

    def test_runs_are_kept(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        self.store.record_run({"id": "run-1", "threads": [tid], "sent": ["c1"], "repliesBefore": {tid: []}})
        self.store.record_run_end("run-1", "stopped")
        self.store.record_run({"id": "run-2", "threads": [tid], "sent": ["c2"], "repliesBefore": {tid: ["r1"]}})

        self.assertEqual([(r["id"], r["outcome"]) for r in self.open_store().runs()],
                         [("run-1", "stopped"), ("run-2", None)])
        self.assertEqual(self.open_store().runs(), self.store.runs())

    def test_a_note_is_kept_only_when_final_and_keeps_its_place(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        note = self.store.add_comment(tid, "progress", "⏳ **Working…**")
        self.store.add_comment(tid, "reply", "It reads better.")
        queued = self.store.add_comment(tid, "queued", "🕒 **Queued**")
        self.assertEqual([c["kind"] for c in self.open_store().threads()[0]["comments"]], ["comment", "reply"],
                         "live notes are not stored")

        self.store.edit_note(note["id"], "progress", "✅ **Done** in 3s", final=True)

        comments = self.open_store().threads()[0]["comments"]
        self.assertEqual([(c["kind"], c["body"]) for c in comments], [
            ("comment", "Why an f-string here?"), ("progress", "✅ **Done** in 3s"), ("reply", "It reads better.")])
        self.assertNotIn(queued["id"], [c["id"] for c in comments])

    def test_stored_lines_are_only_appended_and_go_to_the_review_history_too(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        before = self.read(self.events_file())
        note = self.store.add_comment(tid, "progress", "⏳ **Working…**")
        self.store.edit_note(note["id"], "progress", "✅ **Done** in 3s", final=True)
        self.store.add_comment(tid, "reply", "It reads better.")
        self.store.set_status(tid, "resolved")

        after = self.read(self.events_file())
        self.assertTrue(after.startswith(before), "only appended")
        stored = [json.loads(line) for line in after.decode().splitlines()]
        self.assertEqual([e["type"] for e in stored], ["opened", "comment", "note", "comment", "status"])
        history = self.history_lines()
        self.assertEqual(len(history), len(stored))
        for line, kept in zip(stored, history):
            self.assertEqual({k: v for k, v in kept.items() if k in line}, line)
            self.assertEqual(kept["branch"], "feature")
            self.assertEqual(kept["base"], "main")
            self.assertEqual(kept["repo"]["path"], os.path.realpath(self.repo))

    def test_lines_the_store_didnt_write_are_restored_and_reported(self):
        tid = self.store.open_thread(ANCHOR, "Why an f-string here?")["id"]
        other = self.store.open_thread(ANCHOR, "And the name?")["id"]
        kept = self.read(self.events_file())

        # An edit (the thread resolved by hand) and an appended line (a forged reply)
        text = kept.decode().replace('"Why an f-string here?"', '"Fine."')
        text += json.dumps({"type": "comment", "thread": other, "id": "x", "author": "agent", "kind": "reply",
                            "body": "Forged.", "time": "2026-01-01T00:00:00.000Z", "seq": 99}) + "\n"
        with open(self.events_file(), "w") as f:
            f.write(text)

        threads = self.store.threads()
        self.assertEqual(self.read(self.events_file()), kept)
        self.assertEqual(self.warnings, [sorted([tid, other])])
        self.assertEqual([c["body"] for t in threads for c in t["comments"]], ["Why an f-string here?", "And the name?"])
        self.store.threads()
        self.assertEqual(len(self.warnings), 1, "reported once")


@unittest.skipUnless(shutil.which("diffity"), "diffity 0.9.5 is not installed")
class DiffityStoreTest(StoreContract, unittest.TestCase):
    """A real diffity per test, in a temporary repository. HOME points into the
    temporary folder, so diffity's data stays there too."""
    KEEPS_RUNS = False
    FOLLOWS_CODE = False

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
