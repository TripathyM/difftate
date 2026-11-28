"""Layout D's line comments (#259): picking lines (web/d/drafts.js), the drafts, one per anchor,
and posting each on its own lines through the existing call (web/d/actions.js). Node runs it with
a fake review API."""
import json
import shutil
import unittest

from browser_d import answers, changed, released, run_js

# The page's state and a fake review API that keeps the calls and refuses with `refusal`.
# long.py is a new file of 20 lines, "line_1 = 1" to "line_20 = 20" (line 18 is "line_18 = 180")
PAGE = """
import * as st from "{STATE}";
import * as drafts from "{DRAFTS}";
const calls = [];
let refusal = null, during = () => {};
let s = st.polled(st.initialState(), FIRST);
const use = {
  api: async (method, path, payload) => {
    calls.push([method, path, payload]);
    during();
    if (refusal) throw refusal;
    return {};
  },
  state: () => s,
  update: (change) => { s = change(s); },
  refresh: async () => { calls.push("refresh"); },
};
const spot = (line, side = "new", path = "long.py") => ({ path, side, line });
// The reviewer drags from one line number to the others, then lets go
const drag = (from, ...over) => {
  s = drafts.dragStart(s, from);
  for (const to of over) s = drafts.dragOver(s, to);
  s = drafts.dragEnd(s);
  return s.own.active;
};
const shiftClick = (to) => { s = drafts.dragStart(s, to, { extend: true }); s = drafts.dragEnd(s); return s.own.active; };
const type = (key, text) => { s = drafts.typeIn(s, key, text); };
const kept = () => drafts.draftsOf(s).map((d) => [d.anchor.path, d.anchor.side, d.anchor.start, d.anchor.end, d.text]);"""


def lines(start, end):
    return "\n".join(f"line_{n} = {n}" for n in range(start, end + 1))


@unittest.skipUnless(shutil.which("node"), "needs node")
class Drafting(unittest.TestCase):
    def run_page(self, steps, show, **given):
        """<steps> are JS lines on the page; <show> is what of it to print. <given>: polls."""
        consts = "".join(f"const {name} = {json.dumps(poll)};\n" for name, poll in given.items())
        return run_js("actions", f"""
{PAGE.replace("FIRST", json.dumps(answers()))}
{consts}{steps}
console.log(JSON.stringify({show}));""")


class TwoDrafts(Drafting):
    def test_each_draft_is_posted_on_its_own_lines_after_a_comment_was_started_elsewhere(self):
        calls, left = self.run_page("""
const first = drag(spot(5), spot(6), spot(7));
type(first, "Why these three?");
const second = drag(spot(12));
type(second, "And this one?");
await m.send(use, first);
const left = kept();
await m.send(use, second);""", show="[calls, left]")

        version = released("GET", "/api/changeset")["versions"]["long.py"]["new"]
        anchor = {"file": "long.py", "side": "new", "version": version}
        self.assertEqual(calls, [
            ["POST", "/api/threads", {"anchor": dict(anchor, startLine=5, endLine=7, code=lines(5, 7)),
                                      "body": "Why these three?", "view": ""}], "refresh",
            ["POST", "/api/threads", {"anchor": dict(anchor, startLine=12, endLine=12, code=lines(12, 12)),
                                      "body": "And this one?", "view": ""}], "refresh"])
        self.assertEqual(left, [["long.py", "new", 12, 12, "And this one?"]])


class DraftsAndPolls(Drafting):
    def test_a_draft_survives_a_poll_that_changes_the_review(self):
        later = answers(threads=[], viewed=["app.py"])

        got = self.run_page("""
type(drag(spot(5), spot(7)), "Why these three?");
s = st.polled(s, later);""", show="kept()", later=later)

        self.assertEqual(got, [["long.py", "new", 5, 7, "Why these three?"]])

    def test_after_a_checkout_a_draft_waits_for_its_own_review_to_be_shown_again(self):
        other = answers()
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.run_page("""
type(drag(spot(5)), "Mine");
s = drafts.dragStart(s, spot(9));
s = st.polled(s, other);
s = drafts.dragEnd(s);
const there = kept();
s = st.polled(s, first);""", show="[there, kept()]", other=other, first=answers())

        self.assertEqual(got, [[], [["long.py", "new", 5, 5, "Mine"]]])


