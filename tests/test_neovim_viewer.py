"""Seam: the Neovim viewer (GLOSSARY.md), driven as the reviewer drives it.

Each test starts the real watcher with the fake agent in a temporary git
repository on the branch "feature" (test_watcher.Harness), then a headless
Neovim in that folder with only the plugin (and gitsigns) loaded, from
tests/nvim/init.lua: never the reviewer's config or data, as HOME and every
XDG folder point into the temporary folder. The test runs commands and presses
keys in that Neovim through its --listen socket (msgpack-RPC: tests/nvim_rpc.py),
and checks what the reviewer would see: gitsigns' base and hunks, the plugin's messages and its status note.

Needs `nvim` (0.10 or later) on PATH, and DIFFTATE_TEST_GITSIGNS naming a
gitsigns.nvim checkout for the tests that check gitsigns; they skip without.
With DIFFTATE_TEST_NVIM_REQUIRED=1 (CI's Neovim job) they fail instead.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nvim_rpc  # noqa: E402
from test_watcher import FAKE_AGENT, Harness, git, wait_for, with_folder  # noqa: E402

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


# The agent part of the status note (" · agent fake"): most tests are about the rest of the note
AGENT_PART = re.compile(r" · agent [^·\n]*?(?= ·|$|\n)", re.M)


class Neovim:
    """A headless Neovim in <folder>, started with tests/nvim/init.lua."""

    def __init__(self, test, folder, args=(), opts=None, gitsigns=True, extra_rtp=(), before=None):
        self.test = test
        self.socket = os.path.join(test.tmp, f"nvim-{len(test.neovims)}.sock")
        self.rpc = None
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
        except (OSError, AssertionError):
            return False

    def expr(self, expr, timeout=10):
        """What the Vim expression <expr> gives, as text (as `nvim --remote-expr` prints it). Asked over one
        connection to the --listen socket, opened again after Neovim didn't answer in <timeout> seconds."""
        try:
            if self.rpc is None:
                self.rpc = nvim_rpc.Client(self.socket, timeout)
            value = self.rpc.request("nvim_eval", expr, timeout=timeout)
        except nvim_rpc.RpcError as e:
            raise AssertionError(f"nvim_eval {expr} failed: {e}")
        except OSError:
            self.close_rpc()  # an answer that comes late would be read as the next one's
            raise
        return value if isinstance(value, str) else str(value)

    def close_rpc(self):
        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None

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
        """Press <keys> in normal mode (<leader> is the space, as in LazyVim). The screen is drawn first, as
        Neovim draws it before it waits for a key: what the reviewer sees when pressing one (the width of
        an automatic sign column, say, is known only once it is drawn)."""
        self.lua(f"vim.cmd('redraw'); vim.api.nvim_feedkeys(vim.keycode({vim_string(keys)}), 'mx', false)")

    def messages(self):
        """:messages, with the agent part of the status note left out like status() does."""
        return AGENT_PART.sub("", self.lua("return vim.fn.execute('messages')"))

    def note(self):
        """The plugin's status note, as a statusline shows it."""
        return self.lua("return require('difftate').status()")

    def status(self):
        """The status note without its agent part (" · agent fake"): ReviewAgent says what that part is, the
        other tests say what the rest is."""
        return AGENT_PART.sub("", self.note())

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

    def boxes(self, buf=0):
        """The threads drawn in buffer <buf> as boxes: for each thread, its lines as {"text", "width" (display
        columns, with the padding), "hls" (the highlight of each chunk)}."""
        return self.lua(f"return T.boxes({buf})")

    def look(self, buf=0):
        """The diff look drawn in buffer <buf>: {"deleted": [{"row", "above", "lines", "widths", "hls",
        "priority"} of the deleted text, top to bottom], "tinted": [(line, highlight)]}."""
        look = self.lua(f"return T.look({buf})")
        return {"deleted": look["deleted"], "tinted": [tuple(t) for t in look["tinted"]]}

    def screen(self):
        """What the screen shows now, a string per row."""
        return self.lua("return T.screen()")

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
        self.close_rpc()
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

    def branch_changes(self, name, before, after, base_commit="Add the file"):
        """The file <name> holds <before> on main and <after> on the branch feature (committed), which
        replaces the change the harness leaves uncommitted in app.py."""
        git(self.repo, self.env, "checkout", "-q", "--", "app.py")
        git(self.repo, self.env, "checkout", "-q", "main")
        self.write(name, before)
        self.commit(base_commit)
        git(self.repo, self.env, "checkout", "-q", "-B", "feature")
        self.write(name, after)
        self.commit("Change the file")

    def shapes(self):
        """shapes.py: its second line is changed, its fourth deleted, a line added after the fifth
        (the fourth of the branch); gitsigns sees three hunks."""
        self.branch_changes("shapes.py", SHAPES_BEFORE, SHAPES_AFTER)

    def open_shapes(self, **kwargs):
        """The review open on shapes.py (the Neovim started on it, gitsigns on the base with its three hunks)."""
        self.start_watcher()
        nvim = self.nvim(None, "shapes.py", **kwargs)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        wait_for("the three hunks", lambda: nvim.hunks() == [[1, 1], [0, 1], [1, 0]])
        return nvim

    def a_thread_in_a_run(self):
        """A live thread whose run is still going (the fake agent waits to be released)."""
        tid = self.open_thread("Why an f-string here?")["id"]
        wait_for("a working progress note", lambda: self.note(tid, "progress", "Working"))
        return tid

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

        wait_for("the message", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())
        self.assertIsNone(self.running_pid(), "and it started nothing")
        self.assertIsNone(nvim.gitsigns_base())
        self.assertEqual(nvim.status(), "")

    def test_finding_the_one_watcher_or_none_changes_no_option_or_key_and_starts_nothing(self):
        # #158 adds no key: the keys it adds are the ones of setting it up (test_setting_it_up_...).
        # With no watcher, <leader>rr says so; nothing starts. With one, the first request naming
        # a folder adds it, and the reviewer's window stays as it was.
        self.commit()
        nvim = self.nvim()
        self.attached(nvim)
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        settings = nvim.lua("return T.settings()")

        nvim.keys("<leader>rr")

        wait_for("the message", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())
        self.assertIsNone(self.running_pid(), "Neovim never starts the watcher")
        self.assertFalse(os.path.exists(os.path.join(self.difftate_home, "api.json")))
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)
        self.assertEqual(nvim.lua("return T.settings()"), settings)

        folder = self.add_worktree("tidy")
        self.commit("Greet with hey", folder=folder)
        self.start_watcher()  # a watcher that serves the repository, not the worktree yet
        worktree = self.nvim(folder)
        self.attached(worktree)
        wtree_window = worktree.lua("return vim.api.nvim_get_current_win()")
        wtree_before = worktree.lua(f"return T.snapshot({wtree_window})")

        worktree.keys("<leader>rr")

        wait_for("the review of the worktree", lambda: "git signs show changes since main" in worktree.status())
        worktree.keys("<leader>rr")  # closed again
        wait_for("gitsigns on the index", lambda: worktree.gitsigns_base() is None)
        self.assertEqual(worktree.lua(f"return T.snapshot({wtree_window})"), wtree_before)
        self.assertEqual(self.api("GET", "/api/review", folder=folder)["branch"], "tidy")

    def test_it_points_gitsigns_at_where_the_branch_left_the_base_and_says_so(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        self.assertEqual(self.attached(nvim), [], "the change is committed: nothing differs from the index")

        nvim.command("DifftateOpen")

        wait_for("gitsigns on the base", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        wait_for("the review's hunk", lambda: nvim.hunks() == [[1, 1]])
        self.assertEqual(nvim.status(), "review open · live · git signs show changes since main")
        wait_for("the note in the messages", lambda: "review open · live · git signs show changes since main" in nvim.messages())

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
        self.assertEqual(self.difftate("--base", "feature", folder=folder).returncode, 0)
        nvim = self.nvim(folder)
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("gitsigns on the worktree's base", lambda: nvim.gitsigns_base() == self.head(folder, "main"))
        self.assertEqual(nvim.status(), "review open · live · git signs show changes since feature")


@needs(MISSING_NVIM)
class WithoutGitsigns(NeovimHarness, unittest.TestCase):
    def test_without_gitsigns_it_opens_the_review_and_says_signs_are_missing(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(gitsigns=False)

        nvim.command("DifftateOpen")

        # "live" joins the line a moment after the review opens: wait for the whole line
        line = "review open · live · gitsigns isn't loaded: no git signs for changes since main"
        wait_for("the whole status line", lambda: nvim.status() == line)


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
            "review open · live · git signs show changes since main",
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
        self.assertEqual(nvim.status(), "review open · live · git signs show changes since main")

    def test_a_store_changed_outside_difftate_is_notified_once_as_a_warning_and_changes_no_option_or_key(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Add a docstring")
        nvim = self.nvim()
        self.attached(nvim)
        before = nvim.lua("return T.snapshot()")
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.lua("T.notes = {}; vim.notify = function(m, level, o) table.insert(T.notes, { m, level, o and o.title }) end")
        path = next(os.path.join(top, "events.jsonl") for top, _, names in os.walk(os.path.join(self.repo, ".git"))
                    if os.path.basename(top) == self.api("GET", "/api/review")["id"] and "events.jsonl" in names)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(text.replace("Add a docstring", "Fine."))

        wait_for("the notification", lambda: any("changed outside" in n[0] for n in nvim.lua("return T.notes")))
        time.sleep(1)  # five more polls, each still carrying the warning

        notes = [n for n in nvim.lua("return T.notes") if "changed outside" in n[0]]
        self.assertEqual(len(notes), 1, f"shown once: {notes}")
        self.assertIn("changed outside difftate", notes[0][0])
        self.assertEqual(notes[0][1], 3, "at warning level (vim.log.levels.WARN)")
        self.assertEqual(notes[0][2], "difftate")
        nvim.command("DifftateClose")
        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua("return T.snapshot()"), before)

    def disk(self, name, text, folder=None):
        with open(os.path.join(folder or self.repo, name), "w") as f:
            f.write(text)

    def first_line(self, nvim, name="app.py"):
        return nvim.lua(f"return vim.api.nvim_buf_get_lines(vim.fn.bufnr({vim_string(name)}), 0, 1, false)[1]")

    def test_a_file_a_run_changed_reloads_within_a_poll_without_a_focus_change_or_an_option(self):
        nvim = self.an_open_review()
        before = nvim.lua("return T.snapshot()")

        self.disk("app.py", "print('a run wrote this, and it is longer')\n")

        wait_for("the buffer to reload", lambda: "a run wrote this" in self.first_line(nvim))
        after = nvim.lua("return T.snapshot()")
        # Neovim's own reload runs the filetype plugin again (buffer options): those aren't the plugin's
        is_global = lambda options: {k: v for k, v in options.items() if not k.startswith("b:")}
        self.assertEqual(is_global(after["options"]), is_global(before["options"]))
        self.assertEqual(after["keys"], before["keys"])

    def test_a_buffer_with_unsaved_edits_is_not_overwritten_and_the_warning_comes_once(self):
        nvim = self.an_open_review()
        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, 1, false, { 'unsaved edit' })")
        nvim.command("messages clear")

        self.disk("app.py", "print('a run wrote this, and it is longer')\n")
        time.sleep(1)  # five polls

        self.assertEqual(self.first_line(nvim), "unsaved edit")
        self.assertLessEqual(nvim.messages().count("W12"), 1, nvim.messages())

    def test_a_file_outside_the_reviews_folder_is_left_alone(self):
        outside = os.path.join(self.tmp, "outside")
        os.mkdir(outside)
        self.disk("notes.txt", "old\n", outside)
        nvim = self.an_open_review()
        nvim.command("edit " + os.path.join(outside, "notes.txt"))
        nvim.command("edit app.py")

        self.disk("notes.txt", "new and longer\n", outside)
        time.sleep(1)

        self.assertEqual(self.first_line(nvim, os.path.join(outside, "notes.txt")), "old")

    def test_an_error_while_checking_is_not_shown(self):
        nvim = self.an_open_review()
        nvim.lua("T.checks = 0; local c = vim.cmd; vim.cmd = function(x) "
                 "if type(x) == 'string' and x:find('checktime') then T.checks = T.checks + 1; error('E11: boom') end; return c(x) end")
        nvim.command("messages clear")

        wait_for("a poll to check", lambda: nvim.lua("return T.checks") >= 2)

        self.assertNotIn("boom", nvim.messages())

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
        self.assertEqual(nvim.status(), "review open · live · git signs show changes since main")
        nvim.command("DifftateClose")
        nvim.command("messages clear")

        self.start_watcher()
        time.sleep(1)  # five polls, were it still polling: one would reach this watcher
        self.stop_watcher()
        time.sleep(1)  # and five more would find it stopped

        self.assertNotIn("difftate stopped answering", nvim.messages())


SHAPES_BEFORE = "one = 1\ntwo = 2\nthree = 3\nfour = 4\nfive = 5\nsix = 6\n"
SHAPES_AFTER = "one = 1\ntwo = 22\nthree = 3\nfive = 5\nfive_and_a_half = 5.5\nsix = 6\n"


# Pickers that record what they were given (T.menu) and wait for the test to choose (T.choose_menu)
FAKE_SELECT = ("vim.ui.select = function(items, opts, on_choice) T.menu = { via = 'ui.select', title = opts.prompt, "
               "lines = vim.tbl_map(function(i) return opts.format_item and opts.format_item(i) or tostring(i) end, items) }; "
               "T.choose_menu = function(n) on_choice(items[n], n) end end")
# The files sidebar (source difftate_files) is a long-lived picker: T.sidebar_picker is it (closed once the
# plugin closes it), T.sidebar what it was given, T.sidebar_lines() the rows its finder gives now, T.sidebar_choose(n)
# Enter on a row. It never lands in T.menu: that is the pop-up pickers'.
FAKE_SIDEBAR = ("local p = { closed = false, main = vim.api.nvim_get_current_win() }; "
                "function p:close() self.closed = true end; "
                "function p:find() T.sidebar_finds = (T.sidebar_finds or 0) + 1 end; "
                "T.sidebar_picker = p; T.sidebar_opened = (T.sidebar_opened or 0) + 1; "
                "T.sidebar = { title = o.title, layout = o.layout, preview = o.preview, auto_close = o.auto_close }; "
                "T.sidebar_lines = function() return vim.tbl_map(function(i) return i.text end, o.finder({}, {})) end; "
                "T.sidebar_choose = function(n) o.confirm(p, o.finder({}, {})[n]) end; "
                "if o.on_show then o.on_show({ list = { count = function() return #o.finder({}, {}) end, "
                "move = function(_, n) T.sidebar.cursor = n end } }) end; return p")
FAKE_SNACKS = ("_G.Snacks = { picker = { pick = function(o) if o.source == 'difftate_files' then " + FAKE_SIDEBAR + " end; "
               "T.menu = { via = 'snacks', title = o.title, "
               "lines = vim.tbl_map(function(i) return i.text end, o.items), preview = o.preview, "
               "win = o.win, previews = vim.tbl_map(function(i) return i.preview and i.preview.text or false end, o.items) }; "
               "T.choose_menu = function(n) o.confirm({ close = function() end }, o.items[n]) end; "
               "if o.on_show then o.on_show({ list = { count = function() return #o.items end, "
               "move = function(_, n, absolute) T.menu.cursor = n; T.menu.absolute = absolute end } }) end end } }")

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
        nvim = self.nvim(opts={"poll_ms": 200, "keys": {"toggle": "<leader>gR"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rr', 'n')"), "")

        nvim.keys("<leader>gR")

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
            "threads": "<leader>gP", "files": "<leader>gF", "next": "<leader>gN", "previous": "<leader>gB",
            "mode": "<leader>gM", "agent": "<leader>gH", "submit": "<leader>gU", "done": "<leader>gD", "export": "<leader>gX", "viewed": "<leader>gV", "views": "<leader>gW",
            "browser": "<leader>gY", "side_by_side": "<leader>gZ", "files_sidebar": "<leader>gQ"}})

        self.assertEqual(nvim.lua("return require('which-key').added"), [])

    def test_setting_it_up_changes_no_option_and_only_adds_its_key(self):
        nvim = self.nvim()

        before, after = nvim.lua("return T.before"), nvim.lua("return T.after_setup")

        self.assertEqual(after["options"], before["options"])
        self.assertEqual(set(after["keys"]) - set(before["keys"]), {"n  rr", "n  re", "n  rt", "n  rc", "x  rc", "n  ra", "n  rR", "n  rO", "n  rG",
                                                                 "n  rs", "n  rf", "n ]r", "n [r", "n  rM", "n  rA", "n  rS", "n  rD", "n  rE", "n  rv", "n  rV",
                                                                 "n  rB", "n  rd", "n  rF"})
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
        wait_for("drawn in full again", lambda: len(nvim.threads()[0]["lines"]) > 1)
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
        if before == FAKE_SNACKS:
            # The sidebar read the changeset when the review opened, and the watcher keeps what it read for a
            # second: a test that writes files next wants to see them in the next picker
            time.sleep(1.2)
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

    def a_review_path(self, text):
        """review-path.md in the folder, kept out of the changeset as the "write a review path" skill does."""
        exclude = os.path.join(self.repo, ".git", "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a") as f:
            f.write("review-path.md\n")
        nvim = self.neovims[-1]
        shown = nvim.lua("return T.sidebar_lines and T.sidebar_lines()")
        self.write("review-path.md", text)
        if shown is not None:
            # The sidebar polls the watcher, which keeps what it read for a second: once the sidebar shows the path,
            # the next picker reads it too
            wait_for("the sidebar to show the path", lambda: nvim.lua("return T.sidebar_lines()") != shown)

    def test_leader_rf_follows_the_review_path_with_each_stops_first_question_then_the_other_files(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.a_review_path("---\nbranch: feature\ncreatedAt: 2026-11-22T06:10:00Z\n---\n\n"
                           "## 1 `util.py:1-2` ★\n\n### What does shout do?\nUpper-cases.\n\n"
                           "### Why a helper?\nTwo callers.\n")
        self.api("PUT", "/api/viewed", {"file": "util.py"})

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["title"], "Changed files")
        self.assertEqual(nvim.menu()["lines"], ["✓ 1 util.py ★ · What does shout do?", "Not on the path",
                                                "  └─ app.py  +1 −1"])
        nvim.pick(1)
        self.settle(nvim, ["util.py", 1])

    def test_leader_rf_draws_the_path_as_a_tree_with_side_files_child_stops_skipped_and_not_on_the_path(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        for name in ("util.css", "tips.py", "more.py", "uv.lock"):
            self.write(name, "x\n")
        self.a_review_path("## 1 `util.py` ★\n\n### What does shout do?\nUpper-cases.\n\n"
                           "### Side file: `util.css`\nStyle.\n\n"
                           "## 1.1 `tips.py`\n\n### Where do tips come from?\nA list.\n\n"
                           "## 1.2 `more.py` ★\n\n### Why more?\nBecause.\n\n"
                           "## Skipped\n- `uv.lock` — lockfile only\n")
        self.api("PUT", "/api/viewed", {"file": "util.py"})
        self.api("PUT", "/api/viewed", {"file": "util.css"})
        self.api("PUT", "/api/viewed", {"file": "more.py"})

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], [
            "✓ 1 util.py ★ · What does shout do?",
            "✓ ├─ util.css",
            "  ├─ 1.1 tips.py · Where do tips come from?",
            "✓ └─ 1.2 more.py ★ · Why more?",
            "Skipped",
            "  └─ uv.lock — lockfile only",
            "Not on the path",
            "  └─ app.py  +1 −1"])

    def test_a_stop_under_a_stop_under_a_stop_continues_its_parents_lines(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        for name in ("a.py", "b.py", "c.py", "d.py"):
            self.write(name, "x\n")
        self.a_review_path("## 1 `util.py`\n\n### Q?\nA.\n\n## 1.1 `a.py`\n\n### Q?\nA.\n\n"
                           "## 1.1.1 `b.py`\n\n### Q?\nA.\n\n## 1.2 `c.py`\n\n### Q?\nA.\n\n"
                           "## 2 `d.py`\n\n### Q?\nA.\n\n## Skipped\n- `app.py` — reviewed\n")

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], [
            "  1 util.py · Q?", "  ├─ 1.1 a.py · Q?", "  │  └─ 1.1.1 b.py · Q?", "  └─ 1.2 c.py · Q?",
            "  2 d.py · Q?", "Skipped", "  └─ app.py — reviewed"])

    def test_picking_a_heading_does_nothing(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.a_review_path("## 1 `util.py`\n\n### Q?\nA.\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        where = nvim.at()

        nvim.pick(2)
        time.sleep(0.5)

        self.assertEqual(nvim.at(), where)
        self.assertIsNone(nvim.lua("return T.err"))

    def test_with_snacks_the_picker_previews_a_stop_with_its_questions_specs_side_files_and_the_section_it_points_to(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.write("util.css", "x\n")
        self.a_review_path("## 1 `util.py:5-6` ★\nSpec: `test_util.py` \"shouts\"\n\n### What does shout do?\nUpper-cases.\n\n"
                           "### Why a helper?\nTwo callers. See \"State flow\".\n\n### Side file: `util.css:2-4`\nStyle.\n\n"
                           "## Section: State flow\nIt starts idle.\n\n## Skipped\n- `app.py` — one line\n")

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        menu = nvim.menu()
        self.assertEqual(menu["preview"], "preview")
        self.assertEqual(menu["previews"][0], "\n".join([
            "# 1 util.py ★", "Lines 5-6", "", "## What does shout do?", "Upper-cases.", "",
            "## Why a helper?", 'Two callers. See "State flow".', "",
            "## Spec", '- test_util.py "shouts"', "",
            "## Side file", "- util.css (lines 2-4): Style.", "",
            "## State flow", "It starts idle."]))
        self.assertEqual(menu["previews"][1], "# util.css (lines 2-4)\nSide file of 1 util.py\n\nStyle.")
        self.assertEqual(menu["lines"][2:], ["Skipped", "  └─ app.py — one line"])
        self.assertEqual(menu["previews"][3], "# app.py\nSkipped: one line")

    def test_with_no_review_path_the_picker_has_no_preview(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertFalse(nvim.menu()["preview"])
        self.assertEqual(nvim.menu()["previews"], ["", ""])

    def test_the_picker_opens_with_the_cursor_on_the_row_of_the_file_the_buffer_shows(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.a_review_path("## 1 `util.py`\n\n### Q?\nA.\n")
        nvim.command("edit app.py")

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  1 util.py · Q?", "Not on the path", "  └─ app.py  +1 −1"])
        self.assertEqual((nvim.menu()["cursor"], nvim.menu()["absolute"]), (3, True))

    def test_the_picker_starts_on_its_first_row_when_the_buffer_is_no_file_of_the_review(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.a_review_path("## 1 `util.py`\n\n### Q?\nA.\n")
        nvim.command("enew")

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertNotIn("cursor", nvim.menu())

    def test_enter_opens_the_file_at_the_stops_first_range(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.a_review_path("## 1 `util.py:5-6,1-2`\n\n### Q?\nA.\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())

        nvim.pick(1)

        self.settle(nvim, ["util.py", 5])

    def test_enter_opens_a_stop_that_names_no_range_at_the_files_first_change(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.a_review_path("## 1 `app.py`\n\n### Q?\nA.\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())

        nvim.pick(1)

        self.settle(nvim, ["app.py", 2])

    def test_enter_opens_a_side_file_at_its_range_and_a_file_not_on_the_path_at_its_first_change(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.write("util.css", "a\nb\nc\nd\n")
        self.a_review_path("## 1 `util.py`\n\n### Q?\nA.\n\n### Side file: `util.css:3-4`\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(2)
        self.settle(nvim, ["util.css", 3])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())

        nvim.pick(4)

        self.settle(nvim, ["app.py", 2])

    def test_with_snacks_only_the_pickers_own_preview_window_wraps_long_lines_at_word_breaks(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.a_review_path("## 1 `util.py:5-6` ★\n\n### Q?\nA very long answer.\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["win"], {"preview": {"wo": {"wrap": True, "linebreak": True}}})

    def test_following_the_review_path_with_snacks_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        """Adds only: the preview and the cursor row belong to the picker; opening at a range moves the cursor and nothing else."""
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.a_review_path("## 1 `util.py:5-6` ★\nSpec: `t.py` \"x\"\n\n### Q?\nA. See \"Flow\".\n\n## Section: Flow\ntext\n")
        nvim.command("1")
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        settings = nvim.lua("return T.settings()")
        foreign = nvim.lua("return T.foreign_extmarks(0)")

        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)
        self.settle(nvim, ["util.py", 5])

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)
        self.assertEqual(nvim.lua("return T.settings()"), settings)
        self.assertEqual(nvim.lua("return T.foreign_extmarks(0)"), foreign)

    def test_a_rewritten_review_path_shows_on_the_next_leader_rf_and_skipped_files_are_listed_with_their_reasons(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.a_review_path("## 1 `util.py`\n\n### What does shout do?\nUpper-cases.\n")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.lua("T.menu = nil")

        self.write("review-path.md", "## 1 `app.py`\n\n### Why the f-string?\nIt reads better.\n\n"
                                     "## 2 `util.py`\n\n### Who calls it?\napp.py.\n")
        nvim.keys("<leader>rf")

        wait_for("the new path", lambda: (nvim.menu() or {}).get("lines") == [
            "  1 app.py · Why the f-string?", "  2 util.py · Who calls it?"])
        nvim.lua("T.menu = nil")
        self.write("review-path.md", "## 1 `util.py`\n\n### Who calls it?\napp.py.\n\n"
                                     "## Skipped\n- `app.py` — one line, reviewed before\n")
        nvim.keys("<leader>rf")
        wait_for("the skipped file listed", lambda: (nvim.menu() or {}).get("lines") == [
            "  1 util.py · Who calls it?", "Skipped", "  └─ app.py — one line, reviewed before"])

    def test_a_broken_review_path_is_warned_about_once_and_leader_rf_lists_the_changesets_order_until_fixed(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        nvim.lua("T.notes = {}; vim.notify = function(m, level, o) table.insert(T.notes, { m, level, o and o.title }) end")
        before = nvim.lua("return T.snapshot()")
        self.a_review_path("## 1 `util.py`\n\n### What does shout do?\nUpper-cases.\n\n"
                           "## 2 `gone.py`\n\n### Why?\nBecause.\n")

        wait_for("the warning", lambda: any("gone.py" in n[0] for n in nvim.lua("return T.notes")))
        time.sleep(1)  # more polls, each still carrying it
        notes = [n for n in nvim.lua("return T.notes") if "review-path.md" in n[0]]
        self.assertEqual(len(notes), 1, f"shown once: {notes}")
        self.assertEqual((notes[0][1], notes[0][2]), (3, "difftate"), "at warning level, titled difftate")
        self.assertIn("not in the changeset", notes[0][0])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  app.py  +1 −1", "  util.py  +6 −0"], "the changeset's order")

        nvim.lua("T.menu = nil")
        self.write("review-path.md", "## 1 `util.py`\n\n### What does shout do?\nUpper-cases.\n")
        nvim.keys("<leader>rf")
        wait_for("the path again", lambda: (nvim.menu() or {}).get("lines") == [
            "  1 util.py · What does shout do?", "Not on the path", "  └─ app.py  +1 −1"])
        self.assertEqual(self.api("GET", "/api/review")["warnings"], [], "a fixed file clears the warning")
        self.assertEqual(nvim.lua("return T.snapshot()"), before, "the warning changed no option or key")

    def test_following_the_review_path_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        """Adds only: the tree, with its side files, child stops, headings and the groups, draws in the picker
        and sets no option, key, gitsigns setting or foreign extmark on the reviewer's own buffers and windows."""
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)
        self.write("util.css", "x\n")
        self.write("tips.py", "x\n")
        self.a_review_path("## 1 `util.py` ★\n\n### What does shout do?\nUpper-cases.\n\n### Side file: `util.css`\n\n"
                           "## 1.1 `tips.py`\n\n### Tips?\nA list.\n\n## Skipped\n- `app.py` — one line\n")
        nvim.command("1")
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        settings = nvim.lua("return T.settings()")
        foreign = nvim.lua("return T.foreign_extmarks(0)")

        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)  # a stop
        self.settle(nvim, ["util.py", 1])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(4)  # a heading: nothing happens
        nvim.command("buffer app.py")

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)
        self.assertEqual(nvim.lua("return T.settings()"), settings)
        self.assertEqual(nvim.lua("return T.foreign_extmarks(0)"), foreign)

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
class TheFilesSidebar(ReviewOfTwoFiles, unittest.TestCase):
    """#215: the changed files on the right, open when a review opens, <leader>rF shows or hides it."""

    def sidebar_lines(self, nvim):
        return nvim.lua("return T.sidebar_lines and T.sidebar_lines()")

    def is_open(self, nvim):
        return nvim.lua("return T.sidebar_picker ~= nil and not T.sidebar_picker.closed")

    def test_a_review_opening_shows_it_on_the_right_with_the_rows_of_the_picker_and_no_preview(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        self.api("PUT", "/api/viewed", {"file": "util.py"})

        wait_for("the sidebar", lambda: self.is_open(nvim))

        sidebar = nvim.lua("return T.sidebar")
        self.assertEqual(sidebar["title"], "Changed files")
        self.assertEqual(sidebar["layout"], {"preset": "right", "preview": False})
        self.assertFalse(sidebar["preview"])
        self.assertFalse(sidebar["auto_close"], "Enter must leave it open")
        wait_for("the viewed mark", lambda: self.sidebar_lines(nvim) == ["  app.py  +1 −1", "✓ util.py  +6 −0 · viewed"])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], self.sidebar_lines(nvim))

    def test_it_follows_the_review_path_like_the_picker(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        exclude = os.path.join(self.repo, ".git", "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a") as f:
            f.write("review-path.md\n")
        self.write("review-path.md", "## 1 `util.py` ★\n\n### What does shout do?\nUpper-cases.\n")

        wait_for("the path rows", lambda: self.sidebar_lines(nvim) == [
            "  1 util.py ★ · What does shout do?", "Not on the path", "  └─ app.py  +1 −1"])

    def test_leader_rF_hides_it_and_shows_it_again(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))

        nvim.keys("<leader>rF")
        wait_for("it hidden", lambda: not self.is_open(nvim))
        nvim.keys("<leader>rF")

        wait_for("it shown again", lambda: nvim.lua("return T.sidebar_opened") == 2 and self.is_open(nvim))
        wait_for("its rows", lambda: self.sidebar_lines(nvim) == ["  app.py  +1 −1", "  util.py  +6 −0"])

    def test_leader_rf_stays_the_popup_picker(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))
        nvim.lua("T.sidebar_opened = 0")

        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["title"], "Changed files")
        self.assertEqual(nvim.menu()["lines"], ["  app.py  +1 −1", "  util.py  +6 −0"])
        self.assertEqual(nvim.lua("return T.sidebar_opened"), 0, "the key opens no second sidebar")
        self.assertTrue(self.is_open(nvim), "and does not hide this one")

    def test_enter_on_a_row_opens_the_file_in_the_main_window_and_keeps_the_sidebar(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))
        main = nvim.lua("return vim.api.nvim_get_current_win()")
        # as in Snacks, the sidebar is the current window while it is used
        nvim.lua("vim.cmd('vnew'); T.sidebar_picker.main = " + str(main))

        nvim.lua("T.sidebar_choose(2)")

        wait_for("util.py in the main window", lambda: nvim.lua(
            f"return vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf({main})):match('[^/]*$')") == "util.py")
        self.assertEqual(nvim.lua("return vim.api.nvim_get_current_win()"), main)
        self.assertTrue(self.is_open(nvim))

    def test_a_heading_row_does_nothing(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        exclude = os.path.join(self.repo, ".git", "info", "exclude")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        with open(exclude, "a") as f:
            f.write("review-path.md\n")
        self.write("review-path.md", "## 1 `util.py`\n\n### Q?\nA.\n")
        wait_for("the path rows", lambda: len(self.sidebar_lines(nvim) or []) == 3)
        where = nvim.at()

        nvim.lua("T.sidebar_choose(2)")
        time.sleep(0.5)

        self.assertEqual(nvim.at(), where)
        self.assertTrue(self.is_open(nvim))

    def test_a_viewed_mark_shows_within_a_poll(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))

        self.api("PUT", "/api/viewed", {"file": "app.py"})

        wait_for("the mark", lambda: self.sidebar_lines(nvim) == ["✓ app.py  +1 −1 · viewed", "  util.py  +6 −0"])

    def test_it_refreshes_only_when_the_rows_changed(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))
        wait_for("its rows", lambda: self.sidebar_lines(nvim))
        time.sleep(1)  # several polls
        before = nvim.lua("return T.sidebar_finds or 0")

        time.sleep(1)

        self.assertEqual(nvim.lua("return T.sidebar_finds or 0"), before)

    def test_closing_the_review_closes_it(self):
        nvim = self.a_review_of_two_files(before=FAKE_SNACKS)
        wait_for("the sidebar", lambda: self.is_open(nvim))

        nvim.command("DifftateClose")

        wait_for("it closed", lambda: not self.is_open(nvim))
        nvim.keys("<leader>rF")
        self.assertIn("No review is open", nvim.messages())
        self.assertFalse(self.is_open(nvim))

    def test_without_snacks_the_review_opens_and_the_key_says_a_sidebar_needs_it(self):
        nvim = self.a_review_of_two_files(before=FAKE_SELECT)

        nvim.keys("<leader>rF")

        wait_for("the message", lambda: "needs Snacks" in nvim.messages())
        self.assertNotEqual(nvim.status(), "")
        self.assertNotIn("Error", nvim.messages())


@needs(MISSING_GITSIGNS)
class ReviewModeAndSubmit(NeovimHarness, unittest.TestCase):
    LIVE = "review open · live · git signs show changes since main"

    def batched_note(self, held):
        return f"review open · batched · {held} held · git signs show changes since main"

    def a_review_with_threads(self, count=2, before=None):
        """A batched review open in Neovim with <count> held threads (on app.py's line 2, then 1, ...)."""
        self.commit()
        self.start_watcher()
        self.batched()
        self.held = [self.a_thread(f"Held thread {n}", line=1 + n % 2) for n in range(count)]
        nvim = self.nvim(before=before)
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        return nvim

    def mode(self):
        return self.api("GET", "/api/mode")

    def no_run_started(self):
        time.sleep(1.5)  # the watcher looks every 0.2 s
        self.assertEqual((self.prompts(), self.dispatches()), ([], 0))

    # The mode ----------------------------------------------------------------

    def test_leader_rM_switches_a_live_review_to_batched_and_back_and_the_note_shows_each(self):
        nvim = self.an_open_review()
        self.assertEqual(nvim.status(), self.LIVE)
        nvim.command("messages clear")

        nvim.keys("<leader>rM")

        wait_for("the message", lambda: "Batched: comments are held until you submit" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "batched", "held": []})
        self.assertEqual(nvim.status(), self.batched_note(0))
        nvim.keys("<leader>rM")
        wait_for("the message", lambda: "Live: comments go to the coding agent as you write them" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "live", "held": []})
        self.assertEqual(nvim.status(), self.LIVE)
        self.no_run_started()

    def test_switching_to_live_submits_what_is_held_and_says_how_many(self):
        nvim = self.a_review_with_threads(2)
        nvim.command("messages clear")

        nvim.keys("<leader>rM")

        wait_for("the message", lambda: "Live: 2 held threads submitted to the coding agent" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "live", "held": []})
        self.assertEqual({self.state(tid) for tid in self.held} & {"held"}, set(), "none is held any more")
        wait_for("one run for both", lambda: len(self.prompts()) == 1)
        self.assertEqual(nvim.status(), self.LIVE)
        self.release_agent()

    def test_one_held_thread_is_said_in_the_singular(self):
        nvim = self.a_review_with_threads(1)
        nvim.command("messages clear")

        nvim.keys("<leader>rM")

        wait_for("the message", lambda: "Live: 1 held thread submitted to the coding agent" in nvim.messages())
        self.release_agent()

    def test_the_mode_the_reviewer_sees_is_the_review_apis_not_a_flag_of_the_plugins(self):
        nvim = self.an_open_review()
        self.batched()  # another viewer switched it
        nvim.command("messages clear")

        nvim.keys("<leader>rM")  # so this switches it back to live

        wait_for("the message", lambda: "Live: comments go to the coding agent as you write them" in nvim.messages())
        self.assertEqual(self.mode()["mode"], "live")

    # Submit ------------------------------------------------------------------

    def test_leader_rS_submits_the_held_threads_as_one_run_and_the_review_stays_batched(self):
        nvim = self.a_review_with_threads(2)
        self.assertIn("held until you submit", "\n".join(nvim.threads()[0]["lines"]))
        nvim.command("messages clear")

        nvim.keys("<leader>rS")

        wait_for("the message", lambda: "Submitted 2 held threads" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "batched", "held": []})
        wait_for("one run", lambda: len(self.prompts()) == 1)
        wait_for("the note", lambda: nvim.status() == self.batched_note(0))
        wait_for("the threads no longer held", lambda: all(
            "held until you submit" not in "\n".join(t["lines"]) for t in nvim.threads()))
        self.release_agent()

    def test_submitting_one_held_thread_is_said_in_the_singular(self):
        nvim = self.a_review_with_threads(1)
        nvim.command("messages clear")

        nvim.keys("<leader>rS")

        wait_for("the message", lambda: any(line.endswith("Submitted 1 held thread") for line in nvim.messages().splitlines()))
        self.release_agent()

    def test_submitting_with_nothing_held_says_so_and_starts_no_run(self):
        nvim = self.an_open_review()
        self.batched()
        wait_for("the note", lambda: nvim.status() == self.batched_note(0))
        nvim.command("messages clear")

        nvim.keys("<leader>rS")

        wait_for("the message", lambda: "Nothing is held: nothing to submit" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "batched", "held": []})
        self.no_run_started()

    def test_submitting_a_live_review_says_it_is_not_batched_and_starts_no_run(self):
        nvim = self.an_open_review()
        nvim.command("messages clear")

        nvim.keys("<leader>rS")

        wait_for("the message", lambda: "Not a batched review: nothing to submit" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "live", "held": []})
        self.no_run_started()

    # Held --------------------------------------------------------------------

    def test_a_comment_in_a_batched_review_is_held_inline_and_in_the_threads_picker(self):
        nvim = self.an_open_review(nvim=None)
        self.batched()
        wait_for("the note", lambda: nvim.status() == self.batched_note(0))
        nvim.command("2")
        nvim.lua(FAKE_SELECT)
        nvim.command("messages clear")

        nvim.keys("<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Name the greeting first")
        nvim.command("write")

        wait_for("the message", lambda: "Comment held until you submit" in nvim.messages())
        thread = self.drawn(nvim, [2])[0]
        self.assertIn("● open · held until you submit", thread["lines"][0])
        self.assertEqual(self.api("GET", "/api/threads")[0]["state"], "held")
        wait_for("the count in the note", lambda: nvim.status() == self.batched_note(1))
        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["● app.py:2 · open · held until you submit · Name the greeting first"])
        self.no_run_started()

    def test_a_comment_in_a_thread_of_a_batched_review_is_held_too_and_in_a_live_one_it_is_sent(self):
        nvim = self.a_review_with_threads(1)
        nvim.command("1")  # where the one held thread is
        nvim.command("messages clear")

        nvim.keys("<leader>ra")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("And again")
        nvim.command("write")

        wait_for("the message", lambda: "Comment held until you submit" in nvim.messages())
        nvim.keys("<leader>rM")
        wait_for("live", lambda: self.mode()["mode"] == "live")
        nvim.command("messages clear")
        nvim.keys("<leader>ra")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Now live")
        nvim.command("write")

        wait_for("the message", lambda: "Comment sent" in nvim.messages())
        self.release_agent()

    def test_a_comment_in_a_live_review_says_it_was_sent_not_held(self):
        nvim = self.an_open_review()
        nvim.command("2")
        nvim.command("messages clear")

        nvim.keys("<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Live comment")
        nvim.command("write")

        wait_for("the message", lambda: "Comment sent" in nvim.messages())
        self.assertNotIn("held", nvim.messages())
        self.release_agent()

    def test_the_note_follows_threads_held_or_submitted_in_another_viewer(self):
        nvim = self.an_open_review()
        self.batched()
        wait_for("batched", lambda: nvim.status() == self.batched_note(0))

        self.a_thread("From the browser", line=1)
        self.a_thread("Another", line=2)
        wait_for("two held", lambda: nvim.status() == self.batched_note(2))
        self.api("POST", "/api/submit", {})
        wait_for("none held", lambda: nvim.status() == self.batched_note(0))
        self.api("PUT", "/api/mode", {"mode": "live"})
        wait_for("live", lambda: nvim.status() == self.LIVE)
        self.release_agent()

    def test_the_note_without_gitsigns_names_the_mode_too(self):
        self.commit()
        self.start_watcher()
        self.batched()
        nvim = self.nvim(gitsigns=False)

        nvim.command("DifftateOpen")

        # The note names the mode once the plugin has asked for it, just after the review opens
        note = "review open · batched · 0 held · gitsigns isn't loaded: no git signs for changes since main"
        wait_for("the note", lambda: nvim.status() == note)

    # Where there is nothing to do ----------------------------------------------

    def test_with_no_review_open_each_key_says_so_and_asks_nothing(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        nvim.command("messages clear")

        nvim.keys("<leader>rM")
        nvim.keys("<leader>rS")

        wait_for("both messages", lambda: "No review is open: open it to switch the review mode" in nvim.messages()
                 and "No review is open: open it to submit" in nvim.messages())
        self.assertEqual(self.mode(), {"mode": "live", "held": []})

    def test_a_stopped_watcher_is_said_for_each_key(self):
        nvim = self.an_open_review()
        self.stop_watcher()
        nvim.command("messages clear")

        nvim.keys("<leader>rM")
        nvim.keys("<leader>rS")

        wait_for("the error", lambda: nvim.messages().count("No difftate is running: run `difftate` in a terminal") == 2)

    # The browser is a stand-in that records the URL it is asked to open (vim.ui.open, which
    # `open` or xdg-open runs in a real Neovim): nothing opens a browser in a test
    RECORD_BROWSER = ("_G.difftate_opened = {}; vim.ui.open = function(url) "
                      "table.insert(_G.difftate_opened, url) end")

    def test_leader_rB_opens_the_folders_review_in_the_browser_with_a_launch_code(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(before=self.RECORD_BROWSER)
        self.attached(nvim)

        nvim.keys("<leader>rB")

        opened = wait_for("the browser to be asked", lambda: nvim.lua("return _G.difftate_opened") or None)
        self.assertTrue(opened, nvim.messages())
        [link] = opened
        self.assertRegex(link, rf"^http://127\.0\.0\.1:{self.port}/\?launch=[\w-]+&folder=[\w%.-]+$")
        self.assertIn("folder=" + urllib.parse.quote(os.path.realpath(self.repo), safe=""), link, "the link names the folder")
        self.assertNotIn(self.token, link, "the review token never leaves its file")
        self.assertIsNone(nvim.gitsigns_base(), "the review isn't opened here: <leader>rB asks for nothing else")

    def test_the_browser_key_comes_from_opts_keys_false_maps_none_and_a_taken_one_stays_theirs(self):
        nvim = self.nvim(opts={"keys": {"browser": "<leader>gY", "side_by_side": "<leader>gZ", "files_sidebar": "<leader>gQ"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rB', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gY', 'n')"), "")
        unmapped = self.nvim(opts={"keys": {"browser": False}})
        self.assertEqual(unmapped.lua("return vim.fn.maparg('<leader>rB', 'n')"), "")
        taken = self.nvim(before="vim.keymap.set('n', '<leader>rB', '<cmd>echo \"mine\"<cr>', { desc = 'Mine' })")
        self.assertEqual(taken.lua("return vim.fn.maparg('<leader>rB', 'n')"), '<Cmd>echo "mine"<CR>')
        self.assertIn("<leader>rB is already mapped (Mine): set opts.keys.browser to another key", taken.messages())

    def test_leader_rB_with_no_watcher_says_so_and_opens_nothing(self):
        self.commit()
        nvim = self.nvim(before=self.RECORD_BROWSER)
        self.attached(nvim)
        nvim.command("messages clear")

        nvim.keys("<leader>rB")

        wait_for("the message", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())
        self.assertEqual(nvim.lua("return #_G.difftate_opened"), 0)
        self.assertIsNone(self.running_pid(), "and it started nothing")

    def test_a_refusal_from_the_api_is_shown_as_it_says(self):
        nvim = self.an_open_review()
        self.batched()
        wait_for("the note", lambda: nvim.status() == self.batched_note(0))
        nvim.lua("require('difftate.api').request = (function(real) return function(watcher, method, path, on_answer, payload)"
                 " if method == 'POST' and path == '/api/submit' then"
                 " vim.schedule(function() on_answer(nil, { message = 'only a reviewer submits a review' }) end) return end"
                 " return real(watcher, method, path, on_answer, payload) end end)(require('difftate.api').request)")
        self.a_thread("Held", line=1)
        wait_for("the note", lambda: nvim.status() == self.batched_note(1))
        nvim.command("messages clear")

        nvim.keys("<leader>rS")

        wait_for("the API's own words", lambda: "only a reviewer submits a review" in nvim.messages())
        self.assertEqual(len(self.mode()["held"]), 1, "nothing was submitted")

    # The keys ----------------------------------------------------------------

    def test_the_keys_come_from_opts_keys_and_false_maps_none(self):
        nvim = self.nvim(opts={"poll_ms": 200, "keys": {"mode": "<leader>rm", "submit": "<leader>ru"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rM', 'n')"), "")
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rS', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>rm', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>ru', 'n')"), "")
        unmapped = self.nvim(opts={"keys": {"mode": False, "submit": False}})
        self.assertEqual(unmapped.lua("return vim.fn.maparg('<leader>rM', 'n')"), "")
        self.assertEqual(unmapped.lua("return vim.fn.maparg('<leader>rS', 'n')"), "")

    def test_a_key_another_plugin_mapped_stays_its_and_it_says_which_option_to_change(self):
        nvim = self.nvim(before="vim.keymap.set('n', '<leader>rM', '<cmd>echo \"mine\"<cr>', { desc = 'Mine' });"
                                "vim.keymap.set('n', '<leader>rS', '<cmd>echo \"also\"<cr>', { desc = 'Also' })")

        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rM', 'n')"), '<Cmd>echo "mine"<CR>')
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rS', 'n')"), '<Cmd>echo "also"<CR>')
        self.assertIn("<leader>rM is already mapped (Mine): set opts.keys.mode to another key", nvim.messages())
        self.assertIn("<leader>rS is already mapped (Also): set opts.keys.submit to another key", nvim.messages())

    def test_the_mode_and_submit_keys_change_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.a_review_with_threads(2)
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        nvim.keys("<leader>rS")  # submits the two
        wait_for("the submit", lambda: self.mode()["held"] == [])
        nvim.keys("<leader>rS")  # nothing held
        wait_for("the message", lambda: "Nothing is held" in nvim.messages())
        nvim.keys("<leader>rM")  # batched -> live
        wait_for("live", lambda: self.mode()["mode"] == "live")
        nvim.keys("<leader>rS")  # not batched
        wait_for("the message", lambda: "Not a batched review" in nvim.messages())
        nvim.keys("<leader>rM")  # live -> batched
        wait_for("batched", lambda: self.mode()["mode"] == "batched")

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)
        self.release_agent()


@needs(MISSING_GITSIGNS)
class ReviewAgent(NeovimHarness, unittest.TestCase):
    """GET and PUT /api/agent in Neovim: the agent in the statusline note, and the picker on <leader>rA that sets
    the review's own agent, or clears it. Two agents run the same fake with different folders: which one ran
    shows in the folder it wrote to."""

    def setUp(self):
        super().setUp()
        self.dirs = {name: os.path.join(self.tmp, f"agent-{name}") for name in ("alpha", "beta")}
        for folder in self.dirs.values():
            os.makedirs(folder)
            with open(os.path.join(folder, "go"), "w"):
                pass
        self.write_agent_list('default = "alpha"\n' + "".join(
            f'[agents.{name}]\ntool = "claude"\ncmd = "{FAKE_AGENT}"\nenv = {{ FAKE_AGENT_DIR = "{folder}" }}\n'
            for name, folder in self.dirs.items()))

    def ran(self, name):
        try:
            with open(os.path.join(self.dirs[name], "prompts")) as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0

    def chosen(self):
        return self.api("GET", "/api/agent")

    def expected_note(self, agent, source=""):
        return f"review open · live · agent {agent}{source} · git signs show changes since main"

    def test_the_note_names_the_agent_that_replies_and_says_when_it_is_this_reviews_own(self):
        nvim = self.an_open_review()
        wait_for("the note", lambda: nvim.note() == self.expected_note("alpha"))

        self.api("PUT", "/api/agent", {"agent": "beta"})  # another viewer's choice
        wait_for("the note", lambda: nvim.note() == self.expected_note("beta", " (this review)"))

        self.api("PUT", "/api/agent", {"agent": ""})
        wait_for("the note", lambda: nvim.note() == self.expected_note("alpha"))

    def test_leader_rA_lists_the_agents_and_choosing_one_sets_it_for_this_review_only(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)
        nvim.command("messages clear")

        nvim.keys("<leader>rA")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["title"], "Review agent")
        self.assertEqual(nvim.menu()["lines"], ["Default: alpha (the machine's)", "alpha", "beta"])
        nvim.pick(3)
        wait_for("the message", lambda: "beta replies in this review, from the next run" in nvim.messages())
        self.assertEqual(self.chosen(), {"agent": "beta", "source": "review", "names": ["alpha", "beta"]})
        self.assertEqual(nvim.note(), self.expected_note("beta", " (this review)"))
        self.open_thread("Why an f-string here?")
        wait_for("beta's run", lambda: self.ran("beta") == 1)
        self.assertEqual(self.ran("alpha"), 0)

    def test_the_picker_marks_the_reviews_own_agent_and_its_first_entry_clears_the_choice(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)
        self.api("PUT", "/api/agent", {"agent": "beta"})
        wait_for("the note", lambda: "(this review)" in nvim.note())
        nvim.command("messages clear")

        nvim.keys("<leader>rA")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["Default (clears this review's choice)", "alpha", "beta (this review)"])
        nvim.pick(1)
        wait_for("the message", lambda: "The review's own agent is cleared: alpha replies, from the next run" in nvim.messages())
        self.assertEqual(self.chosen()["source"], "machine")
        wait_for("the note", lambda: nvim.note() == self.expected_note("alpha"))

    def test_choosing_what_the_review_has_already_asks_nothing_of_the_watcher(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)
        nvim.command("messages clear")

        nvim.keys("<leader>rA")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)  # the default, which it has

        wait_for("the message", lambda: "The review has no agent of its own: alpha replies" in nvim.messages())
        self.assertEqual(self.chosen()["source"], "machine")

    def test_with_no_review_open_it_says_so(self):
        nvim = self.nvim(before=FAKE_SELECT)

        nvim.keys("<leader>rA")

        self.assertIn("No review is open: open it to choose the agent", nvim.messages())
        self.assertIsNone(nvim.menu())

    def test_a_list_that_cant_be_read_leaves_the_note_without_an_agent_and_the_key_says_why(self):
        self.write_agent_list("this is not toml [")
        self.commit()
        self.start_watcher()
        nvim = self.nvim(before=FAKE_SELECT)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.command("messages clear")

        nvim.keys("<leader>rA")

        wait_for("the message", lambda: "could not read the agent list" in nvim.messages())
        self.assertIsNone(nvim.menu())
        self.assertNotIn(" · agent ", nvim.note())

    def test_the_key_comes_from_opts_keys_and_false_maps_none(self):
        nvim = self.nvim(opts={"keys": {"agent": "<leader>rg"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rA', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>rg', 'n')"), "")
        off = self.nvim(opts={"keys": {"agent": False}})
        self.assertEqual(off.lua("return vim.fn.maparg('<leader>rA', 'n')"), "")

    def test_a_key_another_plugin_mapped_stays_its_and_it_says_which_option_to_change(self):
        nvim = self.nvim(before="vim.keymap.set('n', '<leader>rA', '<cmd>echo \"mine\"<cr>', { desc = 'Mine' })")

        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rA', 'n')"), '<Cmd>echo "mine"<CR>')
        self.assertIn("<leader>rA is already mapped (Mine): set opts.keys.agent to another key", nvim.messages())

    def test_the_key_and_the_note_change_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.an_open_review(nvim=self.nvim(before=FAKE_SNACKS))
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        nvim.keys("<leader>rA")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(3)
        wait_for("beta", lambda: self.chosen()["agent"] == "beta")
        nvim.keys("<leader>rA")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)
        wait_for("alpha", lambda: self.chosen()["agent"] == "alpha")

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)


@needs(MISSING_GITSIGNS)
class ReviewDone(NeovimHarness, unittest.TestCase):
    mode = "live"

    @property
    def LIVE(self):
        return f"review open · {self.mode} · git signs show changes since main"

    def done(self):
        return self.api("GET", "/api/done")

    def done_note(self, commit=None):
        return f"review open · {self.mode} · Done at {(commit or self.head())[:7]} · git signs show changes since main"

    def a_review_with_an_open_thread(self, nvim=None):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Is this right?", line=2)  # held: the review stays batched, so no run is working
        self.mode = "batched · 1 held"
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        return nvim

    def stub_put_done(self, nvim, message):
        nvim.lua("require('difftate.api').request = (function(real) return function(watcher, method, path, on_answer, payload)"
                 " if method == 'PUT' and path == '/api/done' then"
                 f" vim.schedule(function() on_answer(nil, {{ message = {vim_string(message)} }}) end) return end"
                 " return real(watcher, method, path, on_answer, payload) end end)(require('difftate.api').request)")

    # Mark and undo -------------------------------------------------------------

    def test_leader_rD_marks_the_review_done_says_the_commit_and_the_note_shows_it(self):
        nvim = self.an_open_review()
        self.assertEqual(nvim.status(), self.LIVE)
        nvim.command("messages clear")

        nvim.keys("<leader>rD")

        commit = self.head()
        wait_for("the message", lambda: f"Done at {commit[:7]}. A new commit clears it." in nvim.messages())
        self.assertEqual((self.done()["done"], self.done()["commit"]), (True, commit))
        self.assertEqual(nvim.status(), self.done_note())

    def test_the_key_again_undoes_it_and_says_so(self):
        nvim = self.an_open_review()
        nvim.keys("<leader>rD")
        wait_for("done", lambda: nvim.status() == self.done_note())
        nvim.command("messages clear")

        nvim.keys("<leader>rD")

        wait_for("the message", lambda: f"Done at {self.head()[:7]} undone" in nvim.messages())
        self.assertFalse(self.done()["done"])
        self.assertEqual(nvim.status(), self.LIVE)

    def test_the_note_follows_done_marked_or_undone_in_another_viewer(self):
        nvim = self.an_open_review()

        self.api("PUT", "/api/done", {"done": True})
        wait_for("done", lambda: nvim.status() == self.done_note())
        self.api("PUT", "/api/done", {"done": False})
        wait_for("not done", lambda: nvim.status() == self.LIVE)

    def test_a_new_commit_clears_done_and_the_note_follows(self):
        nvim = self.an_open_review()
        nvim.keys("<leader>rD")
        wait_for("done", lambda: nvim.status() == self.done_note())

        self.write("app.py", "greeting = 'a new commit'\n")
        self.commit("Another change")

        wait_for("the note without Done", lambda: nvim.status() == self.LIVE)
        self.assertEqual(self.done()["lastMark"]["kind"], "cleared")
        nvim.command("messages clear")
        nvim.keys("<leader>rD")  # marks it again, at the new commit
        wait_for("the message", lambda: f"Done at {self.head()[:7]}." in nvim.messages())

    def test_nothing_is_asked_when_nothing_is_open(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rD")

        wait_for("done", lambda: self.done()["done"])
        self.assertIsNone(nvim.menu(), "no question when nothing is open")

    # The warning -----------------------------------------------------------------

    def test_open_threads_are_warned_about_and_stopping_marks_nothing(self):
        nvim = self.a_review_with_an_open_thread()
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rD")

        wait_for("the question", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["title"], "1 thread still open. Mark Done anyway?")
        self.assertEqual(nvim.menu()["lines"], ["Mark Done anyway", "Stop"])
        nvim.pick(2)
        time.sleep(0.5)
        self.assertFalse(self.done()["done"])
        self.assertEqual(nvim.status(), self.LIVE)

    def test_going_on_after_the_warning_marks_it_done(self):
        nvim = self.a_review_with_an_open_thread()
        nvim.lua(FAKE_SELECT)
        nvim.keys("<leader>rD")
        wait_for("the question", lambda: nvim.menu())

        nvim.pick(1)

        wait_for("done", lambda: nvim.status() == self.done_note())
        self.assertEqual(self.done()["openThreads"], 1, "the thread stays open: Done warns, it gates nothing")

    def test_a_run_in_flight_is_warned_about_with_the_open_threads(self):
        self.commit()
        self.start_watcher()
        self.a_thread_in_a_run()
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rD")

        wait_for("the question", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["title"], "1 thread still open · 1 run still working. Mark Done anyway?")
        self.release_agent()

    def test_undoing_done_asks_nothing_even_with_threads_open(self):
        nvim = self.a_review_with_an_open_thread()
        self.api("PUT", "/api/done", {"done": True})
        wait_for("done", lambda: nvim.status() == self.done_note())
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rD")

        wait_for("not done", lambda: not self.done()["done"])
        self.assertIsNone(nvim.menu())

    # Errors ------------------------------------------------------------------------

    def test_a_409_and_a_403_are_shown_as_the_api_says(self):
        nvim = self.an_open_review()
        for message in ("another branch is checked out: go back to feature to mark it Done",
                        "only a reviewer marks a review Done"):
            self.stub_put_done(nvim, message)
            nvim.command("messages clear")

            nvim.keys("<leader>rD")

            wait_for("the API's own words", lambda: message in nvim.messages())
            self.assertFalse(self.done()["done"])
            self.assertEqual(nvim.status(), self.LIVE)

    def test_with_no_review_open_it_says_so_and_asks_nothing(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        nvim.command("messages clear")

        nvim.keys("<leader>rD")

        wait_for("the message", lambda: "No review is open: open it to mark it Done" in nvim.messages())
        self.assertFalse(self.done()["done"])

    def test_a_stopped_watcher_is_said(self):
        nvim = self.an_open_review()
        self.stop_watcher()
        nvim.command("messages clear")

        nvim.keys("<leader>rD")

        wait_for("the error", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())

    def test_a_watcher_that_has_no_done_route_shows_no_done_and_no_error(self):
        nvim = self.an_open_review()
        nvim.lua("require('difftate.api').request = (function(real) return function(watcher, method, path, on_answer, payload)"
                 " if path == '/api/done' then vim.schedule(function() on_answer(nil, { message = 'GET /api/done: 404' }) end) return end"
                 " return real(watcher, method, path, on_answer, payload) end end)(require('difftate.api').request)")
        nvim.command("messages clear")

        time.sleep(1)  # some polls

        self.assertEqual(nvim.status(), self.LIVE)
        self.assertNotIn("404", nvim.messages())

    # The key -----------------------------------------------------------------------

    def test_the_key_comes_from_opts_keys_and_false_maps_none(self):
        nvim = self.nvim(opts={"keys": {"done": "<leader>gD"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rD', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gD', 'n')"), "")
        unmapped = self.nvim(opts={"keys": {"done": False}})
        self.assertEqual(unmapped.lua("return vim.fn.maparg('<leader>rD', 'n')"), "")

    def test_a_key_another_plugin_mapped_stays_its_and_it_says_which_option_to_change(self):
        nvim = self.nvim(before="vim.keymap.set('n', '<leader>rD', '<cmd>echo \"mine\"<cr>', { desc = 'Mine' })")

        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rD', 'n')"), '<Cmd>echo "mine"<CR>')
        self.assertIn("<leader>rD is already mapped (Mine): set opts.keys.done to another key", nvim.messages())

    def test_the_done_key_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.a_review_with_an_open_thread()
        nvim.lua(FAKE_SELECT)
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        nvim.keys("<leader>rD")  # the question
        wait_for("the question", lambda: nvim.menu())
        nvim.pick(1)  # marks it
        wait_for("done", lambda: self.done()["done"])
        nvim.keys("<leader>rD")  # undoes it
        wait_for("not done", lambda: not self.done()["done"])

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

        wait_for("the error", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())
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

def screen_row(screen, text, after=0):
    """The first row of <screen> (from the row <after>) that is <text>: a line of the file after the signs
    before it ("┃ two = 22"), or a line of a thread when <text> starts with its bar."""
    for i in range(after, len(screen)):
        row = screen[i]
        if text.startswith("│") and text in row or not text.startswith("│") and "│" not in row and row.strip().endswith(text):
            return i
    raise AssertionError(f"{text!r} is not on the screen after row {after}:\n" + "\n".join(screen))


@needs(MISSING_GITSIGNS)
class TheDiffLook(NeovimHarness, unittest.TestCase):
    """While the review is open, a buffer shows what changed against the base: the deleted text where it
    was, the added and changed lines tinted (GitHub's unified look) and the threads in a box."""

    def test_deleted_text_is_drawn_where_it_was_in_the_delete_colour_the_width_of_the_window(self):
        self.shapes()

        nvim = self.open_shapes()

        deleted = wait_for("the deleted text", lambda: len(nvim.look()["deleted"]) == 2 and nvim.look()["deleted"])
        self.assertEqual([(d["row"], d["above"], d["lines"]) for d in deleted],
                         [(2, True, ["two = 2"]), (4, True, ["four = 4"])],
                         "above the line after the change: the line before has its threads under it")
        window = nvim.lua("return vim.api.nvim_win_get_width(0)")
        for block in deleted:
            self.assertEqual(block["widths"], [window], "the tint spans the window")
            self.assertEqual(block["hls"], [["DifftateDeleted", "DifftateDeleted"]])

    def test_deleted_text_at_the_top_of_the_file_is_drawn_above_its_first_line(self):
        self.branch_changes("shapes.py", "zero = 0\none = 1\n", "one = 1\n")
        self.start_watcher()
        nvim = self.nvim(None, "shapes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        deleted = wait_for("the deleted text", lambda: nvim.look()["deleted"])
        self.assertEqual([(d["row"], d["above"], d["lines"]) for d in deleted], [(1, True, ["zero = 0"])])

    def test_tabs_in_deleted_text_are_drawn_as_the_spaces_the_buffer_would_show(self):
        self.branch_changes("shapes.py", "one = 1\n\tindented = 2\nthree = 3\n", "one = 1\nthree = 3\n")
        self.start_watcher()
        nvim = self.nvim(None, "shapes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        deleted = wait_for("the deleted text", lambda: nvim.look()["deleted"])
        self.assertEqual(deleted[0]["lines"], [" " * nvim.lua("return vim.bo.tabstop") + "indented = 2"])

    def test_added_and_changed_lines_are_tinted(self):
        self.shapes()

        nvim = self.open_shapes()

        self.assertEqual(wait_for("the tint", lambda: nvim.look()["tinted"]), [(2, "DifftateAdd"), (5, "DifftateAdd")])

    def test_a_new_file_is_tinted_whole(self):
        self.branch_changes("shapes.py", SHAPES_BEFORE, SHAPES_AFTER)
        self.write("notes.md", "# Notes\nGreeting style\n")
        self.commit("Add notes")
        self.start_watcher()
        nvim = self.nvim(None, "notes.md")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        self.assertEqual(wait_for("the tint", lambda: nvim.look()["tinted"]),
                         [(1, "DifftateAdd"), (2, "DifftateAdd")])
        self.assertEqual(nvim.look()["deleted"], [])

    def test_the_highlights_are_the_plugins_own_and_linked_to_the_colorschemes(self):
        self.shapes()

        nvim = self.open_shapes()

        wait_for("the look", lambda: nvim.look()["deleted"])  # the first drawing defines them
        links = nvim.lua("""
            local out = {}
            for _, name in ipairs({ "DifftateAdd", "DifftateDeleted", "DifftateBox", "DifftateBody" }) do
              local hl = vim.api.nvim_get_hl(0, { name = name, link = true })
              out[name] = { hl.link, hl.default }
            end
            return out""")
        self.assertEqual(links, {"DifftateAdd": ["DiffAdd", True], "DifftateDeleted": ["DiffDelete", True],
                                 "DifftateBox": ["NormalFloat", True], "DifftateBody": ["NormalFloat", True]})

    def test_a_highlight_the_reviewer_set_themselves_wins_over_the_default(self):
        self.shapes()

        nvim = self.open_shapes(before="vim.api.nvim_set_hl(0, 'DifftateAdd', { bg = '#003300' })")

        wait_for("the tint", lambda: nvim.look()["tinted"])
        self.assertEqual(nvim.lua("return vim.api.nvim_get_hl(0, { name = 'DifftateAdd' }).bg"), 0x003300)

    def test_closing_the_review_removes_the_deleted_text_and_the_tint(self):
        self.shapes()
        nvim = self.open_shapes()
        wait_for("the look", lambda: nvim.look()["deleted"] and nvim.look()["tinted"])

        nvim.command("DifftateClose")

        self.assertEqual(nvim.look(), {"deleted": [], "tinted": []})
        time.sleep(0.6)
        self.assertEqual(nvim.look(), {"deleted": [], "tinted": []}, "nothing comes back with a poll or a gitsigns update")
        nvim.write_text("one = 1\ntwo = 2\n")
        time.sleep(0.5)
        self.assertEqual(nvim.look(), {"deleted": [], "tinted": []}, "nor with an edit")

    def test_opening_again_draws_the_look_again(self):
        self.shapes()
        nvim = self.open_shapes()
        first = wait_for("the look", lambda: nvim.look()["deleted"] and nvim.look())
        nvim.command("DifftateClose")

        nvim.command("DifftateOpen")

        wait_for("the look again", lambda: nvim.look() == first)

    def test_an_edit_draws_it_again(self):
        self.shapes()
        nvim = self.open_shapes()
        wait_for("the look", lambda: nvim.look()["tinted"])

        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, 0, false, { 'zero = 0' })")  # a new first line, not saved

        wait_for("the tint to move", lambda: nvim.look()["tinted"] == [(1, "DifftateAdd"), (3, "DifftateAdd"), (6, "DifftateAdd")])
        self.assertEqual([(d["row"], d["lines"]) for d in nvim.look()["deleted"]], [(3, ["two = 2"]), (5, ["four = 4"])])
        nvim.lua("vim.api.nvim_buf_set_lines(0, 3, 4, false, { 'three = 3', 'four = 4' })")  # the deleted line is back (and the third is written twice)
        wait_for("the deleted line to go", lambda: [d["lines"] for d in nvim.look()["deleted"]] == [["two = 2"]])

    @unittest.skip('gitsigns race, parked: #211')
    def test_a_move_of_the_base_draws_it_again(self):
        self.shapes()
        nvim = self.open_shapes()
        wait_for("the look", lambda: len(nvim.look()["deleted"]) == 2)
        base_folder = os.path.join(self.tmp, "wt-main")
        git(self.repo, self.env, "worktree", "add", "-q", base_folder, "main")
        with open(os.path.join(base_folder, "shapes.py"), "w") as f:
            f.write(SHAPES_BEFORE.replace("four = 4\n", ""))  # main drops the fourth line too
        self.commit("Drop four", folder=base_folder)

        git(self.repo, self.env, "merge", "-q", "--no-edit", "main")

        wait_for("the deleted line to go", lambda: [d["lines"] for d in nvim.look()["deleted"]] == [["two = 2"]])
        self.assertEqual(nvim.look()["tinted"], [(2, "DifftateAdd"), (5, "DifftateAdd")], "the added line stays: it is not on main")

    def test_a_buffer_with_no_change_against_the_base_has_no_look(self):
        self.shapes()  # app.py is the same on both branches
        self.start_watcher()
        nvim = self.nvim()
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("the review to open", lambda: nvim.status() != "")
        time.sleep(0.6)
        self.assertEqual(nvim.look(), {"deleted": [], "tinted": []})
        nvim.command("edit shapes.py")
        wait_for("the look in the file that changed", lambda: nvim.look()["deleted"])

    def test_diff_tint_false_leaves_the_lines_untinted_and_still_draws_the_deleted_text(self):
        self.shapes()

        nvim = self.open_shapes(opts={"poll_ms": 200, "diff": {"tint": False}})

        wait_for("the deleted text", lambda: len(nvim.look()["deleted"]) == 2)
        self.assertEqual(nvim.look()["tinted"], [])
        self.assertEqual(nvim.lua("return require('difftate').config.diff.tint"), False)

    def test_the_tint_is_on_unless_opts_say_otherwise(self):
        self.assertTrue(self.nvim().lua("return require('difftate').config.diff.tint"))

    def test_with_gitsigns_own_line_highlight_on_as_well_both_are_drawn_and_gitsigns_is_over_the_tint_by_priority(self):
        self.shapes()
        nvim = self.open_shapes()
        wait_for("the tint", lambda: nvim.look()["tinted"])

        nvim.lua("require('gitsigns').toggle_linehl(true)")  # as the reviewer would, to compare

        def line_highlights():  # [group, priority] of every whole-line highlight on the added fifth line
            return nvim.lua("""
                local out = {}
                for _, m in ipairs(vim.api.nvim_buf_get_extmarks(0, -1, { 4, 0 }, { 4, -1 }, { details = true })) do
                  if m[4].line_hl_group then table.insert(out, { m[4].line_hl_group, m[4].priority }) end
                end
                return out""")
        marks = wait_for("gitsigns' line highlight", lambda: len(line_highlights()) == 2 and line_highlights())
        self.assertIn(["DifftateAdd", 1], marks)
        gitsigns = [priority for hl, priority in marks if hl == "GitSignsAddLn"]
        self.assertEqual(len(gitsigns), 1)
        self.assertGreater(gitsigns[0], 1, "gitsigns' own highlight is over the tint: Neovim draws the higher priority")

    def test_the_review_without_gitsigns_has_no_look_and_no_error(self):
        self.shapes()
        self.start_watcher()
        nvim = self.nvim(None, "shapes.py", gitsigns=False)

        nvim.command("DifftateOpen")

        wait_for("the review to open", lambda: nvim.status() != "")
        time.sleep(0.5)
        self.assertEqual(nvim.look(), {"deleted": [], "tinted": []})
        self.assertNotIn("Error", nvim.messages())


@needs(MISSING_GITSIGNS)
class ThreadsInABox(NeovimHarness, unittest.TestCase):
    def a_review_with_a_long_thread(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread(LONG)
        self.api("POST", f"/api/threads/{tid}/comments", {"kind": "reply", "body": "Added a comment.\n\nSee below."})
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        return nvim

    def test_every_line_of_a_thread_is_the_box_highlight_padded_to_the_text_width(self):
        nvim = self.a_review_with_a_long_thread()

        columns = nvim.text_columns()
        # gitsigns' signs may widen the sign column after the first draw: the box follows
        box = wait_for("the box as wide as the text", lambda: {line["width"] for line in nvim.boxes()[0]} == {columns}
                       and nvim.boxes()[0])

        self.assertGreater(len(box), 6)
        for line in box:
            self.assertTrue(all(hl.startswith("DifftateBox") for hl in line["hls"]), line)
        self.assertEqual(box[0]["hls"], ["DifftateBox+DifftateBar", "DifftateBox+DifftateHead", "DifftateBox"])
        self.assertEqual(box[2]["hls"][1], "DifftateBox+DifftateBody", "the body is the box's, not the code's colour")

    def test_the_box_is_as_wide_as_the_narrowest_window_and_follows_a_resize(self):
        nvim = self.a_review_with_a_long_thread()
        wide = nvim.text_columns()

        nvim.command("vsplit")

        narrow = nvim.lua("""
            local narrowest
            for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
              local text = vim.api.nvim_win_get_width(win) - vim.fn.getwininfo(win)[1].textoff
              narrowest = math.min(narrowest or text, text)
            end
            return narrowest""")
        self.assertLess(narrow, wide)
        wait_for("the box to narrow", lambda: {line["width"] for line in nvim.boxes()[0]} == {narrow})
        nvim.command("only")
        wait_for("the box to widen", lambda: {line["width"] for line in nvim.boxes()[0]} == {wide})

    def test_a_collapsed_thread_is_a_box_of_one_line(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread("Done already")
        self.api("PATCH", f"/api/threads/{tid}/status", {"status": "resolved"})
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)

        box = nvim.boxes()[0]

        self.assertEqual(len(box), 1)
        self.assertEqual(box[0]["width"], nvim.text_columns())
        self.assertTrue(box[0]["hls"][1].startswith("DifftateBox+"))

    def test_the_deleted_code_a_thread_quotes_keeps_the_delete_colour_across_the_box(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.api("POST", "/api/threads", {"anchor": {"file": "app.py", "side": "old", "startLine": 2, "endLine": 2,
                                                    "code": "    return 'hi ' + name"}, "body": "Why drop this?"})
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)

        quoted = nvim.boxes()[0][1]

        self.assertEqual(quoted["text"], "│ -     return 'hi ' + name")
        self.assertEqual(quoted["width"], nvim.text_columns())
        self.assertEqual(quoted["hls"][-1], "DifftateDeleted", "the padding is red too: the whole line is deleted code")


@needs(MISSING_GITSIGNS)
class DeletedTextAndThreadsTogether(NeovimHarness, unittest.TestCase):
    """Both are virtual lines in the same gap: the order is the line before, its threads, the threads on
    the deleted lines (each quotes its code), then the deleted text."""

    def test_the_order_in_a_gap_is_the_threads_on_the_line_before_then_those_on_deleted_lines_then_the_deleted_text(self):
        self.shapes()
        self.start_watcher()
        self.batched()
        self.open_thread("Why three?", line=3, file="shapes.py")
        self.api("POST", "/api/threads", {"anchor": {"file": "shapes.py", "side": "old", "startLine": 4, "endLine": 4,
                                                    "code": "four = 4"}, "body": "Why drop four?"})
        nvim = self.nvim(None, "shapes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("everything drawn", lambda: len(nvim.look()["deleted"]) == 2 and len(nvim.threads()) == 2)
        screen = nvim.screen()
        three = screen_row(screen, "three = 3")
        new_thread = screen_row(screen, "│   Why three?", three)
        old_thread = screen_row(screen, "│   Why drop four?", new_thread)
        deleted = screen_row(screen, "four = 4", old_thread)
        five = screen_row(screen, "five = 5", deleted)
        self.assertTrue(three < new_thread < old_thread < deleted < five, "\n".join(screen))
        self.assertIn("│ - four = 4", screen[old_thread - 2], "the thread on the deleted line quotes its code before its words")

    def test_the_order_holds_when_the_line_before_the_gap_is_blank(self):
        self.branch_changes("shapes.py", "a = 1\n\nb = 2\nc = 3\n", "a = 1\n\nc = 3\n")
        self.start_watcher()
        self.batched()
        self.api("POST", "/api/threads", {"anchor": {"file": "shapes.py", "side": "old", "startLine": 3, "endLine": 3,
                                                    "code": "b = 2"}, "body": "Why drop b?"})
        nvim = self.nvim(None, "shapes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("everything drawn", lambda: nvim.look()["deleted"] and nvim.threads())
        screen = nvim.screen()
        thread = screen_row(screen, "│   Why drop b?")
        deleted = screen_row(screen, "b = 2", thread)
        c = screen_row(screen, "c = 3", deleted)
        self.assertTrue(thread < deleted < c, "\n".join(screen))

    def test_at_the_top_of_the_file_the_deleted_text_comes_before_the_thread_on_it(self):
        self.branch_changes("shapes.py", "zero = 0\none = 1\n", "one = 1\n")
        self.start_watcher()
        self.batched()
        self.api("POST", "/api/threads", {"anchor": {"file": "shapes.py", "side": "old", "startLine": 1, "endLine": 1,
                                                    "code": "zero = 0"}, "body": "Why drop zero?"})
        nvim = self.nvim(None, "shapes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("everything drawn", lambda: nvim.look()["deleted"] and nvim.threads())
        # What is above the first line shows only once the window scrolls up (Neovim's way, for any virtual line)
        nvim.keys("<C-y>" * 6)
        screen = nvim.screen()
        deleted = screen_row(screen, "zero = 0")
        thread = screen_row(screen, "│   Why drop zero?", deleted)
        one = screen_row(screen, "one = 1", thread)
        self.assertTrue(deleted < thread < one, "\n".join(screen))


@needs(MISSING_GITSIGNS)
class TheDiffLookAddsOnly(NeovimHarness, unittest.TestCase):
    def test_drawing_the_look_changes_no_option_key_gitsigns_setting_highlight_or_foreign_extmark(self):
        self.shapes()
        self.start_watcher()
        self.batched()
        self.open_thread("Why three?", line=3, file="shapes.py")
        self.api("POST", "/api/threads", {"anchor": {"file": "shapes.py", "side": "old", "startLine": 4, "endLine": 4,
                                                    "code": "four = 4"}, "body": "Why drop four?"})
        nvim = self.nvim(None, "shapes.py", before="vim.diagnostic.set(vim.api.nvim_create_namespace('other'), 0, "
                         "{ { lnum = 0, col = 0, message = 'hint', severity = vim.diagnostic.severity.HINT } })")
        self.attached(nvim)
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        settings = nvim.lua("return T.settings()")
        foreign = nvim.lua("return T.foreign_extmarks(0)")

        nvim.command("DifftateOpen")
        wait_for("the look and the threads", lambda: len(nvim.look()["deleted"]) == 2 and len(nvim.threads()) == 2)
        nvim.keys("<leader>re")  # expanded
        nvim.command("vsplit")
        nvim.lua("vim.api.nvim_buf_set_lines(0, 0, 0, false, { 'zero = 0' })")  # an edit, not saved
        wait_for("it drawn again", lambda: nvim.look()["tinted"][:1] == [(1, "DifftateAdd")])
        nvim.command("silent undo")  # the buffer is unmodified again
        wait_for("it drawn as it was", lambda: nvim.look()["tinted"][:1] == [(2, "DifftateAdd")])

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before, "no option, no key, while the look is drawn")
        self.assertEqual(nvim.lua("return T.settings()"), settings, "gitsigns' line highlight, word diff and deleted lines stay off; the colorscheme's groups stay")
        self.assertEqual(nvim.lua("return T.foreign_extmarks(0)"), foreign, "nobody else's extmarks")
        nvim.command("close")  # the split's window: the reviewer's own stays
        nvim.command("DifftateClose")
        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)
        self.assertEqual(nvim.lua("return T.settings()"), settings)
        self.assertEqual(nvim.lua("return T.foreign_extmarks(0)"), foreign)


@needs(MISSING_GITSIGNS)
class ReviewExport(NeovimHarness, unittest.TestCase):
    """GET /api/export, put where the reviewer pastes it (the system clipboard, as the browser does)."""

    def export_text(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}" + with_folder("/api/export", self.repo) + "&reply_folder=" + urllib.parse.quote(os.path.realpath(self.repo)),
                                         headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.read().decode()

    def events_text(self):
        reviews = os.path.join(self.repo, ".git", "difftate", "reviews")
        texts = []
        for review in sorted(os.listdir(reviews)):
            with open(os.path.join(reviews, review, "events.jsonl")) as f:
                texts.append(f.read())
        return texts

    def clipboard(self, nvim):
        return nvim.lua("return vim.fn.getreg('+')")

    def test_leader_rE_copies_the_export_to_the_clipboard_and_says_what_it_holds(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("Is this right?", line=2)
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "Export copied (1 thread needs an answer): paste it into an agent session" in nvim.messages())
        text = self.clipboard(nvim)
        self.assertIn("Is this right?", text)
        self.assertEqual(text.rstrip("\n"), self.export_text().rstrip("\n"),
                         "the same text as GET /api/export?reply_folder=<the review's folder>: its reply command works from anywhere")

    def test_the_message_counts_the_threads_that_need_an_answer(self):
        self.commit()
        self.start_watcher()
        self.batched()
        self.a_thread("First?", line=1)
        self.a_thread("Second?", line=2)
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "Export copied (2 threads need an answer): paste it into an agent session" in nvim.messages())

    def test_with_no_thread_needing_an_answer_it_says_so(self):
        nvim = self.an_open_review()
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "Export copied (no thread needs an answer): paste it into an agent session" in nvim.messages())
        self.assertIn("Review export", self.clipboard(nvim))

    def test_exporting_changes_no_thread_and_writes_no_event(self):
        self.commit()
        self.start_watcher()
        self.batched()
        tid = self.a_thread("Is this right?", line=2)
        nvim = self.nvim()
        nvim.command("DifftateOpen")
        self.drawn(nvim)
        before = (self.api("GET", "/api/threads?view="), self.thread(tid))
        events = self.events_text()

        nvim.keys("<leader>rE")
        wait_for("the export", lambda: "Review export" in self.clipboard(nvim))

        self.assertEqual((self.api("GET", "/api/threads?view="), self.thread(tid)), before)
        self.assertEqual(self.events_text(), events)

    def test_without_a_system_clipboard_it_goes_to_the_unnamed_register_and_says_so(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim(before="vim.g.loaded_clipboard_provider = 1")
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "No system clipboard here: the export is in the unnamed register (paste it with p)" in nvim.messages())
        self.assertIn("Review export", nvim.lua("return vim.fn.getreg('\"')"))

    def test_an_empty_answer_is_not_an_export(self):
        nvim = self.an_open_review()
        nvim.lua("require('difftate.api').request = function(watcher, method, path, on_answer)"
                 " vim.schedule(function() on_answer('') end) end")
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "Could not export: The watcher gave no export (is it up to date?)" in nvim.messages())
        self.assertEqual(self.clipboard(nvim), "")

    def test_a_refused_export_says_why_and_copies_nothing(self):
        nvim = self.an_open_review()
        nvim.lua("require('difftate.api').request = function(watcher, method, path, on_answer)"
                 " vim.schedule(function() on_answer(nil, { message = 'the commit messages could not be read' }) end) end")
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "Could not export: the commit messages could not be read" in nvim.messages())
        self.assertEqual(self.clipboard(nvim), "")

    def test_the_watcher_stopping_is_said_in_the_usual_words(self):
        nvim = self.an_open_review()
        self.watcher.send_signal(signal.SIGINT)
        self.watcher.wait(15)
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())
        self.assertNotIn("Could not export", nvim.messages(), "said once, in the usual words")

    def test_nothing_is_exported_when_no_review_is_open(self):
        nvim = self.nvim()
        nvim.command("messages clear")

        nvim.keys("<leader>rE")

        wait_for("the message", lambda: "No review is open: open it to export" in nvim.messages())

    def test_the_key_is_free_in_lazyvim_core_and_can_be_changed_or_turned_off(self):
        nvim = self.nvim(opts={"keys": {"export": "<leader>gX"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rE', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gX', 'n')"), "")
        off = self.nvim(opts={"keys": {"export": False}})
        self.assertEqual(off.lua("return vim.fn.maparg('<leader>rE', 'n')"), "")
        taken = self.nvim(before="vim.keymap.set('n', '<leader>rE', '<cmd>echo \"also\"<cr>', { desc = 'Also' })")
        self.assertIn("<leader>rE is already mapped (Also): set opts.keys.export to another key", taken.messages())


@needs(MISSING_GITSIGNS)
class ReviewViewed(NeovimHarness, unittest.TestCase):
    """GET and PUT /api/viewed: the current buffer's file marked viewed, or not, as the browser's checkbox does."""

    def viewed(self):
        return self.api("GET", "/api/viewed")["files"]

    def a_review_with_an_unchanged_file(self):
        """notes.txt is on main and the branch alike (not in the changeset); app.py changed. Neovim is on notes.txt."""
        git(self.repo, self.env, "checkout", "-q", "--", "app.py")
        git(self.repo, self.env, "checkout", "-q", "main")
        self.write("notes.txt", "Notes\n")
        self.commit("Add notes")
        git(self.repo, self.env, "checkout", "-q", "-B", "feature")
        self.write("app.py", "def greet(name):\n    return f'hello {name}'\n")
        self.commit("Change app")
        self.start_watcher()
        nvim = self.nvim(None, "notes.txt")
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        return nvim

    def stub_put_viewed(self, nvim, message):
        nvim.lua("require('difftate.api').request = (function(real) return function(watcher, method, path, on_answer, payload)"
                 " if method == 'PUT' and path == '/api/viewed' then"
                 f" vim.schedule(function() on_answer(nil, {{ message = {vim_string(message)} }}) end) return end"
                 " return real(watcher, method, path, on_answer, payload) end end)(require('difftate.api').request)")

    # Toggle -------------------------------------------------------------------

    def test_leader_rv_marks_the_current_file_viewed_and_says_so_and_the_key_again_unmarks_it(self):
        nvim = self.an_open_review()
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "Viewed app.py" in nvim.messages())
        self.assertEqual(self.viewed(), ["app.py"])
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "Not viewed: app.py" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    def test_the_toggle_goes_from_what_the_review_api_has_so_a_mark_made_elsewhere_is_not_marked_again(self):
        nvim = self.an_open_review()
        self.api("PUT", "/api/viewed", {"file": "app.py"})
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "Not viewed: app.py" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    def test_only_the_current_file_is_toggled(self):
        self.write("util.py", "x = 1\n")
        nvim = self.an_open_review()
        self.api("PUT", "/api/viewed", {"file": "util.py"})

        nvim.keys("<leader>rv")

        wait_for("app.py viewed", lambda: "app.py" in self.viewed())
        self.assertEqual(self.viewed(), ["app.py", "util.py"])

    def test_a_file_in_a_subfolder_is_marked_by_its_path_in_the_repository(self):
        os.makedirs(os.path.join(self.repo, "pkg"))
        self.write("pkg/tool.py", "y = 2\n")
        self.commit()
        self.start_watcher()
        nvim = self.nvim(None, "pkg/tool.py")
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "Viewed pkg/tool.py" in nvim.messages())
        self.assertEqual(self.viewed(), ["pkg/tool.py"])

    # The files picker --------------------------------------------------------------

    def test_the_files_picker_follows_each_toggle_on_its_next_open(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)

        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  app.py  +1 −1"])
        nvim.pick(1)
        nvim.keys("<leader>rv")
        wait_for("viewed", lambda: self.viewed() == ["app.py"])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["✓ app.py  +1 −1 · viewed"])
        nvim.pick(1)
        nvim.keys("<leader>rv")
        wait_for("not viewed", lambda: self.viewed() == [])
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())

        self.assertEqual(nvim.menu()["lines"], ["  app.py  +1 −1"])

    def test_a_file_whose_diff_changed_loses_its_mark_and_the_picker_shows_that(self):
        nvim = self.an_open_review()
        nvim.lua(FAKE_SELECT)
        nvim.keys("<leader>rv")
        wait_for("viewed", lambda: self.viewed() == ["app.py"])

        # Replaced whole, so no poll sees the file half written
        replacement = os.path.join(self.tmp, "app.py.new")
        with open(replacement, "w") as f:
            f.write("def greet(name):\n    return f'hello, {name}!'\n")
        os.replace(replacement, os.path.join(self.repo, "app.py"))
        wait_for("the mark cleared", lambda: self.viewed() == [])
        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  app.py  +1 −1"])

    # A file that is not changed ------------------------------------------------------

    def test_a_file_not_in_the_changeset_says_so_and_changes_nothing(self):
        nvim = self.a_review_with_an_unchanged_file()
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "notes.txt is not in the changeset: nothing to mark viewed" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    def test_a_buffer_that_is_not_a_file_says_to_open_a_changed_file(self):
        nvim = self.an_open_review()
        nvim.command("enew")
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "Open a changed file to mark it viewed" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    def test_a_file_outside_the_reviews_folder_says_so_and_marks_nothing(self):
        outside = os.path.join(self.tmp, "elsewhere.py")
        with open(outside, "w") as f:
            f.write("z = 3\n")
        nvim = self.an_open_review()
        nvim.command("edit " + outside)
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "is not in" in nvim.messages() and "the folder of the review" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    # Errors ------------------------------------------------------------------------

    def test_with_no_review_open_it_says_so_and_marks_nothing(self):
        self.commit()
        self.start_watcher()
        nvim = self.nvim()
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the message", lambda: "No review is open: open it to mark a file viewed" in nvim.messages())
        self.assertEqual(self.viewed(), [])

    def test_a_stopped_watcher_is_said(self):
        nvim = self.an_open_review()
        self.stop_watcher()
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the error", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())

    def test_a_409_is_shown_as_the_api_says(self):
        nvim = self.an_open_review()
        message = "another branch is checked out: go back to feature to mark a file viewed"
        self.stub_put_viewed(nvim, message)
        nvim.command("messages clear")

        nvim.keys("<leader>rv")

        wait_for("the API's own words", lambda: message in nvim.messages())
        self.assertEqual(self.viewed(), [])

    # The key -----------------------------------------------------------------------

    def test_the_key_is_free_in_lazyvim_core_and_can_be_changed_or_turned_off(self):
        nvim = self.nvim(opts={"keys": {"viewed": "<leader>gV"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rv', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gV', 'n')"), "")
        off = self.nvim(opts={"keys": {"viewed": False}})
        self.assertEqual(off.lua("return vim.fn.maparg('<leader>rv', 'n')"), "")
        taken = self.nvim(before="vim.keymap.set('n', '<leader>rv', '<cmd>echo \"also\"<cr>', { desc = 'Also' })")
        self.assertIn("<leader>rv is already mapped (Also): set opts.keys.viewed to another key", taken.messages())

    def test_the_viewed_key_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.an_open_review()
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        nvim.keys("<leader>rv")
        wait_for("viewed", lambda: self.viewed() == ["app.py"])
        nvim.keys("<leader>rv")
        wait_for("not viewed", lambda: self.viewed() == [])


@needs(MISSING_GITSIGNS)
class ChoosingTheView(NeovimHarness, unittest.TestCase):
    """GET and PUT /api/view: the part of the review the reviewer looks at (GLOSSARY.md: View). gitsigns' base follows it."""

    def short(self, ref):
        return subprocess.run(["git", "-C", self.repo, "log", "-1", "--format=%h", ref], check=True,
                              capture_output=True, text=True, env=self.env).stdout.strip()

    def a_branch_of_three_commits(self):
        """notes.py has 12 lines on main. The branch deletes line 4 (its first commit), edits what is then line 5
        (second), line 7 (third), line 9 (staged) and line 11 (not staged): so every view has its own hunks."""
        lines = [f"line {n}" for n in range(1, 13)]
        before = "\n".join(lines) + "\n"
        del lines[3]
        self.branch_changes("notes.py", before, "\n".join(lines) + "\n")
        for number, message in ((5, "Edit the middle"), (7, "Edit near the end")):
            lines[number - 1] += " edited"
            self.write("notes.py", "\n".join(lines) + "\n")
            self.commit(message)
        lines[8] += " edited"
        self.write("notes.py", "\n".join(lines) + "\n")
        git(self.repo, self.env, "add", "notes.py")
        lines[10] += " edited"
        self.write("notes.py", "\n".join(lines) + "\n")

    def open_notes(self, **kwargs):
        """The review open on notes.py, on all changes (its five hunks); the Neovim."""
        self.a_branch_of_three_commits()
        self.start_watcher()
        nvim = self.nvim(None, "notes.py", before=kwargs.pop("before", FAKE_SELECT), **kwargs)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        wait_for("the five hunks", lambda: nvim.hunks() == [[0, 1]] + [[1, 1]] * 4)
        return nvim

    def choose(self, nvim, entry):
        """Press the view key and choose the picker's <entry> (1-based)."""
        nvim.keys("<leader>rV")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(entry)

    def view(self):
        return self.api("GET", "/api/view")["view"]

    def test_leader_rf_in_a_view_shows_the_review_path_cut_down_to_its_files_numbers_kept(self):
        self.a_branch_of_three_commits()
        self.commit("Keep the rest")  # a commit view shows the files on disk too: nothing uncommitted left
        self.write("extra.py", "x = 1\n")
        self.write("extra.css", "a {}\n")
        self.commit("Add extras")
        exclude = os.path.join(self.repo, ".git", "info", "exclude")
        with open(exclude, "a") as f:
            f.write("review-path.md\n")
        self.write("review-path.md", "## 1 `notes.py` ★\n\n### What changed?\nLines.\n\n"
                                     "## 2 `extra.py`\n\n### What is new?\nA file.\n\n### Side file: `extra.css`\nStyle.\n")
        self.start_watcher()
        nvim = self.nvim(None, "notes.py", before=FAKE_SELECT)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  1 notes.py ★ · What changed?", "  2 extra.py · What is new?",
                                                "  └─ extra.css"])
        nvim.lua("T.menu = nil")

        self.choose(nvim, 4)  # the last commit: Add extras
        wait_for("the view", lambda: "showing the last commit" in nvim.status())
        nvim.keys("<leader>rf")

        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], ["  2 extra.py · What is new?", "  └─ extra.css"])

    def test_following_the_review_path_in_a_view_changes_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        """Adds only: asking for the path in a view maps no key and sets no option on the reviewer's buffer or window."""
        self.a_branch_of_three_commits()
        self.commit("Keep the rest")
        self.write("extra.py", "x = 1\n")
        self.commit("Add extras")
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as f:
            f.write("review-path.md\n")
        self.write("review-path.md", "## 1 `notes.py`\n\n### What changed?\nLines.\n\n## 2 `extra.py`\n\n### What is new?\nA file.\n")
        self.start_watcher()
        nvim = self.nvim(None, "notes.py", before=FAKE_SELECT)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        self.choose(nvim, 4)
        wait_for("the view", lambda: "showing the last commit" in nvim.status())
        nvim.keys("<leader>rf")
        wait_for("the picker", lambda: nvim.menu())
        nvim.pick(1)  # extra.py, the only stop left
        wait_for("extra.py", lambda: nvim.at()[0] == "extra.py")
        nvim.command("buffer notes.py")

        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)

    def test_leader_rV_lists_the_views_and_the_last_commits_with_their_subjects(self):
        nvim = self.open_notes()

        nvim.keys("<leader>rV")

        wait_for("the picker", lambda: nvim.menu())
        menu = nvim.menu()
        self.assertEqual(menu["via"], "ui.select")
        self.assertEqual(menu["title"], "Review views")
        self.assertEqual(menu["lines"], [
            "All changes · against main · shown",
            "Uncommitted changes",
            "Unstaged changes",
            f"Last commit · {self.short('HEAD')} Edit near the end",
            f"Last 2 commits · down to {self.short('HEAD~1')} Edit the middle",
            f"Last 3 commits · down to {self.short('HEAD~2')} Change the file",
        ])

    def test_each_view_points_gitsigns_at_its_base_and_names_itself_in_the_note(self):
        nvim = self.open_notes()
        main = self.head(ref="main")
        views = [  # (entry, the API's view, gitsigns' base, its hunks, the message, what the note says)
            (4, "HEAD~1", self.head(ref="HEAD~1"), [[1, 1]] * 3, "Showing the last commit",
             "review open · showing the last commit · live · git signs show changes since HEAD~1"),
            (5, "HEAD~2", self.head(ref="HEAD~2"), [[1, 1]] * 4, "Showing the last 2 commits",
             "review open · showing the last 2 commits · live · git signs show changes since HEAD~2"),
            (6, "HEAD~3", main, [[0, 1]] + [[1, 1]] * 4, "Showing the last 3 commits",
             "review open · showing the last 3 commits · live · git signs show changes since HEAD~3"),
            (2, "HEAD", self.head(), [[1, 1]] * 2, "Showing uncommitted changes",
             "review open · showing uncommitted changes · live · git signs show changes since HEAD"),
            (3, "unstaged", None, [[1, 1]], "Showing unstaged changes",
             "review open · showing unstaged changes · live · git signs show unstaged changes"),
            (1, "", main, [[0, 1]] + [[1, 1]] * 4, "Showing all changes",
             "review open · live · git signs show changes since main"),
        ]
        for entry, view, base, hunks, message, note in views:
            with self.subTest(view=view or "all changes"):
                nvim.command("messages clear")

                self.choose(nvim, entry)

                wait_for("gitsigns on the view's base", lambda: nvim.gitsigns_base() == base and nvim.hunks() == hunks)
                wait_for("the note", lambda: nvim.status() == note)
                self.assertIn(message, nvim.messages())
                self.assertEqual(self.view(), view, "the watcher keeps it: the other viewers show it too")

    def test_choosing_the_view_already_shown_changes_nothing(self):
        nvim = self.open_notes()
        nvim.command("messages clear")

        self.choose(nvim, 1)

        wait_for("the message", lambda: "Already showing all changes" in nvim.messages())
        self.assertEqual(nvim.gitsigns_base(), self.head(ref="main"))

    def test_threads_on_lines_the_view_shows_are_drawn_the_rest_are_listed_not_placed(self):
        nvim = self.open_notes()
        self.batched()
        self.api("POST", "/api/threads", {  # on the line the first commit deleted: only all changes (and the last 3 commits) show it
            "anchor": {"file": "notes.py", "side": "old", "startLine": 4, "endLine": 4, "code": "line 4"},
            "body": "Why drop line 4?"})
        self.open_thread("Is this edit needed?", line=5, file="notes.py")
        nvim.command("1")
        wait_for("both drawn", lambda: len(nvim.threads()) == 2)

        self.choose(nvim, 4)  # the last commit

        wait_for("only the thread the view shows", lambda: [t["row"] for t in nvim.threads()] == [5])
        self.assertEqual(nvim.signs(), [(5, "●")])
        nvim.keys("<leader>rs")
        wait_for("the picker", lambda: nvim.menu())
        self.assertEqual(nvim.menu()["lines"], [
            "● notes.py:4 (deleted) · open · held until you submit · not in this view · Why drop line 4?",
            "● notes.py:5 · open · held until you submit · Is this edit needed?",
        ])

        nvim.pick(1)  # a thread that is listed but on no line opens in its float

        wait_for("its float", lambda: nvim.float_lines())
        self.assertIn("Why drop line 4?", nvim.float_lines())
        nvim.keys("q")
        self.choose(nvim, 6)  # the last 3 commits show the deleted line again
        wait_for("both drawn again", lambda: [t["row"] for t in nvim.threads()] == [3, 5])  # the deleted line's thread under line 3

    def test_the_deleted_text_of_the_view_is_drawn_and_what_it_does_not_show_is_not(self):
        nvim = self.open_notes()
        wait_for("every old line drawn", lambda: len(nvim.look()["deleted"]) == 5)
        self.assertIn(["line 4"], [d["lines"] for d in nvim.look()["deleted"]])

        self.choose(nvim, 4)  # the last commit: three edited lines, not the deleted one

        wait_for("their old text", lambda: len(nvim.look()["deleted"]) == 3)
        self.assertNotIn(["line 4"], [d["lines"] for d in nvim.look()["deleted"]])

    def test_closing_the_review_in_a_view_puts_gitsigns_back_on_the_index(self):
        nvim = self.open_notes()
        self.choose(nvim, 5)
        wait_for("the view", lambda: nvim.gitsigns_base() == self.head(ref="HEAD~2"))

        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertIn("Review closed: git signs show changes since the index again", nvim.messages())
        self.assertEqual(nvim.status(), "")

    def test_closing_the_review_in_the_unstaged_view_puts_back_the_base_the_reviewer_gave_gitsigns(self):
        nvim = self.open_notes(before=FAKE_SELECT + "; require('gitsigns').change_base('HEAD~1', true)")
        self.choose(nvim, 3)
        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)

        nvim.command("DifftateClose")

        wait_for("the reviewer's base again", lambda: nvim.gitsigns_base() == "HEAD~1")
        self.assertIn("Review closed: git signs show changes since HEAD~1 again", nvim.messages())

    def test_hunk_motions_walk_only_the_changes_of_the_view(self):
        nvim = self.open_notes()
        self.choose(nvim, 4)  # the last commit: lines 7, 9 and 11
        wait_for("its three hunks", lambda: nvim.hunks() == [[1, 1]] * 3)
        nvim.command("1")
        visited = []

        for _ in range(3):
            line = nvim.at()[1]
            nvim.lua("require('gitsigns').nav_hunk('next')")
            wait_for("the cursor to move", lambda: nvim.at()[1] != line)
            visited.append(nvim.at()[1])

        self.assertEqual(visited, [7, 9, 11], "line 5 (an earlier commit) and the deleted line 4 are not walked")

    def test_a_view_another_viewer_chose_is_followed_within_a_poll(self):
        nvim = self.open_notes()

        self.api("PUT", "/api/view", {"view": "HEAD~2"})

        wait_for("gitsigns on it", lambda: nvim.gitsigns_base() == self.head(ref="HEAD~2") and nvim.hunks() == [[1, 1]] * 4)
        self.assertEqual(nvim.status(), "review open · showing the last 2 commits · live · git signs show changes since HEAD~2")

    def test_the_staged_view_stays_in_the_browser_here_it_is_said_and_all_changes_are_shown(self):
        nvim = self.open_notes()

        self.api("PUT", "/api/view", {"view": "staged"})

        wait_for("the note", lambda: nvim.status() == "review open · showing all changes: staged changes are only in the browser · live · git signs show changes since main")
        self.assertEqual(nvim.gitsigns_base(), self.head(ref="main"))
        nvim.keys("<leader>rV")
        wait_for("the picker", lambda: nvim.menu())
        self.assertNotIn("Staged changes", nvim.menu()["lines"])

    def test_a_refused_view_says_why_and_leaves_everything_as_it_was(self):
        nvim = self.open_notes()
        nvim.lua("local request = require('difftate.api').request; require('difftate.api').request = function(w, method, path, on_answer, payload, raw)"
                 " if method == 'PUT' and path == '/api/view' then vim.schedule(function() on_answer(nil, { message = 'no view nonsense' }) end) return end"
                 " return request(w, method, path, on_answer, payload, raw) end")
        nvim.command("messages clear")

        self.choose(nvim, 4)

        wait_for("the message", lambda: "Can't show the last commit: no view nonsense" in nvim.messages())
        self.assertEqual(nvim.gitsigns_base(), self.head(ref="main"))
        self.assertEqual(self.view(), "")

    def test_a_view_git_cannot_find_here_is_said_and_all_changes_are_shown_the_review_still_opens(self):
        self.a_branch_of_three_commits()
        self.start_watcher()
        self.api("PUT", "/api/view", {"view": "HEAD~3"})
        git(self.repo, self.env, "reset", "-q", "--hard", "HEAD~2")  # the branch is shorter than the view says
        nvim = self.nvim(None, "notes.py")
        self.attached(nvim)

        nvim.command("DifftateOpen")

        wait_for("the note", lambda: nvim.status() == "review open · showing all changes: git can't find HEAD~3 · live · git signs show changes since main")
        wait_for("gitsigns on all changes", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        self.assertIn("git can't find HEAD~3, the view: showing all changes", nvim.messages())

    def test_the_watcher_stopping_is_said_in_the_usual_words(self):
        nvim = self.open_notes()
        self.watcher.send_signal(signal.SIGINT)
        self.watcher.wait(15)
        nvim.command("messages clear")

        self.choose(nvim, 4)

        wait_for("the message", lambda: "No difftate is running: run `difftate` in a terminal" in nvim.messages())

    def test_with_no_review_open_it_says_so_and_opens_no_picker(self):
        self.commit()
        nvim = self.nvim(before=FAKE_SELECT)

        nvim.keys("<leader>rV")

        wait_for("the message", lambda: "No review is open: open it to choose the view" in nvim.messages())
        self.assertIsNone(nvim.menu())

    def test_a_comment_written_in_a_view_is_anchored_to_the_code_on_disk(self):
        nvim = self.open_notes()
        self.choose(nvim, 4)
        wait_for("the view", lambda: nvim.gitsigns_base() == self.head(ref="HEAD~1"))
        nvim.command("7")

        nvim.keys("<leader>rc")
        wait_for("the compose float", lambda: nvim.compose_float())
        nvim.write_text("Why edit this?")
        nvim.command("write")

        wait_for("the thread", lambda: [t for t in self.api("GET", "/api/threads") if t["anchor"]])
        anchor = [t for t in self.api("GET", "/api/threads") if t["anchor"]][0]["anchor"]
        self.assertEqual((anchor["file"], anchor["side"], anchor["startLine"], anchor["code"]),
                         ("notes.py", "new", 7, "line 8 edited"))

    def test_the_key_is_free_in_lazyvim_core_and_can_be_changed_or_turned_off(self):
        nvim = self.nvim(opts={"keys": {"views": "<leader>gV"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rV', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gV', 'n')"), "")
        off = self.nvim(opts={"keys": {"views": False}})
        self.assertEqual(off.lua("return vim.fn.maparg('<leader>rV', 'n')"), "")
        taken = self.nvim(before="vim.keymap.set('n', '<leader>rV', '<cmd>echo \"also\"<cr>', { desc = 'Also' })")
        self.assertIn("<leader>rV is already mapped (Also): set opts.keys.views to another key", taken.messages())

    def test_switching_views_and_closing_change_no_option_or_key_of_the_reviewers_window_or_buffer(self):
        nvim = self.open_notes()
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")

        for entry in (4, 3, 2, 1):
            self.choose(nvim, entry)
            wait_for("the view", lambda: self.view() == ["", "HEAD", "unstaged", "HEAD~1"][entry - 1])
        wait_for("all changes", lambda: nvim.gitsigns_base() == self.head(ref="main"))
        nvim.command("DifftateClose")

        wait_for("gitsigns on the index", lambda: nvim.gitsigns_base() is None)
        self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before)


@needs(MISSING_GITSIGNS)
class SideBySide(NeovimHarness, unittest.TestCase):
    """<leader>rd: gitsigns' diffthis against the base of the view shown, on or off, for the file in the current window."""

    KEY = "<leader>rd"

    def open_notes(self, **kwargs):
        """notes.py's review (ChoosingTheView's three commits and staged and unstaged edits) open, on all changes."""
        ChoosingTheView.a_branch_of_three_commits(self)
        self.start_watcher()
        nvim = self.nvim(None, "notes.py", before=kwargs.pop("before", FAKE_SELECT), **kwargs)
        self.attached(nvim)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")
        wait_for("the five hunks", lambda: nvim.hunks() == [[0, 1]] + [[1, 1]] * 4)
        return nvim

    def windows(self, nvim):
        """The windows of the tab, left to right: [{"name", "diff", "lines", "current"}]."""
        return nvim.lua("""
            local out = {}
            local here = vim.api.nvim_get_current_win()
            local wins = vim.api.nvim_tabpage_list_wins(0)
            table.sort(wins, function(a, b) return vim.api.nvim_win_get_position(a)[2] < vim.api.nvim_win_get_position(b)[2] end)
            for _, win in ipairs(wins) do
              local buf = vim.api.nvim_win_get_buf(win)
              table.insert(out, { name = vim.api.nvim_buf_get_name(buf), diff = vim.wo[win].diff,
                                  lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false), current = win == here })
            end
            return out""")

    def split_on(self, nvim):
        nvim.keys(self.KEY)
        return wait_for("the split", lambda: (lambda w: w if len(w) == 2 else None)(self.windows(nvim)))

    def one_window(self, nvim):
        return wait_for("one window", lambda: (lambda w: w if len(w) == 1 else None)(self.windows(nvim)))

    def git_show(self, spec):
        return subprocess.run(["git", "-C", self.repo, "show", spec], check=True, capture_output=True, text=True,
                              env=self.env).stdout.splitlines()

    def test_it_opens_the_base_of_all_changes_on_the_left_and_keeps_the_cursor_in_the_reviewers_file(self):
        nvim = self.open_notes()
        merge_base = self.head(ref="main")

        left, right = self.split_on(nvim)

        self.assertIn(f"{merge_base}:notes.py", left["name"])
        self.assertEqual(left["lines"], self.git_show(f"{merge_base}:notes.py"))
        self.assertTrue(right["name"].endswith("notes.py") and "gitsigns://" not in right["name"])
        self.assertEqual((left["diff"], right["diff"], left["current"], right["current"]), (True, True, False, True))

    def test_the_unified_look_is_not_drawn_in_the_split_and_comes_back_with_it_closed(self):
        nvim = self.open_notes()
        wait_for("the look", lambda: nvim.look()["deleted"] and nvim.look()["tinted"])
        look = nvim.look()

        self.split_on(nvim)

        wait_for("the look to go", lambda: nvim.look() == {"deleted": [], "tinted": []})
        nvim.keys(self.KEY)
        self.one_window(nvim)
        wait_for("the look back", lambda: nvim.look() == look)

    def test_the_base_is_that_of_the_view_shown(self):
        nvim = self.open_notes()
        ChoosingTheView.choose(self, nvim, 4)  # the last commit
        wait_for("the view", lambda: nvim.gitsigns_base() == self.head(ref="HEAD~1"))

        left, _ = self.split_on(nvim)

        self.assertIn(f"{self.head(ref='HEAD~1')}:notes.py", left["name"])
        self.assertEqual(left["lines"], self.git_show("HEAD~1:notes.py"))

    def test_in_the_unstaged_view_the_base_is_the_index(self):
        nvim = self.open_notes()
        ChoosingTheView.choose(self, nvim, 3)
        wait_for("the index", lambda: nvim.gitsigns_base() is None and self.api("GET", "/api/view")["view"] == "unstaged")

        left, _ = self.split_on(nvim)

        self.assertIn(":0:notes.py", left["name"])
        self.assertEqual(left["lines"], self.git_show(":notes.py"))

    def test_the_same_key_closes_the_split_from_the_right_and_from_the_left(self):
        nvim = self.open_notes()
        window = nvim.lua("return vim.api.nvim_get_current_win()")
        before = nvim.lua(f"return T.snapshot({window})")
        for side in ("right", "left"):
            self.split_on(nvim)
            if side == "left":
                nvim.command("wincmd h")
                self.assertIn("gitsigns://", nvim.lua("return vim.api.nvim_buf_get_name(0)"))

            nvim.keys(self.KEY)

            (only,) = self.one_window(nvim)
            self.assertTrue(only["name"].endswith("notes.py") and only["current"] and not only["diff"], side)
            self.assertEqual(nvim.lua(f"return T.snapshot({window})"), before, side)
        self.assertEqual(nvim.lua("return vim.api.nvim_get_current_win()"), window)

    def test_a_thread_key_works_in_the_reviewers_file_while_the_split_is_on(self):
        nvim = self.open_notes()
        self.batched()
        self.open_thread("Why delete line 4?", file="notes.py", line=7)
        self.drawn(nvim)
        self.split_on(nvim)
        nvim.command("7")

        nvim.keys("<leader>rt")

        wait_for("the float", lambda: nvim.float_lines())
        self.assertIn("Why delete line 4?", "\n".join(nvim.float_lines()))
        nvim.keys("q")
        self.assertTrue(nvim.threads())

    def test_with_no_review_open_it_says_so_and_opens_no_split(self):
        ChoosingTheView.a_branch_of_three_commits(self)
        self.start_watcher()
        nvim = self.nvim(None, "notes.py")
        self.attached(nvim)

        nvim.keys(self.KEY)

        self.assertIn("No review is open: open it to compare side by side", nvim.messages())
        self.assertEqual(len(self.windows(nvim)), 1)

    def test_a_buffer_gitsigns_has_not_attached_to_is_refused_and_opens_no_split(self):
        nvim = self.open_notes()
        nvim.command("enew")

        nvim.keys(self.KEY)

        self.assertIn("Open a file of the repository to compare it side by side", nvim.messages())
        self.assertEqual(len(self.windows(nvim)), 1)

    def test_without_gitsigns_it_says_so(self):
        ChoosingTheView.a_branch_of_three_commits(self)
        self.start_watcher()
        nvim = self.nvim(None, "notes.py", gitsigns=False)
        nvim.command("DifftateOpen")
        wait_for("the review to open", lambda: nvim.status() != "")

        nvim.keys(self.KEY)

        self.assertIn("gitsigns is not here: side by side needs it", nvim.messages())
        self.assertEqual(len(self.windows(nvim)), 1)

    def test_the_key_is_free_in_lazyvim_core_and_can_be_changed_or_turned_off(self):
        nvim = self.nvim(opts={"keys": {"side_by_side": "<leader>gZ"}})
        self.assertEqual(nvim.lua("return vim.fn.maparg('<leader>rd', 'n')"), "")
        self.assertNotEqual(nvim.lua("return vim.fn.maparg('<leader>gZ', 'n')"), "")
        off = self.nvim(opts={"keys": {"side_by_side": False}})
        self.assertEqual(off.lua("return vim.fn.maparg('<leader>rd', 'n')"), "")
        taken = self.nvim(before="vim.keymap.set('n', '<leader>rd', '<cmd>echo \"also\"<cr>', { desc = 'Also' })")
        self.assertIn("<leader>rd is already mapped (Also): set opts.keys.side_by_side to another key", taken.messages())
