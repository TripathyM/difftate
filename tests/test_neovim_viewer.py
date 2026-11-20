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


def nvim_folders(folder):
    """Every XDG folder Neovim reads or writes, and its log, in <folder>: never the
    reviewer's, nor the folder a test runs in (Neovim falls back to ./nvim.log)."""
    folders = {f"XDG_{name.upper()}_HOME": os.path.join(folder, name) for name in ("config", "data", "state", "cache")}
    return dict(folders, NVIM_LOG_FILE=os.path.join(folder, "nvim.log"))


def nvim_missing():
    """Why the Neovim viewer can't be tested here, or None."""
    if not NVIM:
        return "nvim is not on PATH: install Neovim 0.10 or later to test the Neovim viewer"
    with tempfile.TemporaryDirectory(prefix="difftate-nvim-") as tmp:
        # Neovim's own folders in <tmp>: its log never goes to the reviewer's ~/.local/state
        env = dict(os.environ, HOME=tmp, **nvim_folders(tmp))
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


def vim_string(text):
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
                        DIFFTATE_TEST_EXTRA_RTP=",".join(extra_rtp), **nvim_folders(xdg))
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
                           cwd=self.test.tmp, env=self.env, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise AssertionError(f"--remote-expr {expr} failed: {r.stderr or r.stdout}")
        return r.stdout

    def lua(self, code, timeout=10):
        """What the Lua chunk <code> returns, run in this Neovim."""
        answer = json.loads(self.expr(f"v:lua.T.eval({vim_string(code)})", timeout=timeout))
        if not answer["ok"]:
            raise AssertionError(f"Lua failed: {answer.get('value')}\n{code}")
        return answer.get("value")

    def command(self, command):
        """Run the Ex <command>, as the reviewer types it."""
        return self.lua(f"vim.cmd({vim_string(command)})")

    def keys(self, keys):
        """Press <keys> in normal mode (<leader> is the space, as in LazyVim)."""
        self.lua(f"vim.api.nvim_feedkeys(vim.keycode({vim_string(keys)}), 'mx', false)")

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

    def threads(self, buf=0):
        """The threads drawn in buffer <buf> (0: the current one), as the reviewer sees them:
        [{"row": the line (1-based) it is drawn under, "above": drawn above that line, "lines":
        its virtual lines as text}], top to bottom."""
        return self.lua(f"return T.drawn({buf}).threads")

    def signs(self, buf=0):
        """The signs the plugin placed in buffer <buf>: [(line, sign text)], top to bottom."""
        return [tuple(s) for s in self.lua(f"return T.drawn({buf}).signs")]

    def text_columns(self):
        """The columns of the current window's text: its width without the signs and numbers."""
        return self.lua("return vim.api.nvim_win_get_width(0) - vim.fn.getwininfo(vim.api.nvim_get_current_win())[1].textoff")

    def float_lines(self):
        """The lines of the float the plugin opened, or None when none is open."""
        return self.lua("""
            for _, win in ipairs(vim.api.nvim_list_wins()) do
              if vim.api.nvim_win_get_config(win).relative ~= "" then
                return vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(win), 0, -1, false)
              end
            end""")

    def compose_float(self):
        """The compose float the plugin opened (the current window): {"lines", "filetype", "title"}, or
        None when the current window is not a float."""
        return self.lua("""
            local win = vim.api.nvim_get_current_win()
            local config = vim.api.nvim_win_get_config(win)
            if config.relative == "" then return nil end
            local buf = vim.api.nvim_win_get_buf(win)
            return { lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false), filetype = vim.bo[buf].filetype,
                     title = config.title and config.title[1] and config.title[1][1] or "" }""")

    def menu(self):
        """The picker the plugin opened (see FAKE_SELECT, FAKE_SNACKS): {"title", "lines", "via"}, or None."""
        return self.lua("return T.menu")

    def pick(self, n):
        """Choose the <n>th (1-based) entry of the open picker, as Enter does."""
        # After the call returns, as a picker's Enter is: not inside the expression that presses it
        self.lua(f"local choose = T.choose_menu; T.menu = nil; T.choose_menu = nil; vim.schedule(function() local ok, err = pcall(choose, {n}); T.err = not ok and tostring(err) or nil end)")

    def at(self):
        """Where the cursor is: [file name, line]."""
        return self.lua("return { vim.fn.expand('%:t'), vim.fn.line('.') }")

    def write_text(self, text):
        """Make <text> the text of the current buffer, as typing it would."""
        self.lua(f"vim.api.nvim_buf_set_lines(0, 0, -1, false, vim.split(vim.json.decode([==[{json.dumps(text)}]==]), '\\n'))")

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


    def a_thread(self, body, line=2, **kwargs):
        """A thread of the reviewer's on app.py's line <line> (a batched review holds it:
        no coding agent answers); its id."""
        return self.open_thread(body, line=line, **kwargs)["id"]

    def batched(self):
        self.api("PUT", "/api/mode", {"mode": "batched"})

    def drawn(self, nvim, rows=None):
        """Wait until the current buffer shows the threads (on <rows>, when given); them."""
        def shown():
            threads = nvim.threads()
            return threads if threads and (rows is None or [t["row"] for t in threads] == rows) else None
        return wait_for("the threads to be drawn", shown)


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

    def test_a_base_the_reviewer_gave_gitsigns_comes_back_and_the_message_names_it(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(before="require('gitsigns').change_base('HEAD', true)")
        wait_for("the reviewer's base", lambda: nvim.gitsigns_base() == "HEAD")
        nvim.command("DifftateOpen")
        wait_for("gitsigns on the base", lambda: nvim.gitsigns_base() == self.head(ref="main"))

        nvim.command("DifftateClose")

        wait_for("the reviewer's base again", lambda: nvim.gitsigns_base() == "HEAD")
        self.assertIn("Review closed: git signs show changes since HEAD again", nvim.messages())

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
        time.sleep(1)  # five polls, were it still polling: one would reach this watcher
        self.stop_watcher()
        time.sleep(1)  # and five more would find it stopped

        self.assertNotIn("difftate stopped answering", nvim.messages())


# Pickers that record what they were given (T.menu) and wait for the test to choose (T.choose_menu)
FAKE_SELECT = ("vim.ui.select = function(items, opts, on_choice) T.menu = { via = 'ui.select', title = opts.prompt, "
               "lines = vim.tbl_map(function(i) return opts.format_item and opts.format_item(i) or tostring(i) end, items) }; "
               "T.choose_menu = function(n) on_choice(items[n], n) end end")
FAKE_SNACKS = ("_G.Snacks = { picker = { pick = function(o) T.menu = { via = 'snacks', title = o.title, "
               "lines = vim.tbl_map(function(i) return i.text end, o.items) }; "
               "T.choose_menu = function(n) o.confirm({ close = function() end }, o.items[n]) end end } }")

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

    def test_with_no_key_under_leader_r_it_adds_no_group_to_which_key(self):
        nvim = self.nvim(extra_rtp=[FAKE_WHICH_KEY], opts={"keys": {
            "toggle": "<leader>gR", "expand": "<leader>gE", "thread": "<leader>gT", "comment": "<leader>gC", "add_comment": "<leader>gA",
            "resolve": "<leader>gS", "reopen": "<leader>gO", "general": "<leader>gG",
            "threads": "<leader>gP", "files": "<leader>gF", "next": "<leader>gN", "previous": "<leader>gB"}})

        self.assertEqual(nvim.lua("return require('which-key').added"), [])

    def test_setting_it_up_changes_no_option_and_only_adds_its_key(self):
        nvim = self.nvim()

        before, after = nvim.lua("return T.before"), nvim.lua("return T.after_setup")

        self.assertEqual(after["options"], before["options"])
        self.assertEqual(set(after["keys"]) - set(before["keys"]), {"n  rr", "n  re", "n  rt", "n  rc", "x  rc", "n  ra", "n  rR", "n  rO", "n  rG",
                                                                 "n  rs", "n  rf", "n ]r", "n [r"})
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

    def test_threads_drawn_expanded_read_in_the_float_and_removed_change_no_option_or_key(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        self.a_thread("Is it a style?", line=1)
        tid = self.a_thread("Done already", line=2)
        self.api("PATCH", f"/api/threads/{tid}/status", {"status": "resolved"})
        # LazyVim sets wrap and spell on every markdown buffer, in the current window
        nvim = self.nvim(before="vim.api.nvim_create_autocmd('FileType', { pattern = 'markdown', callback = function() "
                                "vim.opt_local.wrap = true; vim.opt_local.spell = true end })")
        self.attached(nvim)
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        nvim.command("DifftateOpen")
        self.drawn(nvim)

        nvim.keys("<leader>re")
        wait_for("them expanded", lambda: max(len(t["lines"]) for t in nvim.threads()) > 2)
        nvim.command("vsplit")
        nvim.command("2")
        nvim.keys("<leader>rt")  # two threads on the line: a choice
        nvim.lua("vim.ui.select = function(items, _, choose) choose(items[1]) end")
        nvim.keys("<leader>rt")
        wait_for("the float", lambda: nvim.float_lines())
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before, "the float is open: the reviewer's window is as it was")
        nvim.keys("q")
        nvim.command("close")
        nvim.keys("<leader>re")
        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)


