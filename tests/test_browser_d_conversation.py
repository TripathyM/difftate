"""Layout D's Conversation tab (#258): the timeline of threads, as the page draws it
(web/d/page.js over conversation.js). Node runs it, with threads shaped like the released
transcript's."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js


def released_thread(having):
    """A thread of the released transcript that <having> accepts."""
    threads = released("GET", "/api/threads", lambda a: any(having(t) for t in a))
    return next(t for t in threads if having(t))


def at(thread, minute, **changes):
    """<thread> opened at <minute> past ten, with <changes>."""
    first, *rest = thread["comments"]
    return dict(thread, comments=[dict(first, time=f"2026-01-01T10:{minute:02}:00+00:00"), *rest], **changes)


def general():
    return released_thread(lambda t: t["anchor"] is None and t["status"] == "open")


def outdated():
    return released_thread(lambda t: t["outdated"] and t["status"] == "open")


def replied():
    return released_thread(lambda t: any(c["author"] == "agent" for c in t["comments"])
                           and any(c["author"] == "difftate" for c in t["comments"]))


class Conversation(unittest.TestCase):
    def body(self, threads, steps="", **poll):
        """The Conversation tab after a poll with <threads>, then the JS lines <steps>."""
        return run_js("page", f"""
import * as st from "{{STATE}}";
let s = st.polled(st.initialState("conversation"), {json.dumps(answers(threads=threads, **poll))});
{steps}
console.log(JSON.stringify(m.pageModel(s).body));""")


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheTimeline(Conversation):
    def test_every_thread_is_on_it_the_one_opened_first_at_the_top(self):
        threads = [at(replied(), 30, id="last"), at(general(), 10, id="first"), at(outdated(), 20, id="middle")]

        body = self.body(threads)

        self.assertEqual(body["kind"], "conversation")
        self.assertEqual([t["id"] for t in body["threads"]], ["first", "middle", "last"])
        self.assertEqual(body["empty"], "")

    def test_a_thread_shows_its_comments_the_agents_replies_and_the_progress_notes_in_order(self):
        thread = replied()

        [card] = self.body([thread])["threads"]

        shown = [(c["kind"], c.get("agent")) for c in card["comments"]]
        wanted = [("note", None) if c["author"] == "difftate" else ("comment", c["author"] == "agent")
                  for c in thread["comments"]]
        self.assertEqual(shown, wanted)

    def test_an_outdated_thread_shows_the_code_it_was_written_on_labelled_outdated(self):
        thread = outdated()

        [card] = self.body([thread])["threads"]

        self.assertEqual(card["written"], {"text": "Written on line 1:", "code": "def greet(nam):"})
        self.assertIn("Outdated", [label["text"] for label in card["labels"]])

    def test_each_thread_says_where_it_is_a_line_thread_by_its_file_and_lines(self):
        line = outdated()
        ranged = dict(line, id="ranged", anchor=dict(line["anchor"], file="gone.py", side="old", startLine=5, endLine=7))

        cards = self.body([at(general(), 1), at(line, 2), at(ranged, 3)])["threads"]

        self.assertEqual([c["where"]["text"] for c in cards],
                         ["On the whole changeset", "app.py, line 1", "gone.py, lines 5–7 (old side)"])
        self.assertEqual([c["written"] for c in cards][0], None)

    def test_the_replied_and_failed_open_threads_are_marked_as_needing_you(self):
        base = general()
        threads = [at(dict(base, id=s, state=s), i) for i, s in enumerate(("replied", "waiting", "failed"))]
        closed = at(dict(base, id="closed", status="resolved", state=None), 9)

        cards = self.body([*threads, closed])["threads"]

        self.assertEqual({c["id"]: c["needsYou"] for c in cards},
                         {"replied": True, "waiting": False, "failed": True, "closed": False})

    def test_a_review_with_no_thread_says_so(self):
        self.assertEqual(self.body([])["empty"], "No threads yet.")


def on_lines(start, end, **changes):
    """An open thread on the lines <start> to <end> of long.py, a new file of 20 lines."""
    base = outdated()
    return dict(base, id=f"on-{start}-{end}", outdated=False, anchor=dict(
        base["anchor"], file="long.py", side="new", startLine=start, endLine=end,
        code="\n".join(f"line_{n} = {n}" for n in range(start, end + 1))), **changes)


@unittest.skipUnless(shutil.which("node"), "needs node")
class AThreadsLinkToItsLines(Conversation):
    def test_its_scroll_target_is_the_file_and_the_row_of_the_first_of_its_lines(self):
        [card] = self.body([on_lines(5, 7)])["threads"]

        # long.py's rows: the hunk's header, then its lines from 1
        self.assertEqual(card["where"], {"text": "long.py, lines 5–7", "target": {"file": "long.py", "row": 5}})
        self.assertIsNone(card["written"], "the diff has its code")

    def test_of_lines_the_diff_shows_only_in_part_the_target_is_the_first_shown(self):
        diff = ('diff --git a/long.py b/long.py\n--- a/long.py\n+++ b/long.py\n'
                '@@ -6,2 +6,2 @@\n line_6 = 6\n line_7 = 7\n')
        changeset = dict(answers()["changeset"], diff=diff)

        [card] = self.body([on_lines(5, 7)], changeset=changeset)["threads"]

        self.assertEqual(card["where"]["target"], {"file": "long.py", "row": 1})

    def test_an_outdated_threads_target_is_its_files_top_never_the_lines_there_now(self):
        thread = outdated()  # written on app.py's line 1, which holds other code now

        [card] = self.body([thread])["threads"]

        self.assertEqual(card["where"]["target"], {"file": "app.py", "row": None})

    def test_a_thread_with_no_place_in_files_changed_has_no_link_and_shows_its_code(self):
        elsewhere = on_lines(5, 5, inView=False)
        gone = dict(outdated(), id="gone", anchor=dict(outdated()["anchor"], file="gone.py"))

        cards = self.body([at(elsewhere, 1), at(gone, 2), at(general(), 3)])["threads"]

        self.assertEqual([c["where"]["target"] for c in cards], [None, None, None])
        self.assertEqual(cards[0]["written"], {
            "text": "Its code isn't in this view. Written on line 5:", "code": "line_5 = 5"})
        self.assertEqual(cards[1]["written"]["text"], "Written on line 1:")

    def test_following_it_shows_files_changed_with_the_file_open_and_a_resolved_thread_unfolded(self):
        thread = on_lines(5, 5, status="resolved", state=None)

        got = run_js("page", f"""
