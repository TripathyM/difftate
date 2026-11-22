"""The viewers `--open` names: the browser and the Neovim viewer (whose host
is Herdr when it is reachable). Herdr is faked: DT_HERDR points at a script that records each call and
answers `ls` from a file, as Herdr's app would."""
import io
import json
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
from difftate.adapters.inbound.cli import options, viewers  # noqa: E402

FAKE_HERDR = """#!/bin/sh
echo "$@" >> "$FAKE_HERDR_CALLS"
if [ "$1" = ls ]; then
  [ -f "$FAKE_HERDR_TABS" ] || exit 1
  cat "$FAKE_HERDR_TABS"
fi
exit 0
"""


FAKE_HC = """#!/bin/sh
echo "$@" >> "$FAKE_HERDR_CALLS"
[ "$1" = get ] && [ "$3" = --json ] && cat "$FAKE_HC_DIR/$2.json"
"""


class HerdrFake:
    def __init__(self, test):
        self.dir = tempfile.mkdtemp(prefix="difftate-viewers-")
        test.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.binary = os.path.join(self.dir, "herdr-app")
        with open(self.binary, "w") as f:
            f.write(FAKE_HERDR)
        os.chmod(self.binary, os.stat(self.binary).st_mode | stat.S_IXUSR)
        self.calls_file = os.path.join(self.dir, "calls")
        self.tabs_file = os.path.join(self.dir, "tabs.json")
        self.hc = os.path.join(self.dir, "hc")
        with open(self.hc, "w") as f:
            f.write(FAKE_HC)
        os.chmod(self.hc, os.stat(self.hc).st_mode | stat.S_IXUSR)
        self.hc_dir = os.path.join(self.dir, "terminals")
        os.mkdir(self.hc_dir)
        env = {"DT_HERDR": self.binary, "DT_HC": self.hc, "FAKE_HC_DIR": self.hc_dir,
               "FAKE_HERDR_CALLS": self.calls_file, "FAKE_HERDR_TABS": self.tabs_file}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        test.addCleanup(patch.stop)

    def running(self, *tab_names):
        """Herdr is running, with these tabs."""
        tabs = [{"id": f"tab-{i}", "name": name} for i, name in enumerate(tab_names)]
        with open(self.tabs_file, "w") as f:
            json.dump({"spaces": [{"id": "space-1", "tabs": tabs}]}, f)

    def review_tab(self, name, *foregrounds):
        """Herdr runs a tab <name> in space-1 with one terminal for each of <foregrounds>: the program in
        the terminal's foreground (its argv[0]), as `hc get` reports it."""
        terminals = []
        for i, program in enumerate(foregrounds):
            terminals.append({"terminal": f"t{i}", "app": None})
            with open(os.path.join(self.hc_dir, f"t{i}.json"), "w") as f:
                json.dump({"address": f"t{i}", "foreground": {"argv": [program, "-li"], "name": os.path.basename(program)}}, f)
        with open(self.tabs_file, "w") as f:
            json.dump({"spaces": [{"id": "space-1", "tabs": [
                {"id": "tab-0", "name": "1", "terminals": []},
                {"id": "tab-1", "name": name, "terminals": terminals}]}]}, f)

    def calls(self):
        try:
            with open(self.calls_file) as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return []
        return [line.split(" ", 2) for line in lines if line.startswith("do ")]


