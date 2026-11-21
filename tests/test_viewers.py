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
        env = {"DT_HERDR": self.binary, "FAKE_HERDR_CALLS": self.calls_file, "FAKE_HERDR_TABS": self.tabs_file}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        test.addCleanup(patch.stop)

    def running(self, *tab_names):
        """Herdr is running, with these tabs."""
        tabs = [{"id": f"tab-{i}", "name": name} for i, name in enumerate(tab_names)]
        with open(self.tabs_file, "w") as f:
            json.dump({"spaces": [{"id": "space-1", "tabs": tabs}]}, f)

    def calls(self):
        try:
            with open(self.calls_file) as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return []
        return [line.split(" ", 2) for line in lines if not line.startswith("ls")]


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