@needs(MISSING_GITSIGNS)
class ThreadsUnderTheirLines(NeovimHarness, unittest.TestCase):
    def test_an_open_thread_is_drawn_in_full_under_its_last_line_with_a_sign_at_its_first(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread("Why not name this `who`?", line=1, end=2)
        self.api("POST", f"/api/threads/{tid}/comments", {"kind": "reply", "body": "It matches the callers."})
        self.api("POST", f"/api/threads/{tid}/comments", {"body": "Then rename the callers.", "reviewer": "security-bot"})
        nvim = self.nvim()

        nvim.command("DifftateOpen")

        self.assertEqual(self.drawn(nvim), [{"row": 2, "above": False, "lines": [
            "│ ● open · held until you submit · lines 1-2",
            "│ Test",
            "│   Why not name this `who`?",
            "│ agent",
            "│   It matches the callers.",
            "│ security-bot",
            "│   Then rename the callers."]}])
        self.assertEqual(nvim.signs(), [(1, "●")])


LONG = ("The greeting would read better with the name first, and a short comment above explains why the "
        "f-string replaced the concatenation: callers who search for it find the reason at once.")


def words(lines):
    """The words of <lines>, as a reader reads them across line breaks."""
    return " ".join(lines).split()


@needs(MISSING_GITSIGNS)
class WrappingThreads(NeovimHarness, unittest.TestCase):
    def test_a_long_comment_wraps_to_the_window_and_wraps_again_after_a_resize(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread(LONG)
        nvim = self.nvim()
        nvim.command("DifftateOpen")

        wide = self.drawn(nvim)[0]["lines"]
        nvim.command("vsplit")
        wait_for("the thread to wrap narrower", lambda: nvim.threads()[0]["lines"] != wide)
        narrow = nvim.threads()[0]["lines"]
        nvim.command("only")
        wait_for("the thread to wrap wide again", lambda: nvim.threads()[0]["lines"] == wide)

        self.assertEqual(words(line[len("│   "):] for line in wide[2:]), LONG.split())
        self.assertTrue(all(len(line) <= 80 for line in wide), wide)
        self.assertGreater(len(wide), 4, "wide enough to need more than one line")
        self.assertEqual(words(line[len("│   "):] for line in narrow[2:]), LONG.split())
        self.assertGreater(len(narrow), len(wide))
        self.assertTrue(all(len(line) <= 40 for line in narrow), narrow)

    def test_a_word_longer_than_the_window_is_broken_and_nothing_is_lost(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("see " + "x" * 200 + " there")
        nvim = self.nvim()

        nvim.command("DifftateOpen")

        lines = self.drawn(nvim)[0]["lines"]
        self.assertTrue(all(len(line) <= 80 for line in lines), lines)
        self.assertEqual("".join(line[len("│   "):] for line in lines[2:]).replace(" ", ""), "see" + "x" * 200 + "there")


@needs(MISSING_GITSIGNS)
class OneLineThreads(NeovimHarness, unittest.TestCase):
    def a_review_of_a_resolved_a_dismissed_and_an_outdated_thread(self):
        self.write("notes.md", "# Notes\nGreeting style\nLine three\n")
        self.commit()
        self.start_watcher()
        self.batched()
        resolved = self.a_thread("Use a clearer name here, please: `who` reads better than `name`", line=1)
        dismissed = self.a_thread("Add a docstring", line=2)
        outdated = self.a_thread("Is this the style we want?", line=2, file="notes.md", anchor_code="Another style")
        self.api("PATCH", f"/api/threads/{resolved}/status", {"status": "resolved", "reviewer": "security-bot"})
        self.api("PATCH", f"/api/threads/{dismissed}/status", {"status": "dismissed"})
        self.api("POST", f"/api/threads/{resolved}/comments", {"kind": "reply", "body": "Renamed."})
        return self.nvim()

    def test_resolved_dismissed_and_outdated_threads_are_one_line_each(self):
        nvim = self.a_review_of_a_resolved_a_dismissed_and_an_outdated_thread()

        nvim.command("DifftateOpen")

        threads = self.drawn(nvim, rows=[1, 2])
        self.assertEqual([t["lines"] for t in threads], [
            ["│ ○ resolved by security-bot · 2 comments · “Use a clearer name here, plea…”"],
            ["│ ○ dismissed by Test · 1 comment · “Add a docstring”"]])
        nvim.command("edit notes.md")
        self.assertEqual([t["lines"] for t in self.drawn(nvim)], [
            ["│ ● open · held until you submit · outdated · 1 comment · “Is this the style…”"]])

    def test_the_toggle_expands_every_one_and_collapses_them_again(self):
        nvim = self.a_review_of_a_resolved_a_dismissed_and_an_outdated_thread()
        nvim.command("DifftateOpen")
        collapsed = self.drawn(nvim, rows=[1, 2])

        nvim.keys("<leader>re")

        wait_for("the threads to expand", lambda: len(nvim.threads()[0]["lines"]) > 1)
        self.assertEqual([t["lines"] for t in nvim.threads()], [
            ["│ ○ resolved by security-bot",
             "│ Test",
             "│   Use a clearer name here, please: `who` reads better than `name`",
             "│ agent",
             "│   Renamed."],
            ["│ ○ dismissed by Test", "│ Test", "│   Add a docstring"]])
        nvim.command("edit notes.md")
        self.assertEqual([t["lines"] for t in self.drawn(nvim)], [
            ["│ ● open · held until you submit · outdated",
             "│ code when written (it changed since)",
             "│ > Another style",
             "│ Test",
             "│   Is this the style we want?"]])
        nvim.command("edit app.py")
        nvim.keys("<leader>re")
        wait_for("the threads to collapse", lambda: nvim.threads() == collapsed)

    def test_a_thread_that_gets_resolved_shrinks_by_itself(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread("Add a docstring")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.assertEqual(len(self.drawn(nvim)[0]["lines"]), 3)

        self.api("PATCH", f"/api/threads/{tid}/status", {"status": "resolved", "reviewer": "reviewer-two"})

        wait_for("the one line", lambda: nvim.threads()[0]["lines"] == [
            "│ ○ resolved by reviewer-two · 1 comment · “Add a docstring”"])
        self.assertEqual(nvim.signs(), [(2, "○")])


@needs(MISSING_GITSIGNS)
class ThreadsThatMove(NeovimHarness, unittest.TestCase):
    def test_a_reply_the_agent_posts_appears_without_a_key_press(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread("Add a docstring")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.assertEqual(len(self.drawn(nvim)[0]["lines"]), 3)

        self.api("POST", f"/api/threads/{tid}/comments", {"kind": "reply", "body": "Added one."})

        wait_for("the reply", lambda: nvim.threads()[0]["lines"][-2:] == ["│ agent", "│   Added one."])

    def test_a_new_thread_in_another_viewer_appears_too(self):
        self.commit()
        self.start_watcher()
        self.batched()
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        self.assertEqual(nvim.threads(), [])

        self.a_thread("Fresh from the browser", line=1)

        self.assertEqual(self.drawn(nvim, rows=[1])[0]["lines"][-1], "│   Fresh from the browser")

    def test_an_edit_above_a_thread_moves_it_before_the_file_is_saved_and_a_poll_keeps_it_there(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim, rows=[2])

        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, 0, false, { '# greeting', '' })")

        self.assertEqual([t["row"] for t in nvim.threads()], [4])
        self.assertEqual(nvim.signs(), [(4, "●")])
        time.sleep(1)  # five polls
        self.assertEqual([t["row"] for t in nvim.threads()], [4], "a poll puts it back where the file has it")
        self.assertEqual(nvim.signs(), [(4, "●")])

        nvim.command("write")
        wait_for("the watcher to move the thread", lambda: self.thread(self.api("GET", "/api/threads")[0]["id"])
                 ["anchor"]["endLine"] == 4)
        time.sleep(1)
        self.assertEqual([t["row"] for t in nvim.threads()], [4])
        self.assertEqual(nvim.signs(), [(4, "●")], "one thread, one sign")

    def test_reloading_the_buffer_draws_each_thread_once(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        first = self.drawn(nvim)

        nvim.command("edit!")
        time.sleep(0.6)  # a poll or two

        self.assertEqual(self.drawn(nvim), first)
        self.assertEqual(nvim.signs(), [(2, "●")])

    def test_a_general_thread_has_no_line_and_is_not_drawn(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.api("POST", "/api/threads", {"anchor": None, "body": "Overall: nice"})
        self.a_thread("Add a docstring")
        nvim = self.nvim()

        nvim.command("DifftateOpen")

        self.assertEqual([t["row"] for t in self.drawn(nvim)], [2])

    def test_a_buffer_opened_after_the_review_gets_its_threads(self):
        self.write("notes.md", "# Notes\nGreeting style\n")
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Is this the style we want?", line=2, file="notes.md")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")

        nvim.command("edit notes.md")

        self.assertEqual(self.drawn(nvim)[0]["row"], 2)


@needs(MISSING_GITSIGNS)
class ThreadsOnDeletedLines(NeovimHarness, unittest.TestCase):
    def an_old_side_thread(self, line, code, body="Why drop this?"):
        return self.api("POST", "/api/threads", {
            "anchor": {"file": "app.py", "side": "old", "startLine": line, "endLine": line, "code": code},
            "body": body})["id"]

    def test_it_is_drawn_where_the_line_was_deleted_with_the_deleted_code_quoted(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.an_old_side_thread(2, "    return 'hi ' + name")
        nvim = self.nvim()

        nvim.command("DifftateOpen")

        self.assertEqual(self.drawn(nvim), [{"row": 1, "above": False, "lines": [
            "│ ● open · held until you submit · deleted line 2",
            "│ -     return 'hi ' + name",
            "│ Test",
            "│   Why drop this?"]}])
        self.assertEqual(nvim.signs(), [(1, "●")])

    def test_a_deletion_at_the_top_of_the_file_is_drawn_above_its_first_line(self):
        git(self.repo, self.env, "stash", "-q")  # app.py's change waits while main gets its notes
        git(self.repo, self.env, "checkout", "-q", "main")
        self.write("notes.md", "# Notes\nGreeting style\n")
        self.commit("Add notes")
        git(self.repo, self.env, "checkout", "-q", "feature")
        git(self.repo, self.env, "merge", "-q", "main")
        git(self.repo, self.env, "stash", "pop", "-q")
        self.write("notes.md", "Greeting style\n")
        self.commit("Drop the heading")
        self.start_watcher()
        self.batched()
        self.api("POST", "/api/threads", {"anchor": {"file": "notes.md", "side": "old", "startLine": 1, "endLine": 1,
                                                    "code": "# Notes"}, "body": "Keep it"})
        nvim = self.nvim(None, "notes.md")

        nvim.command("DifftateOpen")

        thread = self.drawn(nvim)[0]
        self.assertEqual((thread["row"], thread["above"]), (1, True))
        self.assertEqual(thread["lines"][:2], ["│ ● open · held until you submit · deleted line 1", "│ - # Notes"])


@needs(MISSING_GITSIGNS)
class ReadingAThreadInAFloat(NeovimHarness, unittest.TestCase):
    def a_review_with_a_thread_on_line_two(self, **kwargs):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread(LONG, **kwargs)
        self.api("POST", f"/api/threads/{tid}/comments", {"kind": "reply", "body": "Added a comment.\n\nSee below."})
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("2")
        return nvim

    def test_leader_rt_opens_the_thread_on_the_cursors_line_in_full_as_read_only_markdown(self):
        nvim = self.a_review_with_a_thread_on_line_two()

        nvim.keys("<leader>rt")

        wait_for("the float", lambda: nvim.float_lines())
        lines = nvim.float_lines()
        self.assertEqual(lines[:4], ["# ● open · agent replied", "", "`app.py` line 2", ""])
        self.assertRegex(lines[4], r"^## Test · \d{4}-\d\d-\d\d \d\d:\d\d UTC$")
        self.assertEqual(lines[6], LONG, "long lines are not cut: the float wraps them")
        self.assertRegex(lines[7:][lines[7:].index("") + 1], r"^## agent · \d{4}-\d\d-\d\d \d\d:\d\d UTC$")
        self.assertEqual(lines[-3:], ["Added a comment.", "", "See below."])
        self.assertEqual(nvim.lua("return { vim.bo.filetype, vim.bo.modifiable, vim.wo.wrap, vim.wo.linebreak }"),
                         ["markdown", False, True, True])

    def test_it_can_be_yanked_from_and_searched_and_q_closes_it(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        nvim.keys("<leader>rt")
        wait_for("the float", lambda: nvim.float_lines())

        nvim.keys("/callers<cr>")
        nvim.keys("yiw")

        self.assertEqual(nvim.lua("return vim.fn.getreg('\"')"), "callers")
        nvim.keys("q")
        self.assertIsNone(nvim.float_lines())
        self.assertEqual(nvim.lua("return vim.api.nvim_buf_get_name(0):match('app.py$')"), "app.py")

    def test_an_outdated_thread_shows_the_code_it_was_written_on(self):
        nvim = self.a_review_with_a_thread_on_line_two(anchor_code="    return 'bye ' + name")

        nvim.keys("<leader>rt")

        wait_for("the float", lambda: nvim.float_lines())
        lines = nvim.float_lines()
        self.assertIn("Code when written (it changed since):", lines)
        at = lines.index("Code when written (it changed since):")
        self.assertEqual(lines[at + 1:at + 4], ["```python", "    return 'bye ' + name", "```"])

    def test_on_a_line_with_no_thread_it_says_so_and_opens_nothing(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        nvim.command("1")

        nvim.keys("<leader>rt")

        wait_for("the message", lambda: "No thread on this line" in nvim.messages())
        self.assertIsNone(nvim.float_lines())

    def test_with_two_threads_on_a_line_it_asks_which(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        self.a_thread("Second opinion")
        wait_for("both threads", lambda: len(nvim.threads()) == 2)
        nvim.lua("vim.ui.select = function(items, _, choose) choose(items[2]) end")

        nvim.keys("<leader>rt")

        wait_for("the float", lambda: nvim.float_lines())
        self.assertIn("Second opinion", nvim.float_lines())

    def test_k_stays_what_it_was_and_the_float_has_no_k(self):
        nvim = self.nvim(before="vim.keymap.set('n', 'K', function() vim.g.hover = true end, { desc = 'Hover' })")
        before = nvim.lua("return vim.fn.maparg('K', 'n', false, true).desc")
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("2")
        nvim.keys("<leader>rt")
        wait_for("the float", lambda: nvim.float_lines())

        self.assertEqual(nvim.lua("return vim.fn.maparg('K', 'n', false, true).buffer"), 0, "no K of the float's own")
        self.assertEqual(nvim.lua("return vim.fn.maparg('K', 'n', false, true).desc"), before)
        nvim.keys("q")
        self.assertEqual(nvim.lua("return vim.fn.maparg('K', 'n', false, true).desc"), before)

    def test_reading_threads_over_and_over_leaves_no_buffer_behind(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        buffers = nvim.lua("return #vim.fn.getbufinfo()")

        for _ in range(3):
            nvim.keys("<leader>rt")
            wait_for("the float", lambda: nvim.float_lines())
            nvim.keys("q")

        self.assertEqual(nvim.lua("return #vim.fn.getbufinfo()"), buffers)

    def test_closing_the_review_closes_the_float(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        nvim.keys("<leader>rt")
        wait_for("the float", lambda: nvim.float_lines())

        nvim.command("DifftateClose")

        self.assertIsNone(nvim.float_lines())


@needs(MISSING_GITSIGNS)
class ClosingRemovesTheThreads(NeovimHarness, unittest.TestCase):
    def test_closing_the_review_removes_every_thread_and_sign_from_every_buffer(self):
        self.write("notes.md", "# Notes\nGreeting style\n")
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        self.a_thread("Is this the style we want?", line=2, file="notes.md")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("edit notes.md")
        self.drawn(nvim)

        nvim.command("DifftateClose")

        for buffer in ("app.py", "notes.md"):
            nvim.command(f"edit {buffer}")
            self.assertEqual((nvim.threads(), nvim.signs()), ([], []), buffer)
        time.sleep(0.6)
        self.assertEqual((nvim.threads(), nvim.signs()), ([], []), "nothing comes back with a poll")

    def test_opening_again_draws_them_again(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        first = self.drawn(nvim)
        nvim.command("DifftateClose")
        self.assertEqual(nvim.threads(), [])

        nvim.command("DifftateOpen")

        self.assertEqual(self.drawn(nvim), first)


class WrappingText(NeovimHarness, unittest.TestCase):
    def wrap(self, nvim, text, columns):
        return nvim.lua(f"return require('difftate.wrap').wrap({json.dumps(text, ensure_ascii=False)}, {columns})")

    @unittest.skipIf(MISSING_NVIM is not None, MISSING_NVIM or "")
    def test_wrapping_keeps_breaks_blank_lines_and_indentation_and_counts_wide_characters(self):
        nvim = self.nvim(None, gitsigns=False)

        self.assertEqual(self.wrap(nvim, "one two three\n\n  - a list item that wraps", 12),
                         ["one two", "three", "", "  - a list", "  item that", "  wraps"])
        self.assertEqual(self.wrap(nvim, "日本語 日本語", 6), ["日本語", "日本語"])
        self.assertEqual(self.wrap(nvim, "abcdefghij", 4), ["abcd", "efgh", "ij"])
        self.assertEqual(self.wrap(nvim, "", 10), [""])


@needs(MISSING_GITSIGNS)
class CommentingOnLines(NeovimHarness, unittest.TestCase):
    def a_review(self):
        """The review open in Neovim on app.py, batched: no coding agent answers; the Neovim."""
        nvim = self.an_open_review()
        self.batched()
        return nvim

    def anchors(self):
        return [(t["anchor"] and (t["anchor"]["file"], t["anchor"]["side"], t["anchor"]["startLine"],
                                  t["anchor"]["endLine"], t["anchor"]["code"]), t["comments"][0]["body"])
                for t in self.api("GET", "/api/threads")]

    def test_leader_rc_on_a_line_opens_a_markdown_float_and_w_posts_the_thread_anchored_to_the_code_on_disk(self):
        nvim = self.a_review()
        nvim.command("2")

        nvim.keys("<leader>rc")

        wait_for("the compose float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["filetype"], "markdown")
        self.assertIn("app.py:2", nvim.compose_float()["title"])
        nvim.write_text("Name the greeting first")
        nvim.command("write")
        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        self.assertEqual(self.anchors(), [(("app.py", "new", 2, 2, "    return f'hello {name}'"), "Name the greeting first")])
        self.assertEqual(self.api("GET", "/api/threads")[0]["comments"][0]["by"], "Test", "the API's default reviewer name")
        self.assertIsNone(nvim.compose_float(), "the float closed once it was sent")

    def test_the_thread_shows_inline_as_soon_as_it_is_posted_not_at_the_next_poll(self):
        self.commit()
        self.start_watcher()
        self.batched()
        nvim = self.nvim(opts={"poll_ms": 600000})  # no poll can draw it
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.command("2")
        nvim.keys("<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Name the greeting first")

        nvim.command("write")

        threads = self.drawn(nvim, rows=[2])
        self.assertIn("Name the greeting first", "\n".join(threads[0]["lines"]))

    def test_a_visual_range_is_anchored_to_all_its_lines(self):
        nvim = self.a_review()
        nvim.command("1")

        nvim.keys("Vj<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Both lines")
        nvim.command("write")

        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        self.assertEqual(self.anchors(), [(("app.py", "new", 1, 2, "def greet(name):\n    return f'hello {name}'"), "Both lines")])
        self.drawn(nvim, rows=[2])

    def test_a_multi_line_comment_keeps_its_breaks(self):
        nvim = self.a_review()
        nvim.command("2")
        nvim.keys("<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        text = "First paragraph.\n\n- one\n- two\n    indented"

        nvim.write_text(text)
        nvim.command("write")

        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        self.assertEqual(self.api("GET", "/api/threads")[0]["comments"][0]["body"], text)


@needs(MISSING_GITSIGNS)
class TheComposeFloat(NeovimHarness, unittest.TestCase):
    def a_review(self, **kwargs):
        nvim = self.an_open_review(**kwargs)
        self.batched()
        return nvim

    def compose(self, nvim, text, keys="<leader>rc", line="2"):
        """Open compose with <keys> on <line> and write <text> in it."""
        nvim.command(line)
        nvim.keys(keys)
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text(text)

    def test_q_keeps_the_unsent_text_and_the_same_compose_brings_it_back_until_it_is_sent(self):
        nvim = self.a_review()
        self.compose(nvim, "A long thought\nin two lines")

        nvim.keys("<Esc>")
        nvim.keys("q")

        self.assertIsNone(nvim.compose_float())
        self.assertEqual(self.api("GET", "/api/threads"), [], "q sends nothing")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], ["A long thought", "in two lines"])
        nvim.command("write")
        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], [""], "sending cleared it")

    def test_another_line_has_its_own_text_and_a_blank_float_keeps_nothing(self):
        nvim = self.a_review()
        self.compose(nvim, "For line two")
        nvim.keys("<Esc>q")
        nvim.command("1")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], [""])
        nvim.keys("<Esc>q")

        nvim.command("2")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())

        self.assertEqual(nvim.compose_float()["lines"], ["For line two"])

    def test_closing_the_float_by_leaving_it_keeps_the_text_too(self):
        nvim = self.a_review()
        self.compose(nvim, "Half written")

        nvim.keys("<Esc>")
        nvim.command("wincmd p")

        wait_for("the float to close", lambda: nvim.compose_float() is None)
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], ["Half written"])

    def test_c_s_sends_from_insert_mode_and_the_float_closes(self):
        nvim = self.a_review()
        self.compose(nvim, "Sent with a key")

        nvim.keys("<C-s>")

        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        self.assertIsNone(nvim.compose_float())
        self.assertEqual(self.bodies(self.api("GET", "/api/threads")[0]["id"]), ["Sent with a key"])

    def test_c_s_stays_the_save_key_in_every_other_buffer_and_after_composing(self):
        self.commit()
        self.start_watcher()
        self.batched()
        nvim = self.nvim(before="vim.keymap.set({'i', 'x', 'n', 's'}, '<C-s>', '<cmd>w<cr><esc>', { desc = 'Save File' })")
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        save = "return vim.fn.maparg('<C-s>', 'n', false, true).rhs .. vim.fn.maparg('<C-s>', 'n', false, true).desc"
        before = nvim.lua(save)
        self.compose(nvim, "Sent with a key")
        nvim.keys("<C-s>")
        wait_for("the thread", lambda: self.api("GET", "/api/threads"))

        self.assertEqual(nvim.lua(save), before)
        nvim.command("2")
        nvim.lua("vim.api.nvim_buf_set_lines(0, 1, 2, false, { '    return 1' })")
        nvim.keys("<C-s>")
        wait_for("the file to be saved", lambda: "return 1" in self.read("app.py"))
        self.assertEqual(nvim.lua("return vim.bo.modified"), False)

    def test_completion_is_off_in_the_float_only_so_enter_always_means_a_new_line(self):
        nvim = self.a_review()
        reviewers_buffer = nvim.lua("return vim.api.nvim_get_current_buf()")
        self.compose(nvim, "Too short")

        self.assertIs(nvim.lua("return vim.b.completion"), False, "the float's buffer: blink.cmp and nvim-cmp setups honour it")
        self.assertIsNone(nvim.lua(f"return vim.b[{reviewers_buffer}].completion"), "the reviewer's buffer is as it was")
        nvim.keys("<Esc>q")
        self.assertIsNone(nvim.lua("return vim.b.completion"))

    def test_an_empty_float_sends_nothing_and_stays_open(self):
        nvim = self.a_review()
        self.compose(nvim, "  \n ")

        nvim.command("write")

        wait_for("the message", lambda: "Nothing to send" in nvim.messages())
        self.assertTrue(nvim.compose_float())
        self.assertEqual(self.api("GET", "/api/threads"), [])

    def test_a_buffer_with_unsaved_changes_is_refused_and_nothing_opens_or_is_posted(self):
        nvim = self.a_review()
        nvim.command("2")
        nvim.lua("vim.api.nvim_buf_set_lines(0, 1, 2, false, { '    return 1' })")

        nvim.keys("<leader>rc")
        nvim.keys("Vj<leader>rc")

        wait_for("the message", lambda: "Save the file to comment on it" in nvim.messages())
        self.assertIsNone(nvim.compose_float())
        self.assertEqual(self.api("GET", "/api/threads"), [])
        nvim.command("write")
        nvim.keys("<leader>rc")
        wait_for("the float once saved", lambda: nvim.compose_float())

    def test_an_unsaved_buffer_outside_the_review_is_asked_to_be_saved_first(self):
        nvim = self.a_review()
        nvim.command("enew")
        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, -1, false, { 'scratch' })")

        nvim.keys("<leader>rc")

        wait_for("the message", lambda: "Save the file to comment on it" in nvim.messages())
        self.assertIsNone(nvim.compose_float())

    def test_with_no_review_open_it_says_so(self):
        self.commit()
        nvim = self.nvim()
        for keys in ("<leader>rc", "<leader>ra", "<leader>rR", "<leader>rO", "<leader>rG"):
            nvim.keys(keys)
        self.assertIsNone(nvim.compose_float())
        self.assertEqual(nvim.messages().count("No review is open: open it to"), 5)

    def test_a_buffer_that_is_not_a_file_of_the_review_is_refused(self):
        nvim = self.a_review()
        nvim.command("enew")
        nvim.keys("<leader>rc")
        nvim.command("edit " + os.path.join(self.tmp, "elsewhere.txt"))
        nvim.keys("<leader>rc")

        self.assertIsNone(nvim.compose_float())
        self.assertIn("This buffer is not a file", nvim.messages())
        self.assertIn("is not in", nvim.messages())

    def test_a_key_another_plugin_took_in_visual_mode_stays_theirs_and_normal_mode_still_works(self):
        nvim = self.nvim(before="vim.keymap.set('x', '<leader>rc', '<cmd>echo \"mine\"<cr>', { desc = 'Mine' })")

        self.assertIn("<leader>rc is already mapped (Mine): set opts.keys.comment to another key", nvim.messages())
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rc', 'x')"), '<Cmd>echo "mine"<CR>')
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>rc', 'n')"), "")

    def test_composing_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        self.commit()
        self.start_watcher()
        self.batched()
        # LazyVim sets wrap and spell on every markdown buffer, in the current window
        nvim = self.nvim(before="vim.api.nvim_create_autocmd('FileType', { pattern = 'markdown', callback = function() "
                                "vim.opt_local.wrap = true; vim.opt_local.spell = true end })")
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        self.compose(nvim, "One")
        nvim.keys("<Esc>q")
        self.compose(nvim, "Two", keys="Vj<leader>rc", line="1")
        nvim.command("write")
        self.drawn(nvim)
        nvim.command("2")
        nvim.keys("<leader>ra")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.keys("<Esc>q")
        nvim.keys("<leader>rG")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.keys("<Esc>q")
        nvim.keys("<leader>rR")
        wait_for("resolved", lambda: self.api("GET", "/api/threads")[0]["status"] == "resolved")
        wait_for("drawn as resolved", lambda: len(nvim.threads()[0]["lines"]) == 1)
        nvim.keys("<leader>rO")
        wait_for("reopened", lambda: self.api("GET", "/api/threads")[0]["status"] == "open")
        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)


@needs(MISSING_GITSIGNS)
class CommentsInThreadsAndStatus(NeovimHarness, unittest.TestCase):
    def a_review_with_a_thread_on_line_two(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.tid = self.a_thread("Why not an f-string?")
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("2")
        return nvim

    def test_leader_ra_adds_a_comment_to_the_thread_on_the_cursors_line_and_it_shows_inline(self):
        nvim = self.a_review_with_a_thread_on_line_two()

        nvim.keys("<leader>ra")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertIn("comment on thread at app.py:2", nvim.compose_float()["title"])
        nvim.write_text("Because of the diff\n\nand the tests")
        nvim.command("write")

        wait_for("the comment", lambda: len(self.thread(self.tid)["comments"]) == 2)
        self.assertEqual(self.comments(self.tid)[1], ("comment", "Because of the diff\n\nand the tests"))
        self.assertEqual(len(self.api("GET", "/api/threads")), 1, "a comment in the thread, not a new thread")
        wait_for("the comment drawn", lambda: "and the tests" in "\n".join(nvim.threads()[0]["lines"]))

    def test_a_comment_in_a_thread_keeps_its_unsent_text_apart_from_a_new_comment_on_the_same_line(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        nvim.keys("<leader>ra")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("my comment in the thread")
        nvim.keys("<Esc>q")

        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], [""])
        nvim.keys("<Esc>q")
        nvim.keys("<leader>ra")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], ["my comment in the thread"])

    def test_leader_rR_resolves_and_leader_rO_reopens_the_thread_on_the_line(self):
        nvim = self.a_review_with_a_thread_on_line_two()

        nvim.keys("<leader>rR")
        wait_for("resolved", lambda: self.thread(self.tid)["status"] == "resolved")
        wait_for("drawn as one line", lambda: len(nvim.threads()[0]["lines"]) == 1)
        nvim.keys("<leader>rR")
        nvim.keys("<leader>rO")

        wait_for("reopened", lambda: self.thread(self.tid)["status"] == "open")
        self.assertIn("No open thread on this line", nvim.messages())
        nvim.keys("<leader>rO")
        self.assertIn("No resolved or dismissed thread on this line", nvim.messages())

    def test_on_a_line_with_no_thread_each_says_so_and_opens_nothing(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        nvim.command("1")

        for keys in ("<leader>ra", "<leader>rR", "<leader>rO"):
            nvim.keys(keys)

        self.assertEqual(nvim.messages().count("No thread on this line"), 3)
        self.assertIsNone(nvim.compose_float())
        self.assertEqual(self.thread(self.tid)["status"], "open")

    def test_with_two_threads_on_a_line_it_asks_which_to_comment_in_or_resolve(self):
        nvim = self.a_review_with_a_thread_on_line_two()
        second = self.a_thread("Second opinion")
        wait_for("both threads", lambda: len(nvim.threads()) == 2)
        nvim.lua("vim.ui.select = function(items, _, choose) for _, t in ipairs(items) do if t.id == '%s' then return choose(t) end end end" % second)

        nvim.keys("<leader>rR")
        wait_for("resolved", lambda: self.thread(second)["status"] == "resolved")
        self.assertEqual(self.thread(self.tid)["status"], "open")
        nvim.keys("<leader>rO")
        wait_for("reopened", lambda: self.thread(second)["status"] == "open")
        nvim.keys("<leader>ra")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("To the second")
        nvim.command("write")
        wait_for("the comment", lambda: len(self.thread(second)["comments"]) == 2)
        self.assertEqual(len(self.thread(self.tid)["comments"]), 1)


@needs(MISSING_GITSIGNS)
class GeneralThreads(NeovimHarness, unittest.TestCase):
    def test_leader_rG_writes_a_general_thread_with_no_anchor(self):
        nvim = self.an_open_review()
        self.batched()

        nvim.keys("<leader>rG")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertIn("general", nvim.compose_float()["title"])
        nvim.write_text("The tests need a case for an empty name")
        nvim.command("write")

        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        thread = self.api("GET", "/api/threads")[0]
        self.assertIsNone(thread["anchor"])
        self.assertEqual(thread["comments"][0]["body"], "The tests need a case for an empty name")

    def test_a_general_thread_keeps_its_unsent_text_too(self):
        nvim = self.an_open_review()
        nvim.keys("<leader>rG")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("Later")
        nvim.keys("<Esc>q")

        nvim.keys("<leader>rG")

        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], ["Later"])

    def test_it_works_from_a_buffer_that_is_not_a_file(self):
        nvim = self.an_open_review()
        self.batched()
        nvim.command("enew")

        nvim.keys("<leader>rG")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("From an empty buffer")
        nvim.command("write")

        wait_for("the thread", lambda: self.api("GET", "/api/threads"))
        self.assertIsNone(self.api("GET", "/api/threads")[0]["anchor"])


