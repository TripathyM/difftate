"""Layout D's split diff (#262): the Files changed tab's model once the reviewer chose split
(web/d/files_changed.js). The pairing itself is in test_browser_d_diff_rows.py. Node runs it."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js


def thread(id, side, line):
    """An open thread on app.py, whose line 2 is deleted and added."""
    first = released("GET", "/api/threads", lambda a: a)[0]
    anchor = dict(first["anchor"], file="app.py", side=side, startLine=line, endLine=line)
    return dict(first, id=id, anchor=anchor, outdated=False, status="open", inView=True)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheSplitDiff(unittest.TestCase):
    def run_page(self, steps, show, threads=()):
        return run_js("page", f"""
import * as st from "{{STATE}}";
import * as drafts from "{{DRAFTS}}";
let s = st.polled(st.initialState("files"), {json.dumps(answers(threads=list(threads)))});
const app = () => m.pageModel(s).body.files.find((f) => f.path === "app.py");
const lines = (rows) => rows.filter((r) => r.kind === "line");
{steps}
console.log(JSON.stringify({show}));""")

    def test_the_review_is_unified_until_the_reviewer_chooses_split_and_back(self):
        got = self.run_page("""
const seen = [];
const look = () => seen.push([m.pageModel(s).body.layout, lines(app().rows).length]);
look();
s = st.setLayout(s, "split");
look();
s = st.setLayout(s, "unified");
look();""", show="seen")

        self.assertEqual(got, [["unified", 3], ["split", 2], ["unified", 3]])

    def test_each_thread_stays_on_its_line_and_says_which_side_it_is_on(self):
        got = self.run_page('s = st.setLayout(s, "split");',
                            show="app().rows.map((r) => (r.kind === 'below' ? r.threads.map((t) => [t.id, t.side]) : [r.kind, r.old ?? null, r.new ?? null]))",
                            threads=[thread("on-new", "new", 2), thread("on-old", "old", 2)])

        self.assertEqual(got, [["hunk", None, None], ["line", 1, 1], ["line", 2, 2], [["on-old", "old"], ["on-new", "new"]]])

    def test_a_draft_stays_on_its_lines_with_its_text_in_both_layouts(self):
        got = self.run_page("""
const spot = { path: "app.py", side: "old", line: 2 };
s = drafts.dragEnd(drafts.dragStart(s, spot));
s = drafts.typeIn(s, s.own.active, "Why was this?");
const under = () => {
  const rows = app().rows;
  const at = rows.findIndex((r) => r.kind === "below");
  return [rows[at - 1].old, rows[at].drafts.map((d) => [d.side, d.text, d.was])];
};
const unified = under();
s = st.setLayout(s, "split");""", show="[unified, under()]")

        draft = [2, [["old", "Why was this?", None]]]
        self.assertEqual(got, [draft, draft])

    def test_picked_lines_are_marked_on_their_own_side_of_a_pair(self):
        got = self.run_page("""
s = st.setLayout(s, "split");
s = drafts.dragStart(s, { path: "app.py", side: "new", line: 1 });
s = drafts.dragOver(s, { path: "app.py", side: "new", line: 2 });""", show="lines(app().rows).map((r) => r.picked)")

        self.assertEqual(got, [["new"], ["new"]])

    def test_a_threads_link_goes_to_its_line_in_the_split_rows(self):
        got = self.run_page("""
s = st.setLayout(s, "split");
const files = m.pageModel(s).body.files;
s = st.showTab(s, "conversation");
const [{ where }] = m.pageModel(s).body.threads;
const row = files.find((f) => f.path === where.target.file).rows[where.target.row];""",
                            show="[row.right.type, row.new]", threads=[thread("on-new", "new", 2)])

        self.assertEqual(got, ["add", 2])


if __name__ == "__main__":
    unittest.main()
