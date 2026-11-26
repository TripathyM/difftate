"""The viewers `--open` names: the browser and the Neovim viewer (nvim here when there is a terminal,
the command to run when there is none). difftate opens no host: a fake Herdr records any call, and the
tests check there is none."""
import dataclasses
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate import main  # noqa: E402
from difftate.adapters.inbound.cli import options, run_difftate, viewers  # noqa: E402

FAKE_HERDR = """#!/bin/sh
echo "$@" >> "$FAKE_HERDR_CALLS"
exit 0
"""


class HerdrFake:
    """A herdr-app on PATH and as DT_HERDR (a leftover setting) that records every call: difftate must make none."""
    def __init__(self, test):
        self.dir = tempfile.mkdtemp(prefix="difftate-viewers-")
        test.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.binary = os.path.join(self.dir, "herdr-app")
        with open(self.binary, "w") as f:
            f.write(FAKE_HERDR)
        os.chmod(self.binary, os.stat(self.binary).st_mode | stat.S_IXUSR)
        self.calls_file = os.path.join(self.dir, "calls")
        env = {"DT_HERDR": self.binary, "FAKE_HERDR_CALLS": self.calls_file,
               "PATH": self.dir + os.pathsep + os.environ.get("PATH", "")}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        test.addCleanup(patch.stop)

    def called(self):
        return os.path.exists(self.calls_file)


