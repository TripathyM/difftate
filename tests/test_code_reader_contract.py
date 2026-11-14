"""Seam: one contract for every code reader behind the port for reading the
code (ForReadingTheCode, ADR 0003).

A code reader hands the core plain data about the review's code: snapshots,
the files now, the hunks between two of them, the code on some lines, the
checked-out branch, the changeset and its diff hashes. It decides nothing.
The git adapter (in a temporary repository) and the fake code reader (tests)
run the same suite, on the review of the branch "feature" against "main".
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from core_fakes import FakeCode  # noqa: E402
from difftate.adapters.outbound.git import GitCodeReader, forget_kept_snapshots  # noqa: E402
from difftate.core.changes.model import FileInView, Hunk  # noqa: E402
from difftate.core.review.model import NotFound  # noqa: E402

BASE = "def greet(name):\n    return 'hi ' + name\n"
LONG = "".join(f"line_{n} = {n}\n" for n in range(1, 21))
NEW = FileInView("long.py", "new")
# An id no code reader gave: a snapshot that is gone (git gc)
LOST = "0123456789abcdef0123456789abcdef01234567"
REVIEW = "feature-1a2b3c4d"  # the review's id


class CodeReaderContract:
    """What every code reader does. A subclass sets self.code in setUp, on a
    review where the branch changed app.py from BASE and added long.py (LONG),
    and gives the helpers below."""

    def write(self, file, text):
        raise NotImplementedError

    def remove(self, file):
        raise NotImplementedError

    def commit(self):
        raise NotImplementedError

    def check_out_another_branch(self):
        """Check out "other", with the same files."""
        raise NotImplementedError

    def collect_garbage(self):
        """What git gc --prune=now does: lose every file nothing keeps."""
        raise NotImplementedError

    def now(self, place=NEW):
        return self.code.versions([place])[place]

    # ── Snapshots ────────────────────────────────────────────────────────────
    def test_a_snapshot_keeps_the_file_and_the_code_on_its_lines(self):
        snapshot = self.code.snapshot("long.py", "new", "", 12, 13)

        self.assertEqual(snapshot.code, "line_12 = 12\nline_13 = 13")
        self.assertTrue(snapshot.id)
        self.assertTrue(snapshot.commit)

    def test_a_snapshot_on_the_old_side_is_the_file_where_the_branch_left_the_base(self):
        self.assertEqual(self.code.snapshot("app.py", "old", "", 2, 2).code, "    return 'hi ' + name")

    def test_a_snapshot_of_lines_or_a_file_that_isnt_there_has_no_code(self):
        past_the_end = self.code.snapshot("long.py", "new", "", 20, 21)
        self.assertTrue(past_the_end.id)
        self.assertIsNone(past_the_end.code)

        no_file = self.code.snapshot("gone.py", "new", "", 1, 1)
        self.assertIsNone(no_file.id)
        self.assertIsNone(no_file.code)

    # ── Keeping snapshots ────────────────────────────────────────────────────
    def test_a_kept_snapshot_outlasts_garbage_collection(self):
        snapshot = self.code.snapshot("long.py", "new", "", 12, 12).id
        self.code.keep([snapshot])
        self.write("long.py", "import os\n" + LONG)

        self.collect_garbage()

        self.assertEqual(self.code.hunks(snapshot, self.now()), [Hunk(0, 0, 1, 1)])

    def test_a_snapshot_kept_once_stays_kept_when_it_isnt_asked_for_again(self):
        before = self.code.snapshot("long.py", "new", "", 12, 12).id
        self.code.keep([before])
        self.write("long.py", "import os\n" + LONG)
        after = self.code.snapshot("long.py", "new", "", 13, 13).id
        self.code.keep([after])

        self.collect_garbage()

        self.assertEqual(self.code.hunks(before, after), [Hunk(0, 0, 1, 1)])

    def test_a_snapshot_never_kept_is_lost_to_garbage_collection(self):
        snapshot = self.code.snapshot("long.py", "new", "", 12, 12).id
        self.write("long.py", "import os\n" + LONG)

        self.collect_garbage()

        self.assertIsNone(self.code.hunks(snapshot, self.now()))

    # ── The files now ────────────────────────────────────────────────────────
    def test_a_file_that_didnt_change_is_its_snapshot(self):
        snapshot = self.code.snapshot("long.py", "new", "", 12, 12)

        self.assertEqual(self.now(), snapshot.id)

    def test_an_edited_file_is_another_one_and_a_removed_file_is_none(self):
        before = self.now()
        self.write("long.py", "import os\n" + LONG)
        edited = self.now()
        self.assertNotIn(edited, (None, before))

        self.remove("long.py")
        self.assertIsNone(self.now())

    def test_each_file_asked_for_is_given(self):
        old, new = FileInView("app.py", "old"), FileInView("app.py", "new")
        self.write("long.py", "import os\n" + LONG)

        now = self.code.versions([old, new, NEW])

        self.assertEqual(set(now), {old, new, NEW})
        self.assertEqual(now[old], self.code.snapshot("app.py", "old", "", 1, 1).id)
        self.assertNotEqual(now[old], now[new])

    # ── Hunks and the code on some lines ─────────────────────────────────────
    def test_hunks_are_the_diff_with_no_context_lines(self):
        snapshot = self.code.snapshot("long.py", "new", "", 12, 12).id
        self.write("long.py", "import os\nimport re\n" + LONG.replace("line_13 = 13", "line_13 = 'thirteen'"))

        self.assertEqual(self.code.hunks(snapshot, self.now()), [Hunk(0, 0, 1, 2), Hunk(13, 1, 15, 1)])

    def test_a_file_and_itself_have_no_hunks(self):
        self.assertEqual(self.code.hunks(self.now(), self.now()), [])

    def test_a_lost_snapshot_has_no_hunks(self):
        self.assertIsNone(self.code.hunks(LOST, self.now()))

    def test_the_code_on_some_lines_of_a_file(self):
        self.assertEqual(self.code.code_on_lines(self.now(), 2, 3), "line_2 = 2\nline_3 = 3")
        self.assertIsNone(self.code.code_on_lines(self.now(), 20, 21))

    # ── The checked-out branch ───────────────────────────────────────────────
    def test_the_reviews_branch_is_checked_out_until_another_one_is(self):
        self.assertTrue(self.code.on_branch())
        self.assertEqual(self.code.checked_out_branch(), "feature")

        self.check_out_another_branch()

        self.assertFalse(self.code.on_branch())
        self.assertEqual(self.code.checked_out_branch(), "other")

    # ── The changeset and its diff hashes ────────────────────────────────────
    def test_the_changeset_has_each_changed_file(self):
        changeset = self.code.changeset("")

        self.assertEqual((changeset.view, changeset.base), ("", "main"))
        self.assertTrue(changeset.commit)
        self.assertIn("long.py", changeset.diff)
        self.assertIn("app.py", changeset.diff)

    def test_each_version_the_changeset_shows_can_be_read_after_the_file_changes_again(self):
        self.write("app.py", BASE.replace("'hi ' + name", "'hey ' + name"))  # on disk, never read before
        versions = self.code.changeset("").versions
        self.write("app.py", BASE)

        self.assertEqual(set(versions), {"app.py", "long.py"})
        self.assertEqual(self.code.code_on_lines(versions["app.py"].new, 2, 2), "    return 'hey ' + name")
        self.assertEqual(self.code.code_on_lines(versions["app.py"].old, 2, 2), "    return 'hi ' + name")
        self.assertEqual(self.code.code_on_lines(versions["long.py"].new, 20, 20), "line_20 = 20")
        self.assertIsNone(versions["long.py"].old, "a new file has no old side")

    def test_a_view_that_names_no_commit_is_not_found(self):
        with self.assertRaises(NotFound):
            self.code.changeset("no-such-commit")

    def test_each_changed_file_has_a_diff_hash_that_an_edit_changes_and_a_commit_doesnt(self):
        hashes = self.code.diff_hashes()
        self.assertEqual(set(hashes), {"app.py", "long.py"})

        self.commit()
        self.assertEqual(self.code.diff_hashes(), hashes)

        self.write("long.py", LONG.replace("line_3 = 3", "line_3 = 'three'"))
        after = self.code.diff_hashes()
        self.assertNotEqual(after["long.py"], hashes["long.py"])
        self.assertEqual(after["app.py"], hashes["app.py"])


class TheFakeCodeReader(CodeReaderContract, unittest.TestCase):
    def setUp(self):
        self.code = FakeCode({"app.py": BASE.replace("'hi ' + name", "f'hello {name}'"), "long.py": LONG},
                             base={"app.py": BASE})

    def write(self, file, text):
        self.code.files[file] = text

    def remove(self, file):
        del self.code.files[file]

    def commit(self):
        self.code.commit = self.code.commit + "+"

    def check_out_another_branch(self):
        self.code.checked_out = False

    def collect_garbage(self):
        self.code.collect_garbage()


class InAGitRepository:
    """The review in a temporary git repository, read by the git adapter."""

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="difftate-git-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.repo = os.path.join(tmp, "repo")
        os.makedirs(self.repo)
        with open(os.path.join(tmp, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Test\n\temail = test@example.com\n")
        # Git reads its config from here only: no signing, no hooks
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=tmp, GIT_CONFIG_NOSYSTEM="1", XDG_CONFIG_HOME=os.path.join(tmp, "xdg"))
        self.git("init", "-q", "-b", "main")
        self.write("app.py", BASE)
        self.commit()
        self.git("checkout", "-q", "-b", "feature")
        self.write("app.py", BASE.replace("'hi ' + name", "f'hello {name}'"))
        self.write("long.py", LONG)
        # The adapter runs git as difftate does, with the process's environment
        patched = mock.patch.dict(os.environ, self.env, clear=True)
        patched.start()
        self.addCleanup(patched.stop)
        self.code = GitCodeReader(self.repo, "main", "feature", REVIEW)

    def git(self, *args):
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, env=self.env)

    def output(self, *args):
        """git's output, stripped."""
        return subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout.strip()

    def write(self, file, text):
        with open(os.path.join(self.repo, file), "w") as f:
            f.write(text)

    def remove(self, file):
        os.remove(os.path.join(self.repo, file))

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a commit")

    def check_out_another_branch(self):
        self.git("checkout", "-q", "-b", "other")

    def collect_garbage(self):
        self.git("gc", "-q", "--prune=now")

    def git_out(self, *args, cwd=None):
        return subprocess.run(["git", "-C", cwd or self.repo, *args], check=True, capture_output=True, text=True,
                              env=self.env).stdout.split()


