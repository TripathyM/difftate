"""Layout D's GitHub-like keys (#263): what a key press does, and that none does anything while
the reviewer types (web/d/keys.js). Node runs it."""
import json
import shutil
import unittest

from browser_d import run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheKeys(unittest.TestCase):
    def actions(self, *presses):
        """What each of the <presses> does: {key, ...modifiers, target} as a keydown event is."""
        return run_js("keys", f"""
const press = (p) => ({{ target: {{ tagName: "BODY" }}, ...p }});
console.log(JSON.stringify({json.dumps(presses)}.map((p) => m.keyAction(press(p)))));""")

    def test_t_c_i_1_and_2_are_githubs(self):
        self.assertEqual(self.actions(*[{"key": k} for k in "tci12"]),
                         ["filterFiles", "pickView", "toggleComments", "conversation", "files"])

    def test_another_key_does_nothing_nor_does_a_name_every_object_has(self):
        self.assertEqual(self.actions({"key": "x"}, {"key": "T"}, {"key": "3"}, {"key": "Escape"}, {"key": "constructor"}),
                         [None] * 5)

    def test_none_fires_inside_a_text_box(self):
        boxes = [{"tagName": "TEXTAREA"}, {"tagName": "INPUT", "type": "text"}, {"tagName": "INPUT", "type": "search"},
                 {"tagName": "SELECT"}, {"tagName": "DIV", "isContentEditable": True}]

        got = self.actions(*[{"key": k, "target": box} for box in boxes for k in "tci12"])

        self.assertEqual(got, [None] * 25)

    def test_a_checkbox_or_a_button_is_no_text_box(self):
        got = self.actions({"key": "i", "target": {"tagName": "INPUT", "type": "checkbox"}},
                           {"key": "i", "target": {"tagName": "BUTTON"}})

        self.assertEqual(got, ["toggleComments"] * 2)

    def test_the_browsers_own_shortcuts_and_an_input_methods_keys_are_left_alone(self):
        got = self.actions({"key": "t", "ctrlKey": True}, {"key": "t", "metaKey": True}, {"key": "1", "altKey": True},
                           {"key": "i", "isComposing": True}, {"key": "i", "defaultPrevented": True})

        self.assertEqual(got, [None] * 5)

    def test_holding_a_key_down_does_it_once(self):
        self.assertEqual(self.actions({"key": "i", "repeat": True}), [None])


if __name__ == "__main__":
    unittest.main()
