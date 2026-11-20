"""Seam: the Neovim viewer (GLOSSARY.md), driven as the reviewer drives it.

Each test starts the real watcher with the fake agent in a temporary git
repository on the branch "feature" (test_watcher.Harness), then a headless
Neovim in that folder with only the plugin (and gitsigns) loaded, from
tests/nvim/init.lua: never the reviewer's config or data, as HOME and every
XDG folder point into the temporary folder. The test runs commands and presses
keys in that Neovim through its --listen socket, and checks what the reviewer
would see: gitsigns' base and hunks, the plugin's messages and its status note.

Needs `nvim` (0.10 or later) on PATH, and DIFFTATE_TEST_GITSIGNS naming a
gitsigns.nvim checkout for the tests that check gitsigns; they skip without.
With DIFFTATE_TEST_NVIM_REQUIRED=1 (CI's Neovim job) they fail instead.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_watcher import Harness, git, wait_for  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join(ROOT, "tests", "nvim", "init.lua")
NVIM = shutil.which("nvim")
GITSIGNS = os.environ.get("DIFFTATE_TEST_GITSIGNS", "")
REQUIRED = os.environ.get("DIFFTATE_TEST_NVIM_REQUIRED") == "1"


def xdg_folders(folder):
    """Every XDG folder Neovim reads or writes, in <folder>."""
    return {f"XDG_{name.upper()}_HOME": os.path.join(folder, name) for name in ("config", "data", "state", "cache")}


def nvim_missing():
    """Why the Neovim viewer can't be tested here, or None."""
    if not NVIM:
        return "nvim is not on PATH: install Neovim 0.10 or later to test the Neovim viewer"
    with tempfile.TemporaryDirectory(prefix="difftate-nvim-") as tmp:
        # Neovim's own folders in <tmp>: its log never goes to the reviewer's ~/.local/state
        env = dict(os.environ, HOME=tmp, **xdg_folders(tmp))
        out = subprocess.run([NVIM, "--clean", "--headless", "-c", "lua io.write(vim.fn.has('nvim-0.10'))",
                              "-c", "qa!"], cwd=tmp, env=env, capture_output=True, text=True, timeout=30).stdout
    return None if out.strip() == "1" else "nvim is older than 0.10: the Neovim viewer needs vim.system"


def gitsigns_missing():
    """Why gitsigns can't be tested here, or None."""
    if not GITSIGNS:
        return "DIFFTATE_TEST_GITSIGNS is not set: point it at a gitsigns.nvim checkout to test gitsigns' base"
    if not os.path.isfile(os.path.join(GITSIGNS, "lua", "gitsigns.lua")):
        return f"DIFFTATE_TEST_GITSIGNS={GITSIGNS} is not a gitsigns.nvim checkout"
    return None


MISSING_NVIM = nvim_missing()
MISSING_GITSIGNS = MISSING_NVIM or gitsigns_missing()


def needs(missing):
    """A test class that skips with <missing>, or fails with it when CI's Neovim job
    requires the tests to run."""
    if not (missing and REQUIRED):
        return unittest.skipIf(bool(missing), missing)

    def failing(cls):
        def setUp(self):
            self.fail(f"DIFFTATE_TEST_NVIM_REQUIRED=1, but {missing}")
        cls.setUp = setUp
        return cls
    return failing


