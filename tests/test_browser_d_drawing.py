"""What layout D's drawing must leave alone (#257), so that a poll doesn't move the reviewer: the
nodes that didn't change (web/d/dom.js), and where the window is (web/d/scroll.js). Node runs it,
with fake nodes."""
import json
import shutil
import unittest

from browser_d import answers, run_js


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
    def target(self, now_folded, pinned=0, **shown):
        """The file to bring to the top, with <pinned> of the window under the pinned header.
        <shown>: path -> (was it folded, top, bottom) on screen."""
        files = [{"path": p, "folded": p in now_folded} for p in shown]
        was = {p: {"folded": f, "top": top, "bottom": bottom} for p, (f, top, bottom) in shown.items()}
        return run_js("scroll", f"""
const was = new Map(Object.entries({json.dumps(was)}));
console.log(JSON.stringify(m.foldTarget({json.dumps(files)}, (path) => was.get(path), {pinned})));""")

    def test_a_file_folded_while_the_reviewer_is_inside_it_comes_to_the_top(self):
        self.assertEqual(self.target(["b"], a=(False, -900, -400), b=(False, -300, 600)), "b")

    def test_a_file_folded_that_the_reviewer_scrolled_past_or_sees_the_top_of_moves_nothing(self):
        self.assertIsNone(self.target(["a", "c"], a=(False, -900, -400), b=(False, -300, 600), c=(False, 616, 900)))

    def test_inside_is_below_the_pinned_header_not_below_the_windows_top(self):
        self.assertEqual(self.target(["a"], pinned=100, a=(False, 60, 600)), "a")
        self.assertIsNone(self.target(["a"], pinned=100, a=(False, -300, 90)))
        self.assertIsNone(self.target(["a"], pinned=100, a=(False, 100, 600)))

    def test_a_file_that_was_folded_already_or_that_opens_moves_nothing(self):
        self.assertIsNone(self.target(["a"], a=(True, -10, 30), b=(True, -10, 30)))


@unittest.skipUnless(shutil.which("node"), "needs node")
class WhatIsOnScreenBelowThePinnedHeader(unittest.TestCase):
    """In a window 800 high whose top 100 is under the pinned header, a file's sticky header,
    below it, covers down to 144."""

    def shown(self, function, *boxes):
        """<function> of each of <boxes>, a node's (top, bottom) from the window's top."""
        boxes = [{"top": top, "bottom": bottom, "height": bottom - top} for top, bottom in boxes]
        return run_js("scroll", f"""
console.log(JSON.stringify({json.dumps(boxes)}.map((box) => m.{function}(box, {{ pinned: 100, height: 800 }}))));""")

    def test_a_line_is_on_screen_when_all_of_it_is_below_both_headers(self):
        self.assertEqual(self.shown("lineShown", (144, 164), (130, 150), (60, 80), (780, 800), (790, 810), (300, 300)),
                         [True, False, False, True, False, False])

    def test_a_file_or_a_thread_is_on_screen_while_any_of_it_shows_below_both_headers(self):
        self.assertEqual(self.shown("anyShown", (-500, 145), (-500, 144), (799, 900), (800, 900), (300, 300)),
                         [True, False, True, False, False])

    def test_a_node_the_keyboard_went_to_under_the_headers_is_scrolled_out_from_under_them(self):
        # Scrolled up by what is under them. One above the window the browser scrolls to itself
        self.assertEqual(self.shown("uncoverBy", (60, 80), (143, 163), (144, 164), (500, 520), (-30, -10)),
                         [-84, -1, 0, 0, 0])


# As much of a document as drawing the files needs: a tree of nodes
DOCUMENT = """
const node = (tag) => ({
  tag, children: [], parent: null, className: "", textContent: "", dataset: {},
  setAttribute() {}, addEventListener() {}, contains: () => false,
  getBoundingClientRect: () => ({ top: 0, bottom: 0 }),
  get classList() { return { contains: (name) => this.className.split(" ").includes(name) }; },
  append(...added) { for (const c of added) if (typeof c !== "string") this.insertBefore(c, null); },
  insertBefore(c, ref) { c.remove(); c.parent = this; this.children.splice(ref ? this.children.indexOf(ref) : this.children.length, 0, c); },
  replaceChildren(...added) { for (const c of [...this.children]) c.remove(); this.append(...added); },
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; },
});
const byId = new Map();
globalThis.document = {
  createElement: node, createElementNS: (_, tag) => node(tag), activeElement: null,
  getElementById: (id) => byId.get(id) ?? byId.set(id, node("div")).get(id),
};
const all = (n) => [n, ...n.children.flatMap(all)];
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class AFilesHeaderWhileItScrolls(unittest.TestCase):
    def test_a_header_can_stick_as_long_as_its_file_is_on_screen(self):
        # A sticky element stays only as long as its parent is on screen: the header's parent has
        # to be the file's whole card, diff and all. Drawn again with the file viewed too, which
        # draws the header anew
        got = run_js("draw_files", f"""
import * as st from "{{STATE}}";
import {{ pageModel }} from "{{PAGE}}";
{DOCUMENT}
let s = st.polled(st.initialState("files"), {json.dumps(answers())});
const seen = [];
const draw = () => {{
  m.drawFiles(pageModel(s).body, {{}});
  seen.push(document.getElementById("files").children.map((card) => {{
    const heads = all(card).filter((n) => n.className === "file-head");
    return [heads.length, heads[0].parent === card, all(card).some((n) => n.tag === "table")];
  }}));
}};
draw();
s = st.foldFile(st.viewedAnswered(s, ["app.py"]), "app.py", false);
draw();
console.log(JSON.stringify(seen));""")

        self.assertEqual(got, [[[1, True, True]] * 3] * 2)


if __name__ == "__main__":
    unittest.main()