class ViewersTest(unittest.TestCase):
    def setUp(self):
        self.herdr = HerdrFake(self)
        self.root = "/work/shop-api"
        self.name = "Review · shop-api"

    def open_nvim(self):
        out = io.StringIO()
        with redirect_stdout(out):
            opened = viewers.open_in_nvim("http://127.0.0.1:1/", self.root)
        return opened, out.getvalue()

    def test_in_herdr_with_no_review_tab_nvim_opens_one_running_the_review(self):
        self.herdr.running("1", "2")

        opened, said = self.open_nvim()

        self.assertTrue(opened)
        [[do, verb, args]] = self.herdr.calls()
        self.assertEqual((do, verb), ("do", "tab.new"))
        self.assertEqual(json.loads(args), {"name": self.name, "folder": self.root,
                                            "argv": ["nvim", "+DifftateOpen"]})
        self.assertIn(self.name, said)

    def test_in_herdr_with_a_review_tab_nvim_switches_to_it(self):
        self.herdr.running("1", self.name)

        opened, _ = self.open_nvim()

        self.assertTrue(opened)
        [[do, verb, args]] = self.herdr.calls()
        self.assertEqual((do, verb, json.loads(args)), ("do", "tab.select", {"id": "tab-1"}))

    def test_a_review_tab_where_nvim_runs_is_only_switched_to(self):
        self.herdr.review_tab(self.name, "/opt/homebrew/bin/nvim")

        self.open_nvim()

        [[do, verb, args]] = self.herdr.calls()
        self.assertEqual((verb, json.loads(args)), ("tab.select", {"id": "tab-1"}))

    def test_a_review_tab_whose_nvim_has_quit_is_opened_again_then_the_old_one_closed(self):
        self.herdr.review_tab(self.name, "/bin/zsh")

        opened, said = self.open_nvim()

        self.assertTrue(opened)
        [new, close] = self.herdr.calls()
        self.assertEqual(new[1], "tab.new")
        self.assertEqual(json.loads(new[2]), {"name": self.name, "folder": self.root, "space": "space-1",
                                              "argv": ["nvim", "+DifftateOpen"]})
        self.assertEqual((close[1], json.loads(close[2])), ("tab.close", {"id": "tab-1", "confirmed": True}))
        self.assertIn(self.name, said)

    def test_a_login_shell_with_a_dash_counts_as_a_shell(self):
        self.herdr.review_tab(self.name, "-zsh")

        self.open_nvim()

        self.assertEqual([c[1] for c in self.herdr.calls()], ["tab.new", "tab.close"])

    def test_the_old_tab_stays_when_the_new_one_will_not_open(self):
        self.herdr.review_tab(self.name, "/bin/zsh")
        with open(self.herdr.binary, "w") as f:
            f.write("#!/bin/sh\n[ \"$1\" = ls ] && cat \"$FAKE_HERDR_TABS\" && exit 0\necho \"$@\" >> \"$FAKE_HERDR_CALLS\"\n"
                    "[ \"$2\" = tab.select ]\n")

        self.open_nvim()

        self.assertEqual([c[1] for c in self.herdr.calls()], ["tab.new", "tab.select"])

    def test_a_review_tab_running_something_else_than_a_shell_is_not_closed(self):
        self.herdr.review_tab(self.name, "/bin/zsh", "/usr/bin/python3")

        self.open_nvim()

        [[do, verb, _]] = self.herdr.calls()
        self.assertEqual(verb, "tab.select")

    def test_when_hc_cannot_say_what_runs_the_tab_is_only_switched_to(self):
        self.herdr.review_tab(self.name, "/bin/zsh")
        os.remove(os.path.join(self.herdr.hc_dir, "t0.json"))

        self.open_nvim()

        self.assertEqual([c[1] for c in self.herdr.calls()], ["tab.select"])

    def test_with_no_hc_the_tab_is_only_switched_to(self):
        self.herdr.review_tab(self.name, "/bin/zsh")

        with mock.patch.dict(os.environ, {"DT_HC": os.path.join(self.herdr.dir, "none")}), \
                mock.patch("shutil.which", return_value=None):
            self.open_nvim()

        self.assertEqual([c[1] for c in self.herdr.calls()], ["tab.select"])

    def test_in_herdr_a_tab_that_will_not_open_prints_the_command_and_does_not_fall_back(self):
        self.herdr.running("1")
        with open(self.herdr.binary, "w") as f:
            f.write("#!/bin/sh\n[ \"$1\" = ls ] && cat \"$FAKE_HERDR_TABS\" && exit 0\nexit 1\n")

        opened, said = self.open_nvim()

        self.assertTrue(opened, "the browser is not the fallback of the Neovim viewer")
        self.assertIn(f"cd {self.root} && nvim +DifftateOpen", said)

    def test_outside_herdr_nothing_opens_and_the_command_is_printed(self):
        # Herdr is not running: `herdr-app ls` fails
        opened, said = self.open_nvim()

        self.assertTrue(opened, "the browser is not the fallback of the Neovim viewer")
        self.assertEqual(self.herdr.calls(), [])
        self.assertIn(f"cd {self.root} && nvim +DifftateOpen", said)

    def test_with_no_herdr_at_all_the_command_is_printed(self):
        with mock.patch.dict(os.environ, {"DT_HERDR": os.path.join(self.herdr.dir, "none")}):
            opened, said = self.open_nvim()

        self.assertTrue(opened)
        self.assertIn(f"cd {self.root} && nvim +DifftateOpen", said)

    def test_the_folder_with_a_space_is_quoted_in_the_printed_command(self):
        self.root = "/work/my shop"

        _, said = self.open_nvim()

        self.assertIn("cd '/work/my shop' && nvim +DifftateOpen", said)

    def test_open_both_opens_every_viewer_the_browser_last(self):
        order = []
        table = {"browser": lambda url, root: order.append("browser") or True,
                 "nvim": lambda url, root: order.append("nvim") or True}

        viewers.open_review(table, "both", "u", "/r")

        self.assertEqual(order[-1], "browser")
        self.assertEqual(sorted(order), ["browser", "nvim"])

    def test_the_composition_names_two_viewers_and_both(self):
        self.assertEqual(set(main.VIEWERS), {"browser", "nvim"})
        self.assertFalse(hasattr(viewers, "open_in_herdr"))
        self.assertEqual(viewers.where_to_open(main.VIEWERS), (*main.VIEWERS, "both"))
        self.assertIn("nvim", viewers.where_to_open(main.VIEWERS))

    def test_open_herdr_is_refused_like_any_unknown_value_naming_the_three_values(self):
        for argv, env in ((["--open", "herdr"], {}), ([], {"DT_OPEN": "herdr"})):
            with mock.patch.dict(os.environ, env), self.assertRaises(options.Exit) as raised:
                options.parse(argv, viewers.where_to_open(main.VIEWERS))
            self.assertEqual(raised.exception.code, 1)
            self.assertIn("must be browser, nvim or both, not 'herdr'", raised.exception.message)

    def test_open_accepts_nvim_and_the_help_names_the_three_values(self):
        opts = options.parse(["--open", "nvim"], viewers.where_to_open(main.VIEWERS))
        self.assertEqual(opts["open"], "nvim")
        with mock.patch.dict(os.environ, {"DT_OPEN": "nvim"}):
            opts = options.parse([], viewers.where_to_open(main.VIEWERS))
        self.assertEqual(opts["open"], "nvim")
        self.assertRegex(options.USAGE, r"browser, nvim or both")
        self.assertNotIn("herdr:", options.USAGE)


if __name__ == "__main__":
    unittest.main()
