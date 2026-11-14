"""Seam: the local store over its review folder (beside the store contract in
test_stores.py, which it also passes).

The review in tests/fixtures/todays-review/ was written by the old LocalStore
(local.py), with every kind of line it wrote. The same events, appended to
the local store, give the same bytes in events.jsonl; that events.jsonl
loads; and the store restores and reports lines it didn't write, as the old
one did. Every folder is a temporary one.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode  # noqa: E402
from difftate.adapters.outbound.history_files import HistoryFiles  # noqa: E402
from difftate.adapters.outbound.local_store import LocalStore  # noqa: E402
from difftate.adapters.outbound.local_store.lines import read_events  # noqa: E402
from difftate.adapters.inbound.review_api.json_format import thread_json  # noqa: E402
from difftate.core.review.model import (  # noqa: E402
    Anchor, Comment, CommentAdded, CouldNotRead, ListedThread, NotesInProgress, Review, ThreadOpened,
)
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.mark_viewed import mark_viewed  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402
from test_core_replay import TODAYS_REVIEW, as_stored, read_today, run_as_today, with_no_names  # noqa: E402

TIME = "2026-11-07T10:00:00.000Z"


def read(path):
    with open(path, "rb") as f:
        return f.read()


class TheLocalStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="difftate-local-store-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A review the old LocalStore wrote, in its own folder
        self.today_folder = os.path.join(self.tmp, "today")
        os.makedirs(self.today_folder)
        shutil.copy(os.path.join(TODAYS_REVIEW, "events.jsonl"), self.today_folder)
        self.today = read_today()
        ids = self.today["thread_ids"]
        self.threads = ids["moved"], ids["general"], ids["outdated"]
        self.today_file = os.path.join(self.today_folder, "events.jsonl")
        self.folder = os.path.join(self.tmp, "git", "difftate")
        self.warnings = []

    def open_store(self, base="main"):
        return LocalStore.open(self.folder, branch="feature", base=base, on_tamper=self.warnings.append)

    def events_file(self, store):
        return os.path.join(store.folder, "events.jsonl")

    # ── The same lines as today ──────────────────────────────────────────────
    def test_the_same_events_give_the_same_lines_as_today(self):
        today = read(self.today_file)
        events = read_events(today.decode())
        store = self.open_store()

        store.append(events[:3])
        for event in events[3:]:
            store.append([event])

        self.assertEqual(read(self.events_file(store)), today)

    def test_the_core_keeps_a_review_in_it_and_the_review_history_gets_the_same_lines(self):
        store, notes, history_folder = self.open_store(), NotesInProgress(), os.path.join(self.tmp, "history-new")
        history = HistoryFiles({"review": "r"}, history_folder)
        code = FakeCode({"app.py": "def greet(name):\n    return 'hi ' + name\n"}, diff_hashes={"app.py": "h1"})
        tid = open_thread(store, notes, code, history, "reviewer", "Why concatenate?",
                          Anchor("app.py", "new", 2, 2)).thread.id
        add_comment(store, notes, history, "difftate", tid, "progress", "Thinking…")  # not final: not kept
        add_comment(store, notes, history, "agent", tid, "reply", "It was there before.")
        set_status(store, notes, history, "reviewer", tid, "resolved")
        mark_viewed(store, code, history, "app.py")

        [(thread, state, _)] = list_threads(self.open_store(), NotesInProgress(), code)
        self.assertEqual([(c.kind, c.body) for c in thread.comments],
                         [("comment", "Why concatenate?"), ("reply", "It was there before.")])
        self.assertEqual((thread.status, thread.anchor.code, state), ("resolved", "    return 'hi ' + name", None))
        stored = [json.loads(line) for line in read(self.events_file(store)).splitlines()]
        [month] = os.listdir(history_folder)
        with open(os.path.join(history_folder, month)) as f:
            self.assertEqual([json.loads(line) for line in f], [dict(line, review="r") for line in stored])
        self.assertEqual([line["type"] for line in stored], ["opened", "comment", "comment", "status", "viewed"])

    # ── Existing reviews load ────────────────────────────────────────────────
    def test_an_events_file_written_today_loads(self):
        store = LocalStore(self.today_folder)
        review = Review.from_events(store.load())

        self.assertEqual([as_stored(thread_json(ListedThread(t, None))) for t in review.threads()],
                         with_no_names(self.today["threads"]))
        self.assertEqual([run_as_today(r) for r in review.runs()], self.today["runs"])
        self.assertEqual(review.viewed(), self.today["viewed"])

    def test_a_review_written_today_goes_on_in_the_new_store(self):
        moved = self.threads[0]
        reply = Comment("r9", "agent", "reply", "Done.", TIME, 99)
        before = read(self.today_file)
        LocalStore(self.today_folder).append([CommentAdded(moved, reply)])

        self.assertTrue(read(self.today_file).startswith(before), "only appended")
        reopened = Review.from_events(LocalStore(self.today_folder).load())
        self.assertEqual(reopened.thread(moved).comments[-1], reply)

    def test_a_line_that_holds_no_event_is_skipped(self):
        with open(self.today_file, "a") as f:
            f.write('{"type": "comment", "thread": "x"\n')  # cut short
        self.assertEqual(LocalStore(self.today_folder).load(), read_events(read(self.today_file).decode()))

    # ── The review's folder ──────────────────────────────────────────────────
    def test_the_review_is_one_branch_against_its_base(self):
        store = self.open_store()

        review = store.review()
        self.assertEqual((review["branch"], review["base"]), ("feature", "main"))
        with open(os.path.join(store.folder, "review.json")) as f:
            self.assertEqual({k: v for k, v in json.load(f).items() if k != "started"}, review)
        self.assertEqual(self.open_store().review(), review, "reused")
        self.assertNotEqual(self.open_store(base="develop").review()["id"], review["id"],
                            "another base is another review")

    def test_the_reviews_it_keeps_are_the_review_folders_there(self):
        self.assertEqual(LocalStore.review_ids(self.folder), [], "none yet")
        main, develop = self.open_store().review()["id"], self.open_store(base="develop").review()["id"]

        self.assertEqual(sorted(LocalStore.review_ids(self.folder)), sorted([main, develop]))

        shutil.rmtree(os.path.join(self.folder, "reviews", develop))
        self.assertEqual(LocalStore.review_ids(self.folder), [main])

    def test_lines_are_only_appended(self):
        store = self.open_store()
        store.append([ThreadOpened("t1", None, TIME)])
        before = read(self.events_file(store))

        store.append([CommentAdded("t1", Comment("c1", "reviewer", "comment", "Hi", TIME, 1))])

        self.assertTrue(read(self.events_file(store)).startswith(before))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_a_review_it_cannot_write_is_not_kept(self):
        store = self.open_store()
        os.chmod(store.folder, 0o500)
        self.addCleanup(os.chmod, store.folder, 0o700)

        with self.assertRaises(CouldNotRead):
            store.append([ThreadOpened("t1", None, TIME)])
        self.assertEqual(store.load(), [])

    # ── Lines it didn't write ────────────────────────────────────────────────
    def test_lines_the_store_didnt_write_are_restored_and_reported(self):
        shutil.copytree(self.today_folder, os.path.join(self.folder, "copy"))
        store = LocalStore(os.path.join(self.folder, "copy"), on_tamper=self.warnings.append)
        events = store.load()
        kept = read(self.events_file(store))
        moved, general, outdated = self.threads

        # An edit (a comment changed by hand) and an appended line (a forged reply)
        text = kept.decode().replace('"Why an f-string?"', '"Fine."')
        text += json.dumps({"type": "comment", "thread": general, "id": "x", "author": "agent", "kind": "reply",
                            "body": "Forged.", "time": TIME, "seq": 99}) + "\n"
        with open(self.events_file(store), "w") as f:
            f.write(text)

        self.assertEqual(store.load(), events)
        self.assertEqual(read(self.events_file(store)), kept)
        self.assertEqual(self.warnings, [sorted([moved, general])])
        store.load()
        self.assertEqual(len(self.warnings), 1, "reported once")

    def test_a_line_appended_by_another_is_restored_before_the_stores_own(self):
        store = self.open_store()
        store.append([ThreadOpened("t1", None, TIME)])
        with open(self.events_file(store), "a") as f:
            f.write(json.dumps({"type": "status", "thread": "t1", "status": "resolved", "time": TIME}) + "\n")

        store.append([CommentAdded("t1", Comment("c1", "reviewer", "comment", "Hi", TIME, 1))])

        self.assertEqual(self.warnings, [["t1"]])
        self.assertEqual(read_events(read(self.events_file(store)).decode()), store.load())
        self.assertEqual([type(e).__name__ for e in store.load()], ["ThreadOpened", "CommentAdded"])

    def test_a_deleted_events_file_is_restored(self):
        store = self.open_store()
        store.append([ThreadOpened("t1", None, TIME)])
        kept = read(self.events_file(store))
        os.remove(self.events_file(store))

        self.assertEqual(store.load(), [ThreadOpened("t1", None, TIME)])
        self.assertEqual(read(self.events_file(store)), kept)
        self.assertEqual(self.warnings, [["t1"]])

    def test_a_file_touched_but_unchanged_is_not_reported(self):
        store = self.open_store()
        store.append([ThreadOpened("t1", None, TIME)])
        st = os.stat(self.events_file(store))
        os.utime(self.events_file(store), ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))

        store.load()

        self.assertEqual(self.warnings, [])


if __name__ == "__main__":
    unittest.main()
