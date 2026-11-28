"""Hiding the comments in layout D's diff (#263, GitHub's i): the threads go from the rows of
Files changed, and what the reviewer is writing stays (web/d/files_changed.js and state.js, with
the page's model). Node runs it, with API answers shaped like the released transcript's."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js


def thread(id, **changes):
    """An open thread of the released transcript on line 1 of app.py's new side."""
    threads = released("GET", "/api/threads", lambda a: any(t["anchor"] for t in a))
    found = next(t for t in threads if t["anchor"])
    anchor = dict(found["anchor"], file="app.py", side="new", startLine=1, endLine=1)
    return dict(found, **dict({"id": id, "status": "open", "outdated": False, "inView": True, "anchor": anchor}, **changes))


THREADS = [thread("on-a-line"), thread("old-code", outdated=True)]


@unittest.skipUnless(shutil.which("node"), "needs node")
class HidingComments(unittest.TestCase):
    def run_page(self, steps, show, tab="files"):
        return run_js("page", f"""
import * as st from "{{STATE}}";
import * as d from "{{DRAFTS}}";
let s = st.polled(st.initialState({json.dumps(tab)}), {json.dumps(answers(threads=THREADS))});
const app = () => m.pageModel(s).body.files.find((f) => f.path === "app.py");
// The threads in app.py's rows and at its top, the drafts under its lines, and the rows between
const comments = () => [
  [...app().top.threads, ...app().rows.flatMap((r) => r.threads ?? [])].map((t) => t.id),
  app().rows.flatMap((r) => r.drafts ?? []).length,
  app().rows.filter((r) => r.kind === "below").length];
{steps}
console.log(JSON.stringify({show}));""")

    def test_it_takes_the_threads_out_of_the_diff_and_says_so_and_again_brings_them_back(self):
        got = self.run_page("""
const shown = [comments(), m.pageModel(s).body.commentsHidden];
s = st.toggleComments(s);
const hidden = [comments(), m.pageModel(s).body.commentsHidden];
s = st.toggleComments(s);""", show="[shown, hidden, [comments(), m.pageModel(s).body.commentsHidden]]")

        shown = [[["old-code", "on-a-line"], 0, 1], False]
        self.assertEqual(got, [shown, [[[], 0, 0], True], shown])

    def test_the_tree_still_counts_them_and_the_conversation_tab_still_links_to_their_lines(self):
        counts, targets = self.run_page("""
s = st.toggleComments(s);
const counts = m.pageModel(s).body.tree.map((r) => r.openThreads);
s = st.showTab(s, "conversation");""", show="[counts, m.pageModel(s).body.threads.map((t) => t.where.target)]")

        self.assertEqual(counts[0], 2)
        self.assertIn({"file": "app.py", "row": 1}, targets)  # after the hunk

    def test_following_a_threads_link_shows_the_comments_again(self):
        got = self.run_page("""
s = st.toggleComments(s);
s = st.followThread(st.showTab(s, "conversation"), "on-a-line", "app.py");""", show="comments()")

        self.assertEqual(got, [["old-code", "on-a-line"], 0, 1])

    def test_a_draft_being_written_stays_when_the_comments_are_hidden(self):
        got = self.run_page("""
s = d.dragEnd(d.dragStart(s, { path: "app.py", side: "new", line: 1 }));
s = d.typeIn(s, s.own.active, "Why?");
s = st.toggleComments(s);""", show="comments()")

        self.assertEqual(got, [[], 1, 1])

    def test_starting_a_comment_shows_the_comments_again_so_that_it_is_not_sent_out_of_sight(self):
        got = self.run_page("""
s = st.toggleComments(s);
s = d.dragEnd(d.dragStart(s, { path: "app.py", side: "new", line: 1 }));""", show="comments()")

        self.assertEqual(got, [["old-code", "on-a-line"], 1, 1])

    def test_on_the_conversation_tab_there_is_no_diff_to_hide_them_in(self):
        self.assertTrue(self.run_page("const was = s; s = st.toggleComments(s);", show="s === was", tab="conversation"))


if __name__ == "__main__":
    unittest.main()
