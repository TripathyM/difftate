"""Layout D's banners under the header (#263): that the review waits for a run (waitingForRun:
another branch is checked out), and the review's warnings (web/d/banners.js, with the page's
model). Node runs it, with API answers shaped like the released transcript's."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js

# GET /api/review in the released transcript: waiting for a run, and with a warning
WAITING = released("GET", "/api/review", lambda a: a["waitingForRun"])
WARNED = released("GET", "/api/review", lambda a: a["warnings"])
WARNING = WARNED["warnings"][0]


def warned(*warnings):
    return answers(review=dict(WARNED, warnings=list(warnings)))


@unittest.skipUnless(shutil.which("node"), "needs node")
class Banners(unittest.TestCase):
    def page(self, poll, steps="", show="[page().waiting, page().warnings]", **given):
        consts = "".join(f"const {name} = {json.dumps(value)};\n" for name, value in given.items())
        return run_js("page", f"""
import * as st from "{{STATE}}";
{consts}let s = st.polled(st.initialState("files"), {json.dumps(poll)});
const page = () => m.pageModel(s);
{steps}
console.log(JSON.stringify({show}));""")

    def test_while_it_waits_for_a_run_a_banner_says_reading_goes_on_and_writing_is_refused(self):
        waiting, files = self.page(answers(review=WAITING), show="[page().waiting, page().body.files.length]")

        self.assertEqual(waiting, "other is checked out: you can go on reading, but this review takes no new thread, "
                                  "viewed mark or Done, and its threads aren't placed in that branch's code. "
                                  "The watcher moves to that branch's review once the run in progress ends.")
        self.assertEqual(files, 3, "the diff is still there")

    def test_a_checkout_it_cannot_name_is_another_branch(self):
        waiting, _ = self.page(answers(review=dict(WAITING, checkedOut=None)))

        self.assertTrue(waiting.startswith("Another branch is checked out: "), waiting)

    def test_a_commit_checked_out_by_its_full_id_is_named_short(self):
        # With the base branch checked out, or a detached HEAD, the API names the commit
        waiting, _ = self.page(answers(review=dict(WAITING, checkedOut="39714be1adef0b5c87e6ae9bff2c153f92ae796a")))

        self.assertTrue(waiting.startswith("39714be is checked out: "), waiting)

    def test_the_banner_goes_once_the_watcher_waits_no_longer(self):
        waiting, _ = self.page(answers(review=WAITING), steps="s = st.polled(s, later);", later=answers())

        self.assertEqual(waiting, "")

    def test_each_warning_is_shown_once_however_many_polls_carry_it(self):
        _, warnings = self.page(warned(WARNING, WARNING), steps="s = st.polled(s, later);",
                                later=warned(WARNING, {"id": "restored-1", "time": WARNING["time"], "text": "restored"}))

        self.assertEqual(warnings, [{"id": WARNING["id"], "text": WARNING["text"]}, {"id": "restored-1", "text": "restored"}])

    def test_a_dismissed_warning_stays_away_while_polls_still_carry_it(self):
        _, warnings = self.page(warned(WARNING), steps="""
s = st.dismissWarning(s, id);
s = st.polled(s, later);""", id=WARNING["id"],
                                later=warned(WARNING, {"id": "restored-1", "time": WARNING["time"], "text": "restored"}))

        self.assertEqual([w["id"] for w in warnings], ["restored-1"])

    def test_before_the_first_answers_there_is_no_banner(self):
        got = run_js("page", """
import * as st from "{STATE}";
const page = m.pageModel(st.initialState("files"));
console.log(JSON.stringify([page.waiting, page.warnings]));""")

        self.assertEqual(got, ["", []])


if __name__ == "__main__":
    unittest.main()
