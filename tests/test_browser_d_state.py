"""Layout D's page state (#257): what the server answered, kept apart from what is the reviewer's
own (tab, folds, selection, filter), so that a poll never throws that away (web/d/state.js).
Node runs it."""
import json
import shutil
import unittest

from browser_d import answers, changed, run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class ThePageState(unittest.TestCase):
    def after(self, steps, show="s"):
        """<steps> are JS lines that move the state s; <show> is what of it to print."""
        given = {"first": answers(), "later": answers(
            changeset=dict(answers()["changeset"], diff=changed("app.py") + changed("new.py")), threads=[])}
        return run_js("state", f"""
const {{ first, later }} = {json.dumps(given)};
let s = m.initialState();
{steps}
console.log(JSON.stringify({show}));""")

    def test_a_poll_keeps_the_reviewers_tab_folds_selection_and_filter(self):
        got = self.after("""
s = m.polled(s, first);
s = m.showTab(s, "conversation");
s = m.selectFile(s, "long.py");
s = m.foldFile(s, "app.py", true);
s = m.filterFiles(s, "py");
s = m.polled(s, later);""", show="[s.own.tab, s.own.selected, s.own.filter, m.isFolded(s, 'app.py'), s.server.threads]")

        self.assertEqual(got, ["conversation", "long.py", "py", True, []])

    def test_a_viewed_file_is_folded_until_the_reviewer_opens_it(self):
        got = self.after("""
s = m.polled(s, { ...first, viewed: ["app.py"] });
const before = [m.isFolded(s, "app.py"), m.isFolded(s, "long.py")];
s = m.foldFile(s, "app.py", false);
s = m.polled(s, { ...later, viewed: ["app.py"] });""", show="[...before, m.isFolded(s, 'app.py')]")

        self.assertEqual(got, [True, False, False])

    def test_marking_a_file_viewed_folds_it_at_once_even_one_the_reviewer_had_opened(self):
        got = self.after("""
s = m.polled(s, first);
s = m.selectFile(s, "app.py");
s = m.viewedAnswered(s, ["app.py"]);""", show="[s.server.viewed, m.isFolded(s, 'app.py')]")

        self.assertEqual(got, [["app.py"], True])

    def test_a_file_whose_viewed_mark_the_watcher_cleared_opens_again(self):
        # the watcher clears a mark when the file's diff changes
        got = self.after("""
s = m.polled(s, first);
s = m.viewedAnswered(s, ["app.py"]);
s = m.polled(s, later);""", show="m.isFolded(s, 'app.py')")

        self.assertFalse(got)

    def test_taking_the_viewed_mark_off_opens_the_file(self):
        got = self.after("""
s = m.polled(s, { ...first, viewed: ["app.py"] });
s = m.foldFile(s, "app.py", true);
s = m.viewedAnswered(s, []);""", show="m.isFolded(s, 'app.py')")

        self.assertFalse(got)

    def test_a_poll_that_answers_the_same_gives_the_same_state_so_nothing_is_redrawn(self):
        got = self.after("""
s = m.polled(s, first);
const before = s;
s = m.polled(s, structuredClone(first));
const same = s === before;
s = m.polled(s, later);""", show="[same, s === before]")

        self.assertEqual(got, [True, False])

    def test_a_failed_poll_keeps_the_last_answers_and_says_why_until_one_works(self):
        got = self.after("""
s = m.polled(s, first);
s = m.pollFailed(s, "Can't reach the watcher");
const failed = [s.problem, s.server.review.branch];
s = m.polled(s, structuredClone(first));""", show="[...failed, s.problem]")

        self.assertEqual(got, ["Can't reach the watcher", "feature", ""])

    def test_after_a_checkout_the_other_reviews_folds_and_selection_are_gone_but_not_the_tab(self):
        got = self.after("""
s = m.polled(s, first);
s = m.showTab(s, "conversation");
s = m.selectFile(s, "long.py");
s = m.foldFile(s, "app.py", true);
s = m.polled(s, { ...first, review: { ...first.review, id: "other-12345678", branch: "other" } });""",
                         show="[s.own.tab, s.own.selected, s.own.folds]")

        self.assertEqual(got, ["conversation", None, {}])

    def test_a_file_named_like_a_part_of_every_javascript_object_starts_open(self):
        got = self.after("s = m.polled(s, first);", show="['constructor', 'toString', '__proto__'].map((p) => m.isFolded(s, p))")

        self.assertEqual(got, [False, False, False])


if __name__ == "__main__":
    unittest.main()
