"""What layout D shows (#257): the model of the header, the tabs and the Files changed tab, from
the page state (web/d/page.js). The page only draws it, so a blank tab shows up here. Node runs
it."""
import json
import shutil
import unittest

from browser_d import answers, changed, released, run_js


def thread(state):
    """An open general thread of the released transcript, standing as <state> says."""
    return dict(released("GET", "/api/threads")[0], id=state, anchor=None, outdated=False, status="open", state=state)


@unittest.skipUnless(shutil.which("node"), "needs node")
class ThePage(unittest.TestCase):
    def page(self, poll=None, steps="", address=None, **given):
        """The model of the page, opened at an address naming the tab <address>, after a poll
        answering <poll> (None: none yet), then <steps>."""
        consts = "".join(f"const {name} = {json.dumps(value)};\n" for name, value in given.items())
        return run_js("page", f"""
import * as st from "{{STATE}}";
{consts}let s = st.initialState({json.dumps(address)});
const poll = {json.dumps(poll)};
if (poll) s = st.polled(s, poll);
{steps}
console.log(JSON.stringify(m.pageModel(s)));""")

    def test_a_review_opens_on_files_changed_with_its_tree_and_every_files_rows(self):
        page = self.page(answers(threads=[]))

        self.assertEqual(self.tabs(page), [("Conversation", 0, False, ""), ("Files changed", 3, True, "")])
        body = page["body"]
        self.assertEqual(body["kind"], "files")
        self.assertEqual([r["path"] for r in body["tree"]], ["app.py", "long.py", "README.md"])
        self.assertEqual([f["path"] for f in body["files"]], ["app.py", "long.py", "README.md"])
        self.assertEqual([len(f["rows"]) for f in body["files"]], [4, 21, 3])
        self.assertEqual(body["empty"], "")

    def test_before_the_first_answers_the_page_says_it_is_loading_and_after_a_failed_poll_why(self):
        loading = self.page()
        failed = self.page(steps='s = st.pollFailed(s, "Can\'t reach the watcher");')

        self.assertEqual(loading["body"], {"kind": "loading", "text": "Loading the review…"})
        self.assertEqual(failed["body"], {"kind": "loading", "text": "Loading the review…"})
        self.assertEqual(failed["problem"], "Can't reach the watcher")
        self.assertIsNone(loading["header"])

    def test_the_header_names_the_branch_and_base_and_says_in_review(self):
        page = self.page(answers())

        self.assertEqual(page["header"], {"branch": "feature", "base": "main", "state": "In review", "done": False})
        self.assertEqual(page["title"], "difftate · feature")

    def test_a_review_marked_done_says_done(self):
        page = self.page(answers(done=released("GET", "/api/done", lambda a: a["done"])))

        self.assertEqual((page["header"]["state"], page["header"]["done"]), ("Done", True))

    def test_a_changeset_with_no_files_says_so_in_the_views_words(self):
        said = {view: self.page(answers(changeset=dict(answers()["changeset"], diff="", view=view)))["body"]["empty"]
                for view in ("", "HEAD", "staged", "HEAD~2")}

        self.assertEqual(said, {"": "No changes in all changes.", "HEAD": "No changes in uncommitted changes.",
                                "staged": "No changes in staged changes.",
                                "HEAD~2": "No changes in the commits after HEAD~2."})

    def test_a_tab_the_page_does_not_have_shows_files_changed_not_a_blank(self):
        page = self.page(answers(), steps='s = st.showTab(s, "commits");')

        self.assertEqual((page["body"]["kind"], page["tabs"][1]["current"]), ("files", True))

    def tabs(self, page):
        return [(t["text"], t["count"], t["current"], t["needs"]) for t in page["tabs"]]

    def test_a_review_with_a_reply_opens_on_conversation_with_a_note_saying_why(self):
        page = self.page(answers(threads=[thread("replied")]))

        self.assertEqual((page["body"]["kind"], page["note"]),
                         ("conversation", "Opened on Conversation: 1 thread needs you (replied or failed)."))
        self.assertEqual(self.tabs(page), [("Conversation", 1, True, "1 needs you"), ("Files changed", 3, False, "")])

    def test_a_reply_arriving_by_poll_keeps_the_tab_and_shows_that_it_needs_you(self):
        page = self.page(answers(threads=[thread("working")]), steps="s = st.polled(s, later);",
                         later=answers(threads=[thread("replied"), dict(thread("failed"), id="other")]))

        self.assertEqual((page["body"]["kind"], page["note"]),
                         ("files", "Opened on Files changed: no open thread is replied or failed."))
        self.assertEqual(self.tabs(page)[0], ("Conversation", 2, False, "2 need you"))

    def test_the_tab_the_address_names_is_the_one_shown_with_no_note(self):
        page = self.page(answers(threads=[thread("replied")]), address="files")

        self.assertEqual((page["body"]["kind"], page["tab"], page["note"]), ("files", "files", ""))

    def test_the_note_goes_once_the_reviewer_changes_tab(self):
        page = self.page(answers(threads=[]), steps='s = st.showTab(s, "conversation");')

        self.assertEqual((page["body"]["kind"], page["note"]), ("conversation", ""))

    def test_before_the_first_answers_the_page_has_no_tab_to_put_in_its_address(self):
        self.assertIsNone(self.page()["tab"])

    def test_each_file_header_has_its_viewed_mark_fold_and_line_counts_and_the_progress_counts_them(self):
        # gone.py was viewed and has no changes in this view: it counts in neither number
        page = self.page(answers(viewed=["long.py", "gone.py"]), steps='s = st.foldFile(s, "app.py", true);')

        body = page["body"]
        self.assertEqual(body["progress"], {"viewed": 1, "total": 3, "text": "1 of 3 files viewed"})
        self.assertEqual([(f["path"], f["viewed"], f["folded"], f["additions"], f["deletions"]) for f in body["files"]],
                         [("app.py", False, True, 1, 1), ("long.py", True, True, 20, 0),
                          ("README.md", False, False, 1, 0)])

    def test_a_renamed_file_says_what_it_was_called_and_an_added_one_that_it_is_new(self):
        diff = ("diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n")
        renamed = self.page(answers(changeset=dict(answers()["changeset"], diff=diff)))["body"]["files"][0]
        added = self.page(answers())["body"]["files"][1]

        self.assertEqual((renamed["note"], added["note"]), ("renamed from old.py", "added"))

    def test_the_filter_narrows_the_tree_only_the_diffs_stay(self):
        page = self.page(answers(), steps='s = st.filterFiles(s, "long");')

        self.assertEqual([r["path"] for r in page["body"]["tree"]], ["long.py"])
        self.assertEqual(len(page["body"]["files"]), 3)
        self.assertEqual(page["body"]["filtered"], "")

    def test_the_tree_says_when_the_filter_leaves_no_file(self):
        page = self.page(answers(), steps='s = st.filterFiles(s, "zzz");')

        self.assertEqual(page["body"]["filtered"], "No file's path has “zzz”.")

    def test_the_tree_marks_the_selected_file(self):
        page = self.page(answers(), steps='s = st.selectFile(s, "long.py");')

        self.assertEqual([r["path"] for r in page["body"]["tree"] if r["selected"]], ["long.py"])

    def test_a_file_that_became_a_link_is_one_file_with_both_diffs_git_gives_for_it(self):
        diff = ("diff --git a/conf b/conf\ndeleted file mode 100644\nindex 1111111..0000000\n--- a/conf\n+++ /dev/null\n"
                "@@ -1 +0,0 @@\n-a = 1\n"
                "diff --git a/conf b/conf\nnew file mode 120000\nindex 0000000..2222222\n--- /dev/null\n+++ b/conf\n"
                "@@ -0,0 +1 @@\n+other.conf\n")

        body = self.page(answers(changeset=dict(answers()["changeset"], diff=diff)))["body"]

        [file] = body["files"]
        self.assertEqual((file["note"], file["additions"], file["deletions"]), ("type changed", 1, 1))
        self.assertEqual([r["text"] for r in file["rows"] if r["kind"] == "line"], ["a = 1", "other.conf"])
        self.assertEqual([r["path"] for r in body["tree"]], ["conf"])
        self.assertEqual(body["progress"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