def lua_string(text):
    """<text> as a Vim script string in double quotes."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


class Neovim:
    """A headless Neovim in <folder>, started with tests/nvim/init.lua."""

    def __init__(self, test, folder, args=(), opts=None, gitsigns=True, extra_rtp=(), before=None):
        self.test = test
        self.socket = os.path.join(test.tmp, f"nvim-{len(test.neovims)}.sock")
        xdg = os.path.join(test.tmp, "xdg")
        self.env = dict(test.env, DIFFTATE_ROOT=ROOT, DIFFTATE_TEST_OPTS=json.dumps(opts or {"poll_ms": 200}),
                        DIFFTATE_TEST_GITSIGNS=GITSIGNS if gitsigns else "",
                        DIFFTATE_TEST_EXTRA_RTP=",".join(extra_rtp), **xdg_folders(xdg))
        for name in ("NVIM", "NVIM_APPNAME", "NVIM_LISTEN_ADDRESS", "VIMINIT", "DIFFTATE_TEST_BEFORE"):
            self.env.pop(name, None)
        if before:
            self.env["DIFFTATE_TEST_BEFORE"] = before
        self.process = subprocess.Popen(
            [NVIM, "--headless", "--listen", self.socket, "-u", INIT, "-i", "NONE", *args],
            cwd=folder, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True)
        test.neovims.append(self)
        test.addCleanup(self.quit)
        wait_for("Neovim's socket", lambda: self.process.poll() is not None or self.answers())
        if self.process.poll() is not None:
            test.fail("nvim exited:\n" + self.process.stderr.read())

    def answers(self):
        try:
            return self.expr("1", timeout=5) == "1"
        except (subprocess.TimeoutExpired, AssertionError):
            return False

    def expr(self, expr, timeout=10):
        r = subprocess.run([NVIM, "--clean", "--headless", "--server", self.socket, "--remote-expr", expr],
                           env=self.env, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise AssertionError(f"--remote-expr {expr} failed: {r.stderr or r.stdout}")
        return r.stdout

    def lua(self, code, timeout=10):
        """What the Lua chunk <code> returns, run in this Neovim."""
        answer = json.loads(self.expr(f"v:lua.T.eval({lua_string(code)})", timeout=timeout))
        if not answer["ok"]:
            raise AssertionError(f"Lua failed: {answer.get('value')}\n{code}")
        return answer.get("value")

    def command(self, command):
        """Run the Ex <command>, as the reviewer types it."""
        return self.lua(f"vim.cmd({lua_string(command)})")

    def keys(self, keys):
        """Press <keys> in normal mode (<leader> is the space, as in LazyVim)."""
        self.lua(f"vim.api.nvim_feedkeys(vim.keycode({lua_string(keys)}), 'mx', false)")

    def messages(self):
        return self.lua("return vim.fn.execute('messages')")

    def status(self):
        """The plugin's status note, as a statusline shows it."""
        return self.lua("return require('difftate').status()")

    def gitsigns_base(self):
        """The base gitsigns diffs every buffer against: None for the index."""
        return self.lua("return require('gitsigns.config').config.base")

    def hunks(self):
        """gitsigns' hunks in the current buffer, as [(added lines, removed lines)], or None before it attached."""
        return self.lua("""
            if not vim.b.gitsigns_status_dict then return nil end
            local out = {}
            for _, h in ipairs(require('gitsigns').get_hunks() or {}) do
              table.insert(out, { h.added.count, h.removed.count })
            end
            return out""")

    def quit(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(10)
        self.process.stderr.close()


class NeovimHarness(Harness):
    def setUp(self):
        super().setUp()
        self.neovims = []

    def nvim(self, folder=None, *args, **kwargs):
        """Neovim started in <folder> (the repository) on app.py, or with <args>."""
        return Neovim(self, folder or self.repo, args or ("app.py",), **kwargs)

    def commit(self, message="Greet with an f-string", folder=None):
        git(folder or self.repo, self.env, "add", "-A")
        git(folder or self.repo, self.env, "commit", "-q", "-m", message)

    def head(self, folder=None, ref="HEAD"):
        return subprocess.run(["git", "-C", folder or self.repo, "rev-parse", ref], check=True,
                              capture_output=True, text=True, env=self.env).stdout.strip()

    def attached(self, nvim):
        """Wait until gitsigns attached to the current buffer; its hunks."""
        wait_for("gitsigns to attach", lambda: nvim.hunks() is not None)
        return nvim.hunks()

    def an_open_review(self, nvim=None, folder=None):
        """The review open in Neovim (started in <folder> when not given) on the
        committed change; the Neovim."""
        self.commit(folder=folder)
        if folder is None:
            self.start_watcher()
        nvim = nvim or self.nvim(folder)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        wait_for("the review's hunk", lambda: nvim.hunks() == [[1, 1]])
        return nvim


@needs(MISSING_GITSIGNS)
class OpeningTheReview(NeovimHarness, unittest.TestCase):
    def test_with_no_watcher_running_it_says_so_and_leaves_gitsigns_on_the_index(self):
        self.commit()
        nvim = self.nvim()
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("the message", lambda: "No difftate is running for" in nvim.messages())
        self.assertIn(os.path.realpath(self.repo), nvim.messages())
        self.assertIsNone(nvim.gitsigns_base())
        self.assertEqual(nvim.status(), "")

    def test_it_points_gitsigns_at_where_the_branch_left_the_base_and_says_so(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        self.assertEqual(self.attached(nvim), [], "the change is committed: nothing differs from the index")

        nvim.command("DifftateOpen")

        wait_for("gitsigns on the base", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        wait_for("the review's hunk", lambda: nvim.hunks() == [[1, 1]])
        self.assertEqual(nvim.status(), "review open · git signs show changes since main")
        self.assertIn("review open · git signs show changes since main", nvim.messages())

    def test_nvim_plus_difftate_open_opens_the_review_at_start_up(self):
        self.commit()
        self.start_watcher()

        nvim = self.nvim(None, "+DifftateOpen", "app.py")

        wait_for("gitsigns on the base", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        wait_for("the review's hunk", lambda: nvim.hunks() == [[1, 1]])

    def test_in_a_worktree_it_opens_the_review_of_that_worktree_not_the_repositorys(self):
        self.commit()
        self.start_watcher()
        folder = self.add_worktree("tidy")
        self.commit("Greet with hey", folder=folder)
        self.start_watcher_in(folder, "--base", "feature")
        nvim = self.nvim(folder)
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("gitsigns on the worktree's base", lambda: nvim.gitsigns_base() == self.head(folder, "main"))
        self.assertEqual(nvim.status(), "review open · git signs show changes since feature")


@needs(MISSING_NVIM)
class WithoutGitsigns(NeovimHarness, unittest.TestCase):
    def test_without_gitsigns_it_opens_the_review_and_says_signs_are_missing(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(gitsigns=False)

        nvim.command("DifftateOpen")

        wait_for("the review to open", lambda: nvim.status() != "")
        self.assertEqual(nvim.status(), "review open · gitsigns isn't loaded: no git signs for changes since main")


@needs(MISSING_GITSIGNS)
class ClosingTheReview(NeovimHarness, unittest.TestCase):
    def test_it_puts_gitsigns_back_on_the_index_and_removes_the_note(self):
        nvim = self.an_open_review()

        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None and nvim.hunks() == [])
        self.assertEqual(nvim.status(), "")
        self.assertIn("Review closed", nvim.messages())

    def test_difftate_status_says_whether_it_is_open(self):
        nvim = self.an_open_review()
        nvim.command("messages clear")

        nvim.command("DifftateStatus")
        nvim.command("DifftateClose")
        nvim.command("DifftateStatus")

        self.assertEqual(nvim.messages().strip().split("\n"), [
            "review open · git signs show changes since main",
            "Review closed: git signs show changes since the index again",
            "No review is open"])


@needs(MISSING_GITSIGNS)
class WhileTheReviewIsOpen(NeovimHarness, unittest.TestCase):
    def test_a_new_commit_that_moves_the_merge_base_moves_gitsigns_to_it(self):
        nvim = self.an_open_review()
        base_folder = os.path.join(self.tmp, "wt-main")
        git(self.repo, self.env, "worktree", "add", "-q", base_folder, "main")
        with open(os.path.join(base_folder, "notes.md"), "w") as f:
            f.write("Greeting style\n")
        self.commit("Add notes", folder=base_folder)

        git(self.repo, self.env, "merge", "-q", "--no-edit", "main")

        wait_for("gitsigns on the new merge-base", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        self.assertEqual(nvim.status(), "review open · git signs show changes since main")

    def test_requests_never_block_the_editor_even_when_the_watcher_hangs(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        self.attached(nvim)
        self.watcher.send_signal(signal.SIGSTOP)  # it takes requests, and answers none
        try:
            started = time.time()
            nvim.command("DifftateOpen")
            for _ in range(10):
                self.assertEqual(nvim.expr("1", timeout=2), "1")
            self.assertLess(time.time() - started, 5)
            self.assertEqual(nvim.status(), "", "not open until the watcher answers")

            self.watcher.send_signal(signal.SIGCONT)
            wait_for("the review to open", lambda: nvim.status() != "")
            self.watcher.send_signal(signal.SIGSTOP)  # now a poll hangs
            time.sleep(0.5)
            for _ in range(10):
                self.assertEqual(nvim.expr("1", timeout=2), "1")
        finally:
            self.watcher.send_signal(signal.SIGCONT)

    def test_it_says_so_when_difftate_stops_and_stops_asking_once_closed(self):
        nvim = self.an_open_review()
        self.stop_watcher()
        wait_for("the message", lambda: "difftate stopped answering" in nvim.messages())
        self.assertEqual(nvim.status(), "review open · git signs show changes since main")
        nvim.command("DifftateClose")
        nvim.command("messages clear")

        self.start_watcher()
        self.stop_watcher()
        time.sleep(1)  # five polls, were it still polling

        self.assertNotIn("difftate stopped answering", nvim.messages())


FAKE_WHICH_KEY = os.path.join(ROOT, "tests", "nvim", "fake-which-key")


@needs(MISSING_GITSIGNS)
class TheReviewKeys(NeovimHarness, unittest.TestCase):
    def test_leader_rr_opens_the_review_and_closes_it_again(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        self.attached(nvim)

        nvim.keys("<leader>rr")
        wait_for("the review to open", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        nvim.keys("<leader>rr")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.status(), "")

    def test_the_key_comes_from_opts_keys_and_false_maps_none(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(opts={"poll_ms": 200, "keys": {"toggle": "<leader>rv"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rr', 'n')"), "")

        nvim.keys("<leader>rv")

        wait_for("the review to open", lambda: nvim.status() != "")
        unmapped = self.nvim(opts={"keys": {"toggle": False}})
        self.assertEqual(unmapped.lua("return vim.fn.maparg('<leader>rr', 'n')"), "")

    def test_a_key_another_plugin_mapped_stays_its_and_it_says_which_option_to_change(self):
        nvim = self.nvim(before="vim.keymap.set('n', '<leader>rr', '<cmd>echo \"refactor\"<cr>', { desc = 'Refactor' })")

        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rr', 'n')"), '<Cmd>echo "refactor"<CR>')
        self.assertIn("<leader>rr is already mapped (Refactor): set opts.keys.toggle to another key",
                      nvim.messages())

    def test_it_adds_a_review_group_to_which_key_when_which_key_is_there(self):
        nvim = self.nvim(extra_rtp=[FAKE_WHICH_KEY])

        added = nvim.lua("return require('which-key').added")

        self.assertEqual(added, [[{"1": "<leader>r", "group": "review", "mode": ["n", "x"]}]])

    def test_setting_it_up_changes_no_option_and_only_adds_its_key(self):
        nvim = self.nvim()

        before, after = nvim.lua("return T.before"), nvim.lua("return T.after_setup")

        self.assertEqual(after["options"], before["options"])
        self.assertEqual(set(after["keys"]) - set(before["keys"]), {"n  rr"})
        self.assertEqual({k: v for k, v in after["keys"].items() if k in before["keys"]}, before["keys"])

    def test_opening_and_closing_the_review_changes_no_option_or_key(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        self.attached(nvim)
        before = nvim.lua("return T.snapshot()")
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")

        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua("return T.snapshot()"), before)