import * as st from "{{STATE}}";
let s = st.polled(st.initialState("conversation"), {json.dumps(answers(threads=[thread], viewed=["long.py"]))});
s = st.followThread(s, "on-5-5", "long.py");
const body = m.pageModel(s).body;
const file = body.files.find((f) => f.path === "long.py");
console.log(JSON.stringify([body.kind, file.folded, file.rows.find((r) => r.kind === "below").threads[0].folded,
  body.tree.filter((r) => r.selected).map((r) => r.path)]));""")

        self.assertEqual(got, ["files", False, False, ["long.py"]])


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheGeneralThreadBox(Conversation):
    def test_the_tab_has_a_box_for_a_comment_on_the_whole_changeset(self):
        live = self.body([])["general"]
        batched = self.body([], mode={"mode": "batched", "held": []})["general"]

        self.assertEqual((live["title"], live["text"], live["send"], live["cancels"], live["hint"]),
                         ("Comment on the whole changeset", "", "Comment", False, ""))
        self.assertEqual(batched["hint"], "Held until you submit the review.")

    def sent(self, steps, show="[calls, m.boxOf(s, key)]"):
        """<show> after the JS lines <steps> on the page, with a fake review API that keeps the
        calls. onBranch: the review the folder is on; refusal: what a post is refused with."""
        poll = answers(threads=[], changeset=dict(answers()["changeset"], view="HEAD"))
        return run_js("drafts", f"""
import * as st from "{{STATE}}";
import {{ send }} from "{{ACTIONS}}";
import {{ pageModel }} from "{{PAGE}}";
const calls = [];
let refusal = null;
let s = st.polled(st.initialState("conversation"), {json.dumps(poll)});
let onBranch = s.server.review.id;
const use = {{
  api: async (method, path, payload) => {{
    if (method === "GET") return {{ id: onBranch }};
    calls.push([method, path, payload]);
    if (refusal) throw refusal;
    return {{}};
  }},
  state: () => s, update: (change) => {{ s = change(s); }}, refresh: async () => {{}},
}};
const key = pageModel(s).body.general.key;
{steps}
console.log(JSON.stringify({show}));""")

    def test_it_posts_a_general_thread_through_the_existing_call_and_is_empty_again(self):
        calls, box = self.sent('s = m.typeIn(s, key, " Is this ready? "); await send(use, key);')

        self.assertEqual(calls, [["POST", "/api/threads", {"anchor": None, "body": "Is this ready?", "view": "HEAD"}]])
        self.assertEqual(box["text"], "")

    def test_a_refused_post_keeps_its_text_and_says_why(self):
        calls, box = self.sent('s = m.typeIn(s, key, "Why?"); refusal = new Error("no"); await send(use, key);')

        self.assertEqual((len(calls), box["text"], box["sending"], bool(box["error"])), (1, "Why?", False, True))

    def test_after_a_checkout_the_other_branch_has_a_box_of_its_own_and_the_text_waits(self):
        other = answers(threads=[])
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.sent(f"""
s = m.typeIn(s, key, "For this branch");
onBranch = "other-12345678"; // the watcher followed, the page hasn't polled yet
await send(use, key);
const early = [calls.length, m.boxOf(s, key).error];
s = st.polled(s, {json.dumps(other)});""", show="[...early, pageModel(s).body.general.text, m.boxOf(s, key).text]")

        self.assertEqual(got, [0, "Another branch is checked out now: the draft waits for its own branch.",
                               "", "For this branch"])

    def test_the_page_still_says_why_once_the_other_branchs_empty_box_has_taken_its_place(self):
        other = answers(threads=[])
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.sent(f"""
s = m.typeIn(s, key, "For this branch");
onBranch = "other-12345678";
use.refresh = async () => {{ s = st.polled(s, {json.dumps(other)}); }};
await send(use, key);""", show="[calls.length, pageModel(s).body.general.text, problemOf(pageModel(s))]")

        self.assertEqual(got, [0, "", "Another branch is checked out now: the draft waits for its own branch."])


if __name__ == "__main__":
    unittest.main()
