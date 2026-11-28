"""Layout D's Vim key map (#264, web/d/keymap.js): (defaults, the reviewer's changes) →
bindings, and (bindings, keys pressed) → action. Node runs it."""
import json
import shutil
import unittest

from browser_d import run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheKeyMap(unittest.TestCase):
    def typed(self, keys, changes=None):
        """What each of <keys> does, one after another, with the reviewer's <changes>: the
        action, "…" while a longer key goes on, "swallowed", or None when the key map leaves it."""
        return run_js("keymap", f"""
const bindings = m.bindingsOf({json.dumps(changes or {})});
let pending = [];
console.log(JSON.stringify({json.dumps(keys)}.map((token) => {{
  const step = m.step(bindings, pending, token);
  pending = step.pending;
  return step.action ?? (!step.took ? null : pending.length ? "…" : "swallowed");
}})));""")

    def test_the_default_keys_are_the_neovim_viewers_under_its_action_names(self):
        review = {"c": "comment", "t": "thread", "a": "add_comment", "R": "resolve", "O": "reopen", "e": "expand",
                  "G": "general", "s": "threads", "f": "files", "F": "files_sidebar", "v": "viewed", "V": "views",
                  "M": "mode", "S": "submit", "A": "agent", "D": "done", "E": "export", "d": "side_by_side"}

        got = self.typed([token for key in review for token in (" ", "r", key)])

        self.assertEqual(got, [step for action in review.values() for step in ("…", "…", action)])
        self.assertEqual(self.typed(["]", "r", "[", "r"]), ["…", "next", "…", "previous"])

    def test_the_cursors_keys(self):
        got = self.typed(["j", "k", "h", "l", "G", "C-d", "C-u", "V", "v", "?", "g", "g"])

        self.assertEqual(got, ["down", "up", "old_side", "new_side", "last", "half_down", "half_up",
                               "visual_line", "visual", "help", "…", "first"])
        self.assertEqual(self.typed(["]", "h", "[", "h", "]", "f", "[", "f"]),
                         ["…", "next_hunk", "…", "previous_hunk", "…", "next_file", "…", "previous_file"])

    def test_p_shows_the_review_path_and_no_default_key_clashes(self):
        got = run_js("keymap", """
console.log(JSON.stringify([m.step(m.bindingsOf({}), [], "p").action,
  m.allKeys({}).flatMap((g) => g.rows).filter((r) => r.note).map((r) => r.name)]));""")

        self.assertEqual(got, ["review_path", []])

    def test_a_key_that_ends_no_sequence_ends_it_and_does_nothing(self):
        self.assertEqual(self.typed([" ", "x", "j"]), ["…", "swallowed", "down"])

    def test_a_key_that_is_no_vim_key_is_left_to_the_page(self):
        self.assertEqual(self.typed(["t", "c", "i", "1", "2", "x"]), [None] * 6)

    def test_a_changed_key_does_the_action_and_the_old_one_no_longer(self):
        self.assertEqual(self.typed(["j", "n"], {"down": "n"}), [None, "down"])
        self.assertEqual(self.typed([" ", "x", "x"], {"comment": "<leader>xx"}), ["…", "…", "comment"])

    def test_a_turned_off_key_does_nothing(self):
        self.assertEqual(self.typed(["j", "k"], {"down": ""}), [None, "up"])
        # and a sequence none of whose actions is on doesn't start
        self.assertEqual(self.typed(["g", "g"], {"first": ""}), [None, None])

    def test_a_vim_key_never_takes_one_of_the_pages_own(self):
        got = self.typed(["t", "i", "1", "g"], {"down": "t", "up": "i", "last": "1g"})

        self.assertEqual(got, [None, None, None, "…"])


    def test_a_bracket_typed_with_Option_or_AltGr_is_a_bracket(self):
        got = run_js("keymap", """
console.log(JSON.stringify([{ key: "[", altKey: true }, { key: "]", altKey: true, ctrlKey: true },
  { key: "j", altKey: true }, { key: "d", ctrlKey: true }, { key: "[", metaKey: true }].map(m.tokenOf)));""")

        self.assertEqual(got, ["[", "]", None, "C-d", None])


@unittest.skipUnless(shutil.which("node"), "needs node")
class WhichKeyAndAllKeys(unittest.TestCase):
    def test_which_key_lists_what_can_follow_a_group_where_several_actions_share_it(self):
        got = run_js("keymap", """
const bindings = m.bindingsOf({});
console.log(JSON.stringify([m.whichKey(bindings, [" "]), m.whichKey(bindings, ["g"]), m.whichKey(bindings, [" ", "r"]), m.whichKey(bindings, [])]));""")

        leader, g, review, none = got
        self.assertEqual(leader, {"title": "Space …", "keys": [{"key": "r", "text": "+review"}]})
        self.assertEqual(g, {"title": "g …", "keys": [{"key": "g", "text": "First line"}]})
        self.assertEqual(review["title"], "Space r …")
        self.assertIn({"key": "c", "text": "Comment on this line or selection"}, review["keys"])
        self.assertEqual(len(review["keys"]), 18)
        self.assertIsNone(none)

    def rows(self, changes):
        """All keys, by action name."""
        got = run_js("keymap", f"""
console.log(JSON.stringify(m.allKeys({json.dumps(changes)})));""")
        return {row["name"]: row for group in got for row in group["rows"]}

    def test_all_keys_lists_every_action_with_its_key_as_neovim_writes_it(self):
        rows = self.rows({"down": "n", "up": ""})

        self.assertEqual((rows["comment"]["key"], rows["comment"]["note"]), ("<leader>rc", ""))
        self.assertEqual((rows["down"]["key"], rows["down"]["changed"]), ("n", True))
        self.assertEqual((rows["up"]["key"], rows["up"]["note"]), ("", "off"))

    def test_all_keys_says_when_a_key_cannot_work(self):
        rows = self.rows({"down": "t", "up": "G", "first": "<leader>r"})

        self.assertEqual(rows["down"]["note"], "off: t is one of the page's own keys")
        self.assertEqual((rows["up"]["note"], rows["last"]["note"]), ("clashes with last", "clashes with up"))
        self.assertIn("clashes with", rows["comment"]["note"])

    def test_all_keys_says_when_it_cannot_read_a_key_which_then_is_off(self):
        rows = self.rows({"down": "<CR>", "up": "<S-j>", "first": "Space x", "last": "<C-g>", "visual": "<<"})

        unread = "off: write keys as Neovim does; of the <…> names only <leader> and <C-d>'s kind work"
        self.assertEqual([rows[n]["note"] for n in ("down", "up", "first", "last", "visual")],
                         [unread, unread, unread, "", ""])
        self.assertEqual(run_js("keymap", """
console.log(JSON.stringify(m.bindingsOf({ down: "<CR>" }).some((b) => b.name === "down")));"""), False)


if __name__ == "__main__":
    unittest.main()
