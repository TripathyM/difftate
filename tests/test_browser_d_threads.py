"""What layout D shows of a thread (#259): its state as a label, who wrote what, progress notes as
one-line events, resolved threads folded, and an outdated thread's own code (web/d/threads.js).
Node runs it, with threads shaped like the released transcript's."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js


def threads():
    """The released transcript's threads once one has two comments, a progress note, a reply and
    a comment after it (the first), and others are outdated."""
    return released("GET", "/api/threads?status=open", lambda a: a and len(a[0]["comments"]) == 5 and a[0]["state"] == "waiting")


def a_thread(**changes):
    """The released transcript's first thread (two comments, a progress note, a reply, a comment)."""
    return dict(threads()[0], **changes)


@unittest.skipUnless(shutil.which("node"), "needs node")
class AThread(unittest.TestCase):
    def card(self, thread, placed=True, steps="", show="m.threadCard(thread, s, { placed })"):
        return run_js("threads", f"""
import * as st from "{{STATE}}";
import * as drafts from "{{DRAFTS}}";
const thread = {json.dumps(thread)}, placed = {json.dumps(placed)};
let s = st.polled(st.initialState(), {json.dumps(answers())});
{steps}
console.log(JSON.stringify({show}));""")

    def labels(self, **changes):
        return [label["text"] for label in self.card(a_thread(**changes))["labels"]]

    def test_an_open_threads_state_is_its_label_and_held_reads_pending(self):
        self.assertEqual([self.labels(state=state) for state in
                          ("held", "waiting", "queued", "working", "replied", "failed", "paused")],
                         [["Pending"], ["Waiting"], ["Queued"], ["Working"], ["Replied"], ["Failed"], ["paused"]])

    def test_a_closed_threads_label_is_its_status_with_who_closed_it(self):
        self.assertEqual(self.labels(status="resolved", state=None, statusBy="security-bot"), ["Resolved by security-bot"])
        self.assertEqual(self.labels(status="dismissed", state=None, statusBy=None), ["Dismissed"])

    def test_the_coding_agents_comments_are_marked_and_a_progress_note_is_a_one_line_event(self):
        card = self.card(a_thread())

        self.assertEqual([(c["kind"], c.get("who"), c.get("agent")) for c in card["comments"]], [
            ("comment", "Test", False), ("comment", "Test", False), ("note", None, None),
            ("comment", "Coding agent", True), ("comment", "Test", False)])
        self.assertEqual(card["comments"][2]["line"], [{"text": "⏳ Read app.py"}])
        self.assertEqual(card["comments"][2]["more"], [])
        self.assertEqual(card["comments"][3]["body"], [{"kind": "paragraph", "spans": [{"text": "It reads better."}]}])

    def test_a_note_of_many_lines_shows_its_first_and_unfolds_the_rest(self):
        note = {"id": "n1", "author": "difftate", "by": None, "kind": "progress",
                "body": "❌ **Failed** after 3s\n- ✅ `Read app.py`\n\nThe agent stopped.", "time": "<time>"}

        folded, unfolded = self.card(a_thread(comments=[note]), show="""[m.threadCard(thread, s, { placed }).comments[0],
  m.threadCard(thread, st.setOpen(s, "n1", true), { placed }).comments[0]]""")

        self.assertEqual(folded["line"], [{"text": "❌ "}, {"strong": "Failed"}, {"text": " after 3s"}])
        self.assertEqual([b["kind"] for b in folded["more"]], ["list", "paragraph"])
        self.assertEqual((folded["open"], unfolded["open"]), (False, True))

    def test_an_open_thread_takes_a_reply_and_can_be_resolved_or_dismissed(self):
        card = self.card(a_thread(), steps="""s = drafts.typeIn(s, drafts.replyKey(thread.id), "And **why**?");
s = drafts.showBoxTab(s, drafts.replyKey(thread.id), "preview");""")

        self.assertEqual((card["folds"], card["folded"]), (False, False))
        self.assertEqual([(a["text"], a["status"]) for a in card["actions"]], [("Resolve", "resolved"), ("Dismiss", "dismissed")])
        reply = card["reply"]
        self.assertEqual((reply["text"], reply["tab"], reply["send"]), ("And **why**?", "preview", "Reply"))
        self.assertEqual(reply["preview"][0]["spans"][1], {"strong": "why"})

    def test_a_resolved_thread_is_folded_to_its_first_words_until_it_is_unfolded_and_can_be_reopened(self):
        thread = a_thread(status="resolved", state=None)

        folded, unfolded = self.card(thread, show="""[m.threadCard(thread, s, { placed }),
  m.threadCard(thread, st.setOpen(s, thread.id, true), { placed })]""")

        self.assertEqual((folded["folds"], folded["folded"], folded["gist"], unfolded["folded"]),
                         (True, True, "Why an f-string?", False))
        self.assertEqual((unfolded["reply"], [a["text"] for a in unfolded["actions"]]), (None, ["Reopen"]))

    def test_a_thread_resolved_through_the_page_folds_even_one_that_was_unfolded_before(self):
        folded = self.card(a_thread(status="resolved", state=None), steps="""s = st.setOpen(s, thread.id, true);
s = st.threadTaken(s, thread.id);""", show="m.threadCard(thread, s, { placed }).folded")

        self.assertTrue(folded)

    def test_an_outdated_thread_is_labelled_so_and_shows_the_code_it_was_written_on(self):
        outdated = next(t for t in threads() if t["outdated"])

        card = self.card(outdated, placed=False)

        self.assertEqual([label["text"] for label in card["labels"]], ["Waiting", "Outdated"])
        self.assertEqual(card["written"], {"text": "Written on line 1:", "code": "def greet(nam):"})

    def test_a_thread_away_from_its_line_says_why_and_shows_its_code_and_one_under_it_shows_neither(self):
        anchor = dict(a_thread()["anchor"], side="old", startLine=2, endLine=3, code="a\nb")

        away = self.card(a_thread(anchor=anchor, inView=False), placed=False)

        self.assertEqual([label["text"] for label in away["labels"]], ["Waiting", "Not in this view"])
        self.assertEqual(away["written"], {"text": "Its code isn't in this view. Written on lines 2–3 (old side):",
                                           "code": "a\nb"})
        self.assertEqual(self.card(a_thread(anchor=anchor), placed=False)["written"]["text"],
                         "Not among the lines shown. Written on lines 2–3 (old side):")
        self.assertIsNone(self.card(a_thread())["written"])

    def test_an_outdated_thread_on_a_blank_line_still_says_where_it_was_written(self):
        anchor = dict(a_thread()["anchor"], startLine=3, endLine=3, code="")

        card = self.card(a_thread(anchor=anchor, outdated=True), placed=False)

        self.assertEqual(card["written"], {"text": "Written on line 3:", "code": ""})


if __name__ == "__main__":
    unittest.main()