class ViewersTest(unittest.TestCase):
    def setUp(self):
        self.herdr = HerdrFake(self)
        self.root = "/work/shop-api"

    def open_nvim(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(viewers, "_has_terminal", return_value=False):
            opened = viewers.open_in_nvim("http://127.0.0.1:1/", self.root)
        return opened, out.getvalue()

    def open_nvim_in_terminal(self, exec_nvim=None):
        """open_in_nvim with a terminal (stdin and stdout ttys); the exec is faked and recorded."""
        execs = []
        out = io.StringIO()
        fake = exec_nvim or (lambda root: execs.append(root))
        with redirect_stdout(out), mock.patch.object(viewers, "_has_terminal", return_value=True), \
                mock.patch.object(viewers, "_exec_nvim", fake):
            opened = viewers.open_in_nvim("http://127.0.0.1:1/", self.root)
        return opened, out.getvalue(), execs

    def test_with_a_terminal_nvim_runs_here_in_the_review_root_and_herdr_is_never_called(self):
        _, _, execs = self.open_nvim_in_terminal()

        self.assertEqual(execs, [self.root])
        self.assertFalse(self.herdr.called())

    def test_the_exec_runs_nvim_with_difftateopen_in_the_root(self):
        with mock.patch("shutil.which", return_value="/bin/nvim"), mock.patch("os.chdir") as chdir, \
                mock.patch("os.execvp") as execvp:
            viewers._exec_nvim(self.root)

        chdir.assert_called_once_with(self.root)
        execvp.assert_called_once_with("nvim", ["nvim", "+DifftateOpen"])

    def test_with_no_nvim_on_path_it_is_a_clear_error_and_exit_1(self):
        err = io.StringIO()
        with mock.patch("shutil.which", return_value=None), mock.patch("os.execvp") as execvp, \
                mock.patch("sys.stderr", err), self.assertRaises(SystemExit) as raised:
            self.open_nvim_in_terminal(viewers._exec_nvim)

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(err.getvalue().strip(), "difftate: nvim not found on PATH")
        execvp.assert_not_called()
        self.assertFalse(self.herdr.called())

    def test_an_exec_that_fails_is_the_same_error_and_exit_1(self):
        err = io.StringIO()
        with mock.patch("shutil.which", return_value="/bin/nvim"), mock.patch("os.chdir"), \
                mock.patch("os.execvp", side_effect=OSError), mock.patch("sys.stderr", err), \
                self.assertRaises(SystemExit) as raised:
            viewers._exec_nvim(self.root)

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("difftate: nvim", err.getvalue())

    def test_the_terminal_check_needs_stdin_and_stdout_both_ttys(self):
        for stdin, stdout, expected in ((True, True, True), (True, False, False), (False, True, False)):
            with mock.patch("sys.stdin") as i, mock.patch("sys.stdout") as o:
                i.isatty.return_value, o.isatty.return_value = stdin, stdout
                self.assertEqual(viewers._has_terminal(), expected)

    def test_with_no_terminal_the_command_is_printed_and_the_browser_is_not_the_fallback(self):
        opened, said = self.open_nvim()

        self.assertTrue(opened, "the browser is not the fallback of the Neovim viewer")
        self.assertIn(f"cd {self.root} && nvim +DifftateOpen", said)

    def test_with_no_terminal_herdr_is_never_called_even_when_it_is_on_path_and_in_dt_herdr(self):
        self.open_nvim()

        self.assertFalse(self.herdr.called())

    def test_difftate_has_no_herdr_host_left(self):
        for name in ("_herdr_cli", "_hc_cli", "_herdr_tab", "_nvim_in_herdr", "NVIM_HOSTS", "_only_idle_shells"):
            self.assertFalse(hasattr(viewers, name), name)

    def test_the_folder_with_a_space_is_quoted_in_the_printed_command(self):
        self.root = "/work/my shop"

        _, said = self.open_nvim()

        self.assertIn("cd '/work/my shop' && nvim +DifftateOpen", said)

    def test_open_both_opens_every_viewer_the_browser_first_because_nvim_may_exec(self):
        order = []
        table = {"browser": lambda url, root: order.append("browser") or True,
                 "nvim": lambda url, root: order.append("nvim") or True}

        viewers.open_review(table, "both", "u", "/r")

        self.assertEqual(order, ["browser", "nvim"])

    def test_the_composition_names_two_viewers_both_and_none(self):
        self.assertEqual(set(main.VIEWERS), {"browser", "nvim"})
        self.assertFalse(hasattr(viewers, "open_in_herdr"))
        self.assertEqual(viewers.where_to_open(main.VIEWERS), (*main.VIEWERS, "both", "none"))
        self.assertIn("nvim", viewers.where_to_open(main.VIEWERS))

    def test_open_herdr_is_refused_like_any_unknown_value_naming_the_four_values(self):
        for argv, env in ((["--open", "herdr"], {}), ([], {"DT_OPEN": "herdr"})):
            with mock.patch.dict(os.environ, env), self.assertRaises(options.Exit) as raised:
                options.parse(argv, viewers.where_to_open(main.VIEWERS))
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("must be browser, nvim, both or none, not 'herdr'", raised.exception.message)

    def test_open_accepts_nvim_and_the_help_names_the_four_values(self):
        opts = options.parse(["--open", "nvim"], viewers.where_to_open(main.VIEWERS))
        self.assertEqual(opts["open"], "nvim")
        with mock.patch.dict(os.environ, {"DT_OPEN": "nvim"}):
            opts = options.parse([], viewers.where_to_open(main.VIEWERS))
        self.assertEqual(opts["open"], "nvim")
        self.assertRegex(options.USAGE, r"browser, nvim, both or none")
        self.assertRegex(options.USAGE, r"none: [^.]*your own viewer[^.]*finds the watcher")
        self.assertNotIn("herdr:", options.USAGE)


class OpenNoneTest(unittest.TestCase):
    """`--open none`, for the reviewer's own viewer: the `difftate` command with fake wiring."""
    def setUp(self):
        home = tempfile.mkdtemp(prefix="difftate-open-none-")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("DT_OPEN", None)
        os.environ.pop("DT_INTERVAL", None)
        self.started, self.asked, self.opened = [], [], []

        def start_watcher(args):
            self.started.append(args)
            return lambda: True

        def ask(home, method, path, payload=None):
            self.asked.append((method, path, payload))
            route = path.split("?")[0]
            return 200, {"/api/review": {"branch": "feature", "base": "develop"},
                         "/api/view": {"view": "HEAD~1"},
                         "/api/launch": {"url": "http://127.0.0.1:1/?launch=code"}}[route]

        self.wiring = dataclasses.replace(
            main.wiring(), difftate_home=home,
            viewers={name: lambda url, root, name=name: self.opened.append(name) or True for name in main.VIEWERS},
            difftate_folder=lambda cwd: mock.Mock(root="/work/shop-api"),
            running_watcher=lambda home: 4242 if self.started else None,
            start_watcher=start_watcher, ask_running_watcher=ask, agent_choice=lambda root: None)

    def difftate(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = run_difftate(list(argv), self.wiring)
        return code, out.getvalue()

    def routes(self):
        return [(method, path.split("?")[0]) for method, path, _ in self.asked]

    def test_open_none_starts_the_watcher_adds_the_review_and_opens_nothing(self):
        code, said = self.difftate("HEAD~1", "--base", "develop", "--open", "none")

        self.assertEqual(code, 0, said)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.routes(), [("GET", "/api/review"), ("PUT", "/api/view")], "no link is asked for")
        self.assertIn("base=develop", self.asked[0][1])
        self.assertEqual(self.asked[1][2], {"view": "HEAD~1"})
        self.assertEqual(said.strip(), "difftate is running (pid 4242): the review of feature against develop "
                                       "in /work/shop-api, showing the commits after HEAD~1")
        self.assertEqual(self.opened, [])

    def test_dt_open_none_makes_it_the_default(self):
        os.environ["DT_OPEN"] = "none"

        code, said = self.difftate()

        self.assertEqual(code, 0, said)
        self.assertNotIn(("POST", "/api/launch"), self.routes())
        self.assertEqual(self.opened, [])

    def test_open_overrides_dt_open_none(self):
        os.environ["DT_OPEN"] = "none"

        self.difftate("--open", "browser")

        self.assertIn(("POST", "/api/launch"), self.routes())
        self.assertEqual(self.opened, ["browser"])


if __name__ == "__main__":
    unittest.main()
