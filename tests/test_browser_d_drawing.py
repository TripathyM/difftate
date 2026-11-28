"""What layout D's drawing must leave alone (#257), so that a poll doesn't move the reviewer: the
nodes that didn't change (web/d/dom.js), and where the window is (web/d/scroll.js). Node runs it,
with fake nodes."""
import json
import shutil
import unittest

from browser_d import run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class PuttingNodesInPlace(unittest.TestCase):
    def moved(self, before, after):
        """(the children after place(), the nodes it inserted): a moved node loses its selection."""
        return run_js("dom", f"""
const inserted = [], children = [];
const take = (n) => {{ if (children.includes(n)) children.splice(children.indexOf(n), 1); }};
const nodes = new Map();
const node = (name) => nodes.get(name) ?? nodes.set(name, {{ name, remove() {{ take(this); }} }}).get(name);
children.push(...{json.dumps(before)}.map(node));
const parent = {{ children, insertBefore(n, ref) {{ inserted.push(n.name); take(n); children.splice(ref ? children.indexOf(ref) : children.length, 0, n); }},
  get lastElementChild() {{ return children.at(-1); }} }};
m.place(parent, {json.dumps(after)}.map(node));
console.log(JSON.stringify([children.map((n) => n.name), inserted]));""")

    def test_replacing_one_node_leaves_the_others_where_they_are(self):
        self.assertEqual(self.moved(["a", "b", "c", "d"], ["a", "B", "c", "d"]), [["a", "B", "c", "d"], ["B"]])

    def test_a_node_added_or_gone_moves_no_other(self):
        self.assertEqual(self.moved(["a", "c", "d"], ["a", "b", "c"]), [["a", "b", "c"], ["b"]])


@unittest.skipUnless(shutil.which("node"), "needs node")
class WhereAFoldLeavesTheWindow(unittest.TestCase):
    def target(self, now_folded, **shown):
        """The file to bring to the top. <shown>: path -> (was it folded, top, bottom) on screen."""
        files = [{"path": p, "folded": p in now_folded} for p in shown]
        was = {p: {"folded": f, "top": top, "bottom": bottom} for p, (f, top, bottom) in shown.items()}
        return run_js("scroll", f"""
const was = new Map(Object.entries({json.dumps(was)}));
console.log(JSON.stringify(m.foldTarget({json.dumps(files)}, (path) => was.get(path))));""")

    def test_a_file_folded_while_the_reviewer_is_inside_it_comes_to_the_top(self):
        self.assertEqual(self.target(["b"], a=(False, -900, -400), b=(False, -300, 600)), "b")

    def test_a_file_folded_that_the_reviewer_scrolled_past_or_sees_the_top_of_moves_nothing(self):
        self.assertIsNone(self.target(["a", "c"], a=(False, -900, -400), b=(False, -300, 600), c=(False, 616, 900)))

    def test_a_file_that_was_folded_already_or_that_opens_moves_nothing(self):
        self.assertIsNone(self.target(["a"], a=(True, -10, 30), b=(True, -10, 30)))


if __name__ == "__main__":
    unittest.main()