class TheGitAdapter(InAGitRepository, CodeReaderContract, unittest.TestCase):
    def test_an_id_a_viewer_sent_that_is_no_blob_id_is_no_file_and_never_an_option_to_git(self):
        out = os.path.join(self.repo, "written")
        for sent in (f"--output={out}", "HEAD", "-p"):
            with self.subTest(sent=sent):
                self.assertIsNone(self.code.code_on_lines(sent, 1, 1))
                self.assertIsNone(self.code.hunks(sent, self.now()))
                self.assertIsNone(self.code.hunks(self.now(), sent))
        self.assertFalse(os.path.exists(out))


class TheGitAdapterInEachView(InAGitRepository, unittest.TestCase):
    """Only git has views: the fake shows all changes in every view. Each view
    compares two versions of a file: a commit, HEAD and the index (staged),
    the index and the files on disk (unstaged)."""

    def test_the_old_side_of_a_commit_view_is_that_commit_and_the_new_side_is_on_disk(self):
        self.commit()
        self.write("long.py", LONG.replace("line_3 = 3", "line_3 = 'three'"))

        self.assertEqual(self.code.snapshot("long.py", "old", "HEAD", 3, 3).code, "line_3 = 3")
        self.assertEqual(self.code.snapshot("long.py", "new", "HEAD", 3, 3).code, "line_3 = 'three'")
        self.assertIsNone(self.code.snapshot("long.py", "old", "HEAD~1", 3, 3).id, "not in the base")

    def test_staged_is_head_against_the_index_and_unstaged_the_index_against_the_files_on_disk(self):
        self.commit()
        self.write("long.py", LONG.replace("line_3 = 3", "line_3 = 'three'"))
        self.git("add", "long.py")
        self.write("long.py", LONG.replace("line_3 = 3", "line_3 = 'THREE!'"))

        def code(side, view):
            return self.code.snapshot("long.py", side, view, 3, 3).code
        self.assertEqual((code("old", "staged"), code("new", "staged")), ("line_3 = 3", "line_3 = 'three'"))
        self.assertEqual((code("old", "unstaged"), code("new", "unstaged")), ("line_3 = 'three'", "line_3 = 'THREE!'"))
        self.assertIn("+line_3 = 'three'", self.code.changeset("staged").diff)
        self.assertNotIn("THREE", self.code.changeset("staged").diff)
        self.assertIn("+line_3 = 'THREE!'", self.code.changeset("unstaged").diff)

    def test_a_same_size_edit_in_the_second_the_index_was_written_is_in_the_changeset(self):
        # Git trusts an index entry whose file times and size match, unless the
        # entry is as new as the index file itself (racily clean). A copy of the
        # index must keep its times, or git trusts the stale entry.
        self.git("config", "core.trustctime", "false")  # ctime can't be set; mtime stands for both
        self.commit()
        path = os.path.join(self.repo, "long.py")
        index_written_at = 1_700_000_000

        def write_in_that_second(text):
            self.write("long.py", text)
            os.utime(path, (index_written_at, index_written_at))
        write_in_that_second(LONG.replace("line_3 = 3", "line_3 = 'a'"))
        self.git("add", "long.py")
        os.utime(os.path.join(self.repo, self.output("rev-parse", "--git-path", "index")), (index_written_at, index_written_at))
        write_in_that_second(LONG.replace("line_3 = 3", "line_3 = 'b'"))  # the same size

        # A stale entry names the old blob in all changes, and hides the edit from unstaged
        self.assertIn(".." + self.output("hash-object", "long.py")[:7], self.code.changeset("").diff)
        self.assertIn("+line_3 = 'b'", self.code.changeset("unstaged").diff)

    def test_a_thread_on_the_old_side_of_a_commit_view_has_its_file_in_that_view(self):
        self.commit()
        snapshot = self.code.snapshot("long.py", "old", "HEAD", 12, 12)
        self.write("long.py", "import os\n" + LONG)

        old_side = FileInView("long.py", "old", "HEAD")
        self.assertEqual(self.code.versions([old_side])[old_side], snapshot.id, "an edit on disk isn't in HEAD")

    def test_where_the_branch_left_the_base_unknown_leaves_out_the_old_side_of_all_changes(self):
        code = GitCodeReader(self.repo, "no-such-base", "feature", REVIEW)
        old, new, in_head = FileInView("app.py", "old"), FileInView("app.py", "new"), FileInView("app.py", "old", "HEAD")

        self.assertEqual(set(code.versions([old, new, in_head])), {new, in_head})