class ReviewOfTwoFiles(NeovimHarness):
    """app.py (changed on the branch: line 2) and util.py (new), with threads on both and a general one."""

    def a_review_of_two_files(self, before=None):
        self.write("util.py", "def shout(text):\n    return text.upper()\n\n\ndef whisper(text):\n    return text.lower()\n")
        self.commit()
        self.start_watcher()
        self.batched()
        self.general = self.api("POST", "/api/threads", {"anchor": None, "body": "Overall: add tests"})["id"]
        self.in_app = self.a_thread("Why not an f-string?", line=2)
        self.in_util = self.a_thread("Name this better", line=1, file="util.py")
        self.later_in_util = self.a_thread("Cover whisper", line=6, file="util.py")
        nvim = self.nvim(before=before)
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        return nvim

    def settle(self, nvim, where):
        wait_for(f"the cursor at {where}", lambda: nvim.at() == where)


@needs(MISSING_GITSIGNS)
class ThreadMotions(ReviewOfTwoFiles, unittest.TestCase):
    def test_r_visits_every_open_thread_in_order_across_files_and_wraps_to_the_general_thread_first(self):
        nvim = self.a_review_of_two_files()
        nvim.command("1")

        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("]r")
        self.settle(nvim, ["util.py", 1])
        nvim.keys("]r")
        self.settle(nvim, ["util.py", 6])
        self.assertNotIn("Wrapped", nvim.messages())
        nvim.keys("]r")

        wait_for("the general thread", lambda: nvim.float_lines())
        self.assertIn("Overall: add tests", nvim.float_lines())
        self.assertIn("Wrapped to the first open thread", nvim.messages())
        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        self.assertIsNone(nvim.float_lines(), "going to a line closes the general thread's float")
        self.assertEqual(nvim.messages().count("Wrapped"), 1)

    def test_the_other_way_goes_back_and_wraps_to_the_last_thread(self):
        nvim = self.a_review_of_two_files()
        nvim.command("edit util.py")
        nvim.command("6")

        nvim.keys("[r")
        self.settle(nvim, ["util.py", 1])
        nvim.keys("[r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("[r")
        wait_for("the general thread", lambda: nvim.float_lines())
        self.assertNotIn("Wrapped", nvim.messages())
        nvim.keys("[r")

        self.settle(nvim, ["util.py", 6])
        self.assertIn("Wrapped to the last open thread", nvim.messages())

    def test_from_a_buffer_that_is_not_a_file_it_starts_at_the_first_or_the_last_thread(self):
        nvim = self.a_review_of_two_files()
        nvim.command("enew")

        nvim.keys("]r")
        wait_for("the general thread", lambda: nvim.float_lines())
        nvim.keys("q")
        nvim.command("enew")
        nvim.keys("[r")

        self.settle(nvim, ["util.py", 6])
        self.assertNotIn("Wrapped", nvim.messages())

    def test_resolved_and_dismissed_threads_are_skipped_and_without_open_ones_it_says_so(self):
        nvim = self.a_review_of_two_files()
        self.api("PATCH", f"/api/threads/{self.in_util}/status", {"status": "resolved"})
        self.api("PATCH", f"/api/threads/{self.later_in_util}/status", {"status": "dismissed"})
        nvim.command("1")

        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("]r")
        wait_for("the general thread", lambda: nvim.float_lines())
        for tid in (self.general, self.in_app):
            self.api("PATCH", f"/api/threads/{tid}/status", {"status": "resolved"})
        nvim.keys("q")
        nvim.keys("]r")

        wait_for("the message", lambda: "No open threads" in nvim.messages())

    def test_two_threads_on_one_line_are_both_visited(self):
        nvim = self.a_review_of_two_files()
        second = self.a_thread("Second opinion", line=2)
        wait_for("both drawn", lambda: len(nvim.threads()) == 2)
        nvim.command("1")

        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("]r")
        self.settle(nvim, ["util.py", 1])

        self.assertEqual(self.thread(second)["status"], "open")

    def test_a_thread_moved_by_an_unsaved_edit_is_found_where_it_is_drawn(self):
        nvim = self.a_review_of_two_files()
        nvim.command("1")
        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, 0, false, { '# new', '# lines' })")  # the thread moves to line 4
        wait_for("it moved", lambda: nvim.signs() == [(4, "●")])

        nvim.keys("]r")

        self.settle(nvim, ["app.py", 4])

    def test_it_says_so_with_no_review_open_and_maps_the_keys_from_opts(self):
        self.commit()
        nvim = self.nvim(opts={"poll_ms": 200, "keys": {"next": "<leader>jn"}})

        nvim.keys("<leader>jn")

        self.assertIn("No review is open", nvim.messages())
        self.assertEqual(nvim.lua("return vim.fn.maparg(']r', 'n')"), "")

    def test_a_thread_on_code_another_branch_has_is_reached_through_its_float_not_a_line(self):
        nvim = self.a_review_of_two_files()
        nvim.command("1")
        git(self.repo, self.env, "checkout", "-q", "-b", "other", "main")
        wait_for("the threads not in view", lambda: all(t.get("inView") is False for t in self.api("GET", "/api/threads?view=") if t["anchor"]))

        nvim.keys("]r")

        wait_for("the general thread", lambda: nvim.float_lines())
        self.assertIn("Overall: add tests", nvim.float_lines())


@needs(MISSING_GITSIGNS)
class ThePickers(ReviewOfTwoFiles, unittest.TestCase):
    def test_leader_rs_lists_every_thread_with_status_and_state_general_ones_at_the_top(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.api("PATCH", f"/api/threads/{self.in_util}/status", {"status": "resolved", "reviewer": "security-bot"})
        outdated = self.a_thread("Is this the style we want?", line=3, anchor_code="Another style")
        second_general = self.api("POST", "/api/threads", {"anchor": None, "body": "Also: a changelog"})["id"]
        self.api("PATCH", f"/api/threads/{second_general}/status", {"status": "dismissed"})

        nvim.keys("<leader>rs")

        wait_for("the picker", lambda: nvim.menu())
        menu = nvim.menu()
        self.assertEqual(menu["via"], "ui.select")
        self.assertEqual(menu["title"], "Review threads")
        self.assertEqual(menu["lines"], [
            "● general · open · held until you submit · Overall: add tests",
            "○ general · dismissed by Test · Also: a changelog",
            "● app.py:2 · open · held until you submit · Why not an f-string?",
            "● app.py:3 · open · held until you submit · outdated · Is this the style we want?",
            "● util.py:6 · open · held until you submit · Cover whisper",
            "○ util.py:1 · resolved by security-bot · Name this better",
        ])
        self.assertIsNotNone(outdated)

    def test_picking_a_line_thread_goes_to_it_in_its_file(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())

        nvim.pick(4)

        self.settle(nvim, ["util.py", 6])

    def test_picking_a_general_thread_opens_it_in_the_float_where_comment_resolve_and_reopen_act_on_it(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())

        nvim.pick(1)

        wait_for("the float", lambda: nvim.float_lines())
        self.assertIn("Overall: add tests", nvim.float_lines())
        nvim.keys("<leader>rR")
        wait_for("resolved", lambda: self.thread(self.general)["status"] == "resolved")
        wait_for("the float says so", lambda: nvim.float_lines()[0].startswith("# ○ resolved"))
        nvim.keys("<leader>rO")
        wait_for("reopened", lambda: self.thread(self.general)["status"] == "open")
        wait_for("the float says so", lambda: nvim.float_lines()[0].startswith("# ● open"))
        nvim.keys("<leader>ra")
        wait_for("the compose float", lambda: nvim.compose_float())
        self.assertIn("comment on a general thread", nvim.compose_float()["title"])
        nvim.write_text("Tests are in")
        nvim.command("write")
        wait_for("the comment", lambda: len(self.thread(self.general)["comments"]) == 2)
        self.assertEqual(self.comments(self.general)[1], ("comment", "Tests are in"))

    def test_leader_rf_lists_the_changed_files_with_viewed_ones_marked_and_opens_the_picked_one(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.api("PUT", "/api/viewed", {"file": "util.py"})

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        menu = nvim.menu()
        self.assertEqual(menu["title"], "Changed files")
        self.assertEqual(menu["lines"], ["  app.py  +1 −1", "✓ util.py  +6 −0 · viewed"])
        nvim.pick(2)
        self.settle(nvim, ["util.py", 1])

    def test_a_deleted_file_is_listed_and_says_it_has_nothing_to_open(self):
        os.remove(os.path.join(self.repo, "app.py"))
        self.write("util.py", "x = 1\n")
        self.commit("Drop app")
        self.start_watcher()
        nvim = self.nvim(self.repo, "util.py", before=FAKE_SELECT)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")

        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  app.py  +0 −2", "  util.py  +1 −0"])
        nvim.pick(1)

        self.assertIn("app.py was deleted: there is no file to open", nvim.messages())
        self.assertEqual(nvim.at()[0], "util.py")

    def test_with_snacks_both_pickers_go_through_snacks_picker(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)

        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["via"], "snacks")
        self.assertEqual(nvim.menu()["title"], "Review threads")
        self.assertEqual(nvim.menu()["lines"][0], "● general · open · held until you submit · Overall: add tests")
        nvim.pick(2)
        self.settle(nvim, ["app.py", 2])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())

        self.assertEqual(nvim.menu()["title"], "Changed files")
        self.assertEqual(nvim.menu()["via"], "snacks")
        nvim.pick(2)
        self.settle(nvim, ["util.py", 1])

    def test_with_no_review_open_each_says_so(self):
        self.commit()
        nvim = self.nvim(before=FAKE_SELECT)

        nvim.keys("<leader>rs")
        nvim.keys("<leader>rf")

        self.assertEqual(nvim.messages().count("No review is open"), 2)
        self.assertIsNone(nvim.menu())

    def test_with_no_threads_it_says_so_and_opens_no_picker(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rs")

        wait_for("the message", lambda: "No threads in this review" in nvim.messages())
        self.assertIsNone(nvim.menu())

    def test_the_motions_and_pickers_change_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        nvim.command("1")
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        nvim.keys("]r")
        self.settle(nvim, ["app.py", 2])
        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)
        wait_for("the float", lambda: nvim.float_lines())
        nvim.keys("q")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)
        nvim.keys("[r")
        wait_for("the float", lambda: nvim.float_lines())
        nvim.keys("q")

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)


