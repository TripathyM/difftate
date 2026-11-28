"""Layout D's settings (#262): the diff's layout and the theme, which follows the system until the
reviewer picks one, kept in the browser (web/d/settings.js, with the page's model). Node runs it,
with a fake browser storage."""
import json
import shutil
import unittest

from browser_d import answers, run_js

# A browser's storage, as localStorage is, and a reload: a new page state with what was kept
PAGE = """
import * as st from "{STATE}";
import * as page from "{PAGE}";
const stored = new Map();
const storage = {
  getItem: (key) => (stored.has(key) ? stored.get(key) : null),
  setItem: (key, value) => stored.set(key, String(value)),
  removeItem: (key) => stored.delete(key),
};
const open = (kept = m.readSettings(storage)) => st.initialState("files", kept);
let s = open();
const change = (next) => { s = next; m.keepSettings(storage, s.own.settings); };
const reload = () => { s = open(); };
const shown = () => page.pageModel(s).settings;
const theme = () => { const t = shown(); return [t.theme, t.follows, t.flip.to, t.flip.icon]; };
const layout = () => shown().layouts.find((l) => l.current).layout;"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class Settings(unittest.TestCase):
    def run_page(self, steps, show):
        return run_js("settings", f"""
{PAGE}
{steps}
console.log(JSON.stringify({show}));""")


class TheTheme(Settings):
    def test_by_default_the_theme_follows_the_system_and_the_switch_offers_the_other_one(self):
        got = self.run_page("""
const light = theme();
change(st.systemTheme(s, true));""", show="[light, theme()]")

        # (the theme the page forces, null: none; follows the system; the switch's theme and icon)
        self.assertEqual(got, [[None, True, "dark", "moon"], [None, True, "light", "sun"]])

    def test_the_switch_shows_the_other_theme_which_then_no_longer_follows_the_system(self):
        got = self.run_page("""
change(m.switchTheme(s));
const switched = theme();
change(st.systemTheme(s, true));
const systemDark = theme();
change(m.switchTheme(s));""", show="[switched, systemDark, theme()]")

        self.assertEqual(got, [["dark", False, "light", "sun"], ["dark", False, "light", "sun"],
                               ["light", False, "dark", "moon"]])

    def test_follow_the_system_goes_back_to_it_and_turned_off_keeps_the_theme_on_screen(self):
        got = self.run_page("""
change(st.systemTheme(s, true));
change(m.followSystem(s, false));
const off = theme();
change(st.systemTheme(s, false));
const stays = theme();
change(m.followSystem(s, true));""", show="[off, stays, theme()]")

        self.assertEqual(got, [["dark", False, "light", "sun"], ["dark", False, "light", "sun"],
                               [None, True, "dark", "moon"]])

    def test_the_switch_says_what_it_does(self):
        self.assertEqual(self.run_page("", show="shown().flip.text"), "Switch to the dark theme")


class KeptInTheBrowser(Settings):
    def test_a_chosen_theme_and_layout_are_there_after_a_reload(self):
        got = self.run_page("""
change(m.switchTheme(s));
change(st.setLayout(s, "split"));
reload();""", show="[theme()[0], layout()]")

        self.assertEqual(got, ["dark", "split"])

    def test_following_the_system_again_is_kept_too(self):
        got = self.run_page("""
change(m.switchTheme(s));
change(m.followSystem(s, true));
reload();""", show="theme().slice(0, 2)")

        self.assertEqual(got, [None, True])

    def test_with_nothing_kept_or_something_unknown_the_diff_is_unified_and_the_theme_follows(self):
        got = self.run_page("""
const nothing = [layout(), theme()[0]];
stored.set("difftate.layout", "three-way");
stored.set("difftate.theme", "sepia");
reload();""", show="[nothing, [layout(), theme()[0]]]")

        self.assertEqual(got, [["unified", None], ["unified", None]])

    def test_a_browser_that_refuses_storage_still_shows_the_page_and_takes_choices(self):
        got = self.run_page("""
const refuses = () => { throw new Error("SecurityError"); };
const none = { getItem: refuses, setItem: refuses, removeItem: refuses };
const got = [];
for (const broken of [none, null]) {
  s = open(m.readSettings(broken));
  s = m.switchTheme(st.setLayout(s, "split"));
  m.keepSettings(broken, s.own.settings);
  got.push([layout(), theme()[0]]);
}""", show="got")

        self.assertEqual(got, [["split", "dark"], ["split", "dark"]])


class SettingsAndPolls(Settings):
    def test_the_page_has_its_settings_before_the_first_answers_and_a_poll_keeps_them(self):
        other = answers()
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.run_page(f"""
change(m.switchTheme(st.setLayout(s, "split")));
const loading = [layout(), theme()[0]];
s = st.polled(st.polled(s, {json.dumps(answers())}), {json.dumps(other)});""",
                            show="[loading, [layout(), theme()[0]]]")

        self.assertEqual(got, [["split", "dark"], ["split", "dark"]])


if __name__ == "__main__":
    unittest.main()