class TheGitAdapterKeepingSnapshots(InAGitRepository, unittest.TestCase):
    """git keeps the snapshots reachable from a ref of difftate's own,
    refs/difftate/<review id>, so git gc can't prune them. The ref names a
    tree, not a commit: nothing to sign, and git log --all doesn't show it."""
    REF = f"refs/difftate/{REVIEW}"

    def kept(self):
        """{each object in the review's ref: its type}."""
        rows = self.git_out("ls-tree", self.REF)  # <mode> <type> <id>\t<name>, one after the other
        return {rows[i + 2]: rows[i + 1] for i in range(0, len(rows), 4)}

    def test_the_reviews_ref_holds_only_snapshot_blobs_and_never_lets_one_go(self):
        self.code.keep([])
        self.assertEqual(self.git_out("for-each-ref", "refs/difftate/"), [], "nothing to keep: no ref")
        app = self.code.snapshot("app.py", "new", "", 2, 2).id
        long = self.code.snapshot("long.py", "new", "", 12, 12).id

        self.code.keep([app])
        self.code.keep([long])
        self.assertEqual(self.kept(), {app: "blob", long: "blob"})

        self.code.keep([])
        self.assertEqual(self.kept(), {app: "blob", long: "blob"})

    def test_another_reader_of_the_same_review_adds_to_its_ref(self):
        app = self.code.snapshot("app.py", "new", "", 2, 2).id
        self.code.keep([app])
        again = GitCodeReader(self.repo, "main", "feature", REVIEW)  # the watcher started again, say
        long = again.snapshot("long.py", "new", "", 12, 12).id

        again.keep([long])

        self.assertEqual(self.kept(), {app: "blob", long: "blob"})

    def test_a_snapshot_already_lost_is_left_out(self):
        long = self.code.snapshot("long.py", "new", "", 12, 12).id

        self.code.keep([LOST, long])

        self.assertEqual(self.kept(), {long: "blob"})
        self.git("fsck", "--strict")

    def test_a_plain_git_push_doesnt_send_the_ref(self):
        remote = os.path.join(os.path.dirname(self.repo), "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", remote], check=True, capture_output=True, env=self.env)
        self.git("remote", "add", "origin", remote)
        self.commit()
        self.code.keep([self.code.snapshot("long.py", "new", "", 12, 12).id])

        self.git("push", "-q", "-u", "origin", "feature")
        self.git("push", "-q")
        self.git("push", "-q", "--all")
        self.git("push", "-q", "--tags")

        self.assertEqual([r for r in self.git_out("ls-remote", remote) if "difftate" in r], [])

    def test_a_ref_removed_by_someone_else_is_written_again(self):
        long = self.code.snapshot("long.py", "new", "", 12, 12).id
        self.code.keep([long])
        self.git("update-ref", "-d", self.REF)

        self.code.keep([long])

        self.assertEqual(self.kept(), {long: "blob"})

    def test_the_refs_of_reviews_that_are_gone_are_dropped(self):
        other = GitCodeReader(self.repo, "main", "other-branch", "other-5e6f7a8b")
        self.code.keep([self.code.snapshot("long.py", "new", "", 12, 12).id])
        other.keep([other.snapshot("app.py", "new", "", 2, 2).id])

        forget_kept_snapshots(self.repo, reviews=[REVIEW])

        self.assertEqual(self.git_out("for-each-ref", "--format=%(refname)", "refs/difftate/"), [self.REF])


if __name__ == "__main__":
    unittest.main()
