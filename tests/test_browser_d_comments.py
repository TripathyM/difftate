"""Layout D's Files changed tab with its comments (#259): the thread cards and comment boxes on
their rows, at their file's top, or above the files, as the page draws them (web/d/page.js over
files_changed.js). Node runs it, with the released transcript's threads."""
import json
import shutil
import unittest

from browser_d import answers, changed, released, run_js


def transcript_threads():
    return released("GET", "/api/threads?status=open",
                    lambda a: a and len(a[0]["comments"]) == 5 and a[0]["state"] == "waiting")


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheCommentsInTheDiff(unittest.TestCase):
    def body(self, steps="", poll=None, **given):
        """The Files changed tab after a poll, then the JS lines <steps>."""
        consts = "".join(f"const {name} = {json.dumps(value)};\n" for name, value in given.items())
        return run_js("page", f"""
import * as st from "{{STATE}}";
import * as drafts from "{{DRAFTS}}";
{consts}let s = st.polled(st.initialState(), {json.dumps(poll or answers(threads=[]))});
const spot = (line, path = "long.py") => ({{ path, side: "new", line }});
const pick = (from, to = from) => {{ s = drafts.dragEnd(drafts.dragOver(drafts.dragStart(s, from), to)); return s.own.active; }};
{steps}
console.log(JSON.stringify(m.pageModel(s).body));""")

    def file(self, body, path):
        return next(f for f in body["files"] if f["path"] == path)

    def below(self, file):
        """(the line's new number, the thread ids, the draft titles) for each row under a line."""
        return [(r["new"], [t["id"] for t in r["threads"]], [d["title"] for d in r["drafts"]])
                for r in file["rows"] if r["kind"] == "below"]

    def test_threads_show_as_cards_under_their_lines_and_outdated_ones_at_the_files_top_with_their_code(self):
        threads = transcript_threads()

        app = self.file(self.body(poll=answers(threads=threads)), "app.py")

        outdated = {t["id"] for t in threads if t["outdated"] and t["anchor"]["file"] == "app.py"}
        self.assertTrue(outdated)
        under = [i for _, ids, _ in self.below(app) for i in ids]
        self.assertEqual((outdated & set(under), outdated - {t["id"] for t in app["top"]["threads"]}), (set(), set()))
        for card in (t for t in app["top"]["threads"] if t["id"] in outdated):
            self.assertTrue(card["written"]["code"])
            self.assertIn("Outdated", [label["text"] for label in card["labels"]])
        everyone = under + [t["id"] for t in app["top"]["threads"]]
        self.assertEqual(sorted(everyone), sorted(t["id"] for t in threads if t["anchor"] and t["anchor"]["file"] == "app.py"))
        self.assertTrue(under)
        card = next(r for r in app["rows"] if r["kind"] == "below")["threads"][0]
        self.assertEqual((card["written"], card["comments"][0]["who"]), (None, "Test"))

    def test_a_draft_is_a_comment_box_under_its_last_line_named_by_its_lines(self):
        body = self.body("pick(spot(5), spot(7));")

        long = self.file(body, "long.py")
        self.assertEqual(self.below(long), [(7, [], ["Comment on lines 5–7"])])
        box = next(r for r in long["rows"] if r["kind"] == "below")["drafts"][0]
        self.assertEqual((box["send"], box["tab"], box["text"], box["was"], box["hint"]), ("Comment", "write", "", None, ""))
        self.assertEqual(body["loose"], {"threads": [], "drafts": []})

    def test_in_a_batched_review_the_box_says_the_comment_is_held(self):
        poll = answers(threads=[], mode={"mode": "batched", "held": []})

        long = self.file(self.body("pick(spot(5));", poll=poll), "long.py")

        box = next(r for r in long["rows"] if r["kind"] == "below")["drafts"][0]
        self.assertEqual((box["send"], box["hint"]), ("Comment", "Held until you submit the review."))

    def picked(self, body):
        return [(r["old"], r["new"], r["picked"]) for f in body["files"] for r in f["rows"] if r.get("picked")]

    def test_the_lines_being_dragged_over_are_marked_on_their_side_and_so_are_a_drafts(self):
        dragging = self.body("s = drafts.dragOver(drafts.dragStart(s, spot(5)), spot(6));")
        old_side = self.body('pick({ path: "app.py", side: "old", line: 1 });')

        self.assertEqual(self.picked(dragging), [(None, 5, ["new"]), (None, 6, ["new"])])
        self.assertEqual(self.picked(old_side), [(1, 1, ["old"])])

    def test_a_draft_whose_lines_changed_goes_to_the_files_top_with_the_code_it_still_posts_to(self):
        later = answers(threads=[])
        later["changeset"] = dict(later["changeset"], diff=later["changeset"]["diff"].replace("+line_5 = 5", "+five = 5"))

        body = self.body('const key = pick(spot(5)); s = drafts.typeIn(s, key, "Why?"); s = st.polled(s, later);', later=later)

        long = self.file(body, "long.py")
        [box] = long["top"]["drafts"]
        self.assertEqual((box["text"], box["was"]), ("Why?", {
            "text": "The diff doesn't show these lines as you picked them. The comment goes with this code:",
            "code": "line_5 = 5"}))
        self.assertEqual((self.below(long), self.picked(body)), ([], []))

    def test_a_draft_whose_file_left_the_diff_stays_above_the_files(self):
        later = answers(threads=[])
        later["changeset"] = dict(later["changeset"], diff=changed("app.py"))

        body = self.body('const key = pick(spot(5)); s = drafts.typeIn(s, key, "Why?"); s = st.polled(s, later);', later=later)

        self.assertEqual([(d["title"], d["text"], d["was"]["code"]) for d in body["loose"]["drafts"]],
                         [("Comment on long.py, line 5", "Why?", "line_5 = 5")])

    def test_a_thread_whose_file_is_not_in_the_diff_stays_above_the_files_named_by_its_file(self):
        first = transcript_threads()[0]
        gone = dict(first, id="gone", outdated=True, anchor=dict(first["anchor"], file="gone.py", code="old = 1"))
        general = dict(first, id="general", anchor=None)

        body = self.body(poll=answers(threads=[gone, general]))

        # the file is in the card's head, which a folded card keeps
        self.assertEqual([(t["id"], t["file"], t["written"]) for t in body["loose"]["threads"]],
                         [("gone", "gone.py", {"text": "Written on line 2:", "code": "old = 1"})])


if __name__ == "__main__":
    unittest.main()