@needs(MISSING_GITSIGNS)
class WhenTheReviewApiFails(NeovimHarness, unittest.TestCase):
    def test_a_stopped_watcher_shows_an_error_and_keeps_the_float_and_its_text(self):
        nvim = self.an_open_review()
        nvim.command("2")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("Do not lose me")
        self.stop_watcher()

        nvim.command("write")

        wait_for("the error", lambda: "No difftate is running for" in nvim.messages())
        self.assertEqual(nvim.compose_float()["lines"], ["Do not lose me"], "the float stays, with its text")
        nvim.keys("<Esc>q")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        self.assertEqual(nvim.compose_float()["lines"], ["Do not lose me"])

    def test_a_refusal_from_the_api_is_shown_as_it_says_and_the_float_and_text_stay(self):
        self.commit()
        self.start_watcher()
        tid = self.a_thread_in_a_run()
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        # The branch changes under the review while a run keeps the watcher on it: the API refuses new threads
        git(self.repo, self.env, "checkout", "-q", "-b", "other", "main")
        nvim.command("2")
        nvim.keys("<leader>rc")
        wait_for("the float", lambda: nvim.compose_float())
        nvim.write_text("Refused")

        nvim.command("write")

        wait_for("the API's own words", lambda: "another branch is checked out" in nvim.messages())
        self.assertEqual(nvim.compose_float()["lines"], ["Refused"])
        self.assertEqual([t["id"] for t in self.api("GET", "/api/threads")], [tid], "nothing was posted")
        self.release_agent()

    def a_thread_in_a_run(self):
        """A live thread whose run is still going (the fake agent waits to be released)."""
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        return tid