class PickingLines(Drafting):
    def test_a_drag_upwards_picks_the_same_lines_and_a_line_of_another_side_or_file_is_ignored(self):
        got = self.run_page("""
type(drag(spot(7), spot(2, "old", "app.py"), spot(5), spot(1, "new", "app.py")), "up");""", show="kept()")

        self.assertEqual(got, [["long.py", "new", 5, 7, "up"]])

    def test_a_pick_stops_before_a_gap_in_the_diff(self):
        two = answers()
        two["changeset"] = dict(two["changeset"],
                                diff=changed("two.py", "@@ -1 +1 @@", "-a", "+b", "@@ -10 +10 @@", "-c", "+d"))

        got = self.run_page("""
s = st.polled(s, two);
type(drag(spot(1, "new", "two.py"), spot(10, "new", "two.py")), "dragged");
shiftClick(spot(10, "new", "two.py"));""", show="kept()", two=two)

        self.assertEqual(got, [["two.py", "new", 1, 1, "dragged"], ["two.py", "new", 10, 10, ""]])

    def test_shift_click_makes_the_comment_longer_or_shorter_from_where_its_pick_started(self):
        got = self.run_page("""
type(drag(spot(5)), "These");
shiftClick(spot(8));
const longer = kept();
shiftClick(spot(6));
const shorter = kept();
shiftClick(spot(3));""", show="[longer, shorter, kept()]")

        self.assertEqual(got, [[["long.py", "new", 5, 8, "These"]], [["long.py", "new", 5, 6, "These"]],
                               [["long.py", "new", 3, 5, "These"]]])

    def test_shift_click_onto_lines_that_have_their_own_draft_opens_it_and_loses_no_text(self):
        got = self.run_page("""
type(drag(spot(5), spot(6)), "five and six");
type(drag(spot(5)), "five");
shiftClick(spot(6));""", show="kept()")

        self.assertEqual(got, [["long.py", "new", 5, 6, "five and six"], ["long.py", "new", 5, 5, "five"]])

    def test_picking_elsewhere_drops_a_draft_with_nothing_written(self):
        got = self.run_page("""
drag(spot(2));
type(drag(spot(4)), "  ");
type(drag(spot(6)), "kept");
drag(spot(8));""", show="kept()")

        self.assertEqual(got, [["long.py", "new", 6, 6, "kept"], ["long.py", "new", 8, 8, ""]])

    def test_picking_a_drafts_lines_again_opens_it_on_the_code_they_hold_now(self):
        later = answers()
        later["changeset"] = dict(later["changeset"], diff=later["changeset"]["diff"].replace("+line_5 = 5", "+five = 5"),
                                  versions=dict(later["changeset"]["versions"], **{"long.py": {"old": None, "new": "<hash-new>"}}))

        got = self.run_page("""
const key = drag(spot(5));
type(key, "Why?");
s = st.polled(s, later);
const before = drafts.draftsOf(s)[0].anchor;
const again = drag(spot(5));
const after = drafts.draftsOf(s)[0];""", show="[again === key, before.code, after.anchor.code, after.anchor.version, after.text]",
                            later=later)

        self.assertEqual(got, [True, "line_5 = 5", "five = 5", "<hash-new>", "Why?"])


class Sending(Drafting):
    def test_a_refused_draft_keeps_its_text_and_says_why_until_the_reviewer_types(self):
        got = self.run_page("""
import { ApiError } from "{API}";
refusal = new ApiError(409, "another branch is checked out");
const key = drag(spot(5));
type(key, "Why?");
const took = await m.send(use, key);
const refused = [took, kept()[0][4], drafts.boxOf(s, key).error, drafts.boxOf(s, key).sending, calls.length];
type(key, "Why??");""", show="[...refused, drafts.boxOf(s, key).error]")

        self.assertEqual(got, [False, "Why?", "another branch is checked out", False, 1, ""])

    def test_a_blank_draft_is_not_sent_and_one_being_sent_is_not_sent_again(self):
        got = self.run_page("""
const key = drag(spot(5));
type(key, "  \\n ");
await m.send(use, key);
const blank = calls.length;
type(key, "Once");
let second;
during = () => { during = () => {}; second = m.send(use, key); };
await m.send(use, key);""", show="[blank, await second, calls.filter((c) => c !== 'refresh').length, kept()]")

        self.assertEqual(got, [0, False, 1, []])


class ThreadActions(Drafting):
    def test_a_reply_is_posted_to_its_thread_as_a_comment_and_its_box_empties(self):
        calls, left = self.run_page("""
const key = drafts.replyKey("t1");
type(key, " And the name? ");
type(drafts.replyKey("t2"), "not sent");
await m.send(use, key);""", show="[calls, [drafts.boxOf(s, key).text, drafts.boxOf(s, drafts.replyKey('t2')).text]]")

        self.assertEqual(calls, [["POST", "/api/threads/t1/comments", {"body": "And the name?"}], "refresh"])
        self.assertEqual(left, ["", "not sent"])

    def test_resolve_dismiss_and_reopen_change_the_threads_status_through_its_call(self):
        calls = self.run_page("""
await m.setStatus(use, "t1", "resolved");
await m.setStatus(use, "t1", "open");
await m.setStatus(use, "a/b", "dismissed");""", show="calls")

        self.assertEqual(calls, [
            ["PATCH", "/api/threads/t1/status", {"status": "resolved"}], "refresh",
            ["PATCH", "/api/threads/t1/status", {"status": "open"}], "refresh",
            ["PATCH", "/api/threads/a%2Fb/status", {"status": "dismissed"}], "refresh"])

    def test_a_refused_status_change_says_why_on_its_thread_until_one_is_taken(self):
        got = self.run_page("""
import { ApiError } from "{API}";
refusal = new ApiError(409, "another branch is checked out");
const took = await m.setStatus(use, "t1", "resolved");
const refused = [took, s.own.errors.t1, calls.length];
refusal = null;
await m.setStatus(use, "t1", "resolved");""", show="[...refused, s.own.errors.t1 ?? '']")

        self.assertEqual(got, [False, "another branch is checked out", 1, ""])


if __name__ == "__main__":
    unittest.main()
