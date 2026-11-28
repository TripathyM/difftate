"""The review path in layout D (#260, #276): the file tree in Reading order or by folder, each
file's header line and the description it opens, and Viewed, next (the models of web/d/, with the review path model of
web/review_path.js). Node runs them, with answers shaped like the released transcript."""
import json
import shutil
import unittest

from browser_d import answers, changed, released, run_js

# The released transcript's path: one key stop, app.py, with a side file and a stop under it
PATH = released("GET", "/api/review-path", lambda a: a["path"] and a["path"]["stops"])["path"]
# The files it names, as git lists them in a diff
NAMED = ["README.md", "app.py", "lib.py", "long.py", "notes.md", "review-path.md"]


def with_path(path=PATH, files=NAMED):
    """A poll's answers for a changeset of <files> with the review path <path>."""
    return answers(changeset=dict(released("GET", "/api/changeset"), diff="".join(changed(f) for f in files)),
                   reviewPath=path, threads=[])


# A page on Files changed with a poll's <answers>; body() is the tab's model
PAGE = """
import * as st from "{STATE}";
let s = st.polled(st.initialState("files"), ANSWERS);
const body = () => m.pageModel(s).body;"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class Pages(unittest.TestCase):
    def page(self, show, given=None, steps=""):
        setup = PAGE.replace("ANSWERS", json.dumps(given or with_path()))
        return run_js("page", f"{setup}\n{steps}\nconsole.log(JSON.stringify({show}));")


# One tree row in a line: its depth as indent, its stop number, its name, ★ for a key stop
SHAPE = """body().tree.map((r) => "  ".repeat(r.depth) + [r.number, r.name + (r.kind === "file" ? "" : "/"), r.key ? "★" : ""].filter(Boolean).join(" "))"""
ORDER = "body().files.map((f) => f.path)"


class ReadingOrder(Pages):
    def test_with_a_review_path_the_tree_and_the_diffs_are_in_reading_order(self):
        # notes.md sorts after long.py and review-path.md by folder too; app.py is the one that moves
        tree, files = self.page(f"[{SHAPE}.slice(0, 3), {ORDER}.slice(0, 3)]")

        self.assertEqual(tree, ["1 app.py ★", "  README.md", "  1.1 lib.py"])
        self.assertEqual(files, ["app.py", "README.md", "lib.py"])

    def test_skipped_files_and_files_not_on_the_path_are_shown_apart_after_the_stops(self):
        tree, files = self.page(f"[{SHAPE}.slice(3), {ORDER}.slice(3)]")

        self.assertEqual(tree, ["Skipped/", "long.py", "Not on the path/", "notes.md", "review-path.md"])
        self.assertEqual(files, ["long.py", "notes.md", "review-path.md"])

    def test_a_skipped_file_says_why(self):
        self.assertEqual(self.page("body().tree.find((r) => r.path === 'long.py').reason"), "numbers only")

    def test_a_changed_file_the_path_answer_does_not_name_is_listed_as_not_on_the_path(self):
        # A path read before the file changed names it nowhere: it mustn't leave the tree
        for path in (dict(PATH, not_on_the_path=[]), PATH):
            tree = self.page(SHAPE + ".slice(5)", with_path(path, NAMED + ["zz.py"]))

            self.assertEqual(tree[0], "Not on the path/")
            self.assertEqual(tree.count("Not on the path/"), 1)
            self.assertEqual(tree[-1], "zz.py")

    def test_the_filter_keeps_the_matching_rows_in_their_order_and_no_empty_heading(self):
        got = self.page(f"[{SHAPE}, {ORDER}.length, body().filtered]", steps='s = st.filterFiles(s, "LIB");')

        # The diffs are all there still
        self.assertEqual(got, [["  1.1 lib.py"], len(NAMED), ""])


# The files as D lists them by folder: by name, whatever its case
BY_FOLDER = ["app.py", "lib.py", "long.py", "notes.md", "README.md", "review-path.md"]
# The sort control, one choice in a line: its text, > for the one shown, - for one that can't be
SORTS = """body().sorts.map((o) => (o.current ? "> " : o.disabled ? "- " : "") + o.text)"""


class TheSort(Pages):
    def test_the_reviewer_can_sort_by_folder_and_back(self):
        got = self.page("[first, folders, again()]", steps=f"""
const first = {SORTS};
s = st.sortTree(s, "folder");
const folders = [{SORTS}, {SHAPE}, {ORDER}];
const again = () => {{ s = st.sortTree(s, "order"); return {ORDER}.slice(0, 3); }};""")

        self.assertEqual(got, [["> Reading order", "Folders"], [["Reading order", "> Folders"], BY_FOLDER, BY_FOLDER],
                               ["app.py", "README.md", "lib.py"]])

    def test_without_a_review_path_the_tree_follows_the_changeset_by_folder(self):
        got = self.page(f"[{SORTS}, {SHAPE}, {ORDER}]", with_path(None))

        self.assertEqual(got, [["- Reading order", "> Folders"], BY_FOLDER, BY_FOLDER])

    def test_pressing_folders_without_a_review_path_chooses_nothing(self):
        got = self.page(f"[unchanged, {ORDER}.slice(0, 3)]", with_path(None), f"""
const unchanged = st.sortTree(s, "folder") === s;
s = st.polled(st.sortTree(s, "folder"), {json.dumps(with_path())});""")

        # A review path written later is followed
        self.assertEqual(got, [True, ["app.py", "README.md", "lib.py"]])

    def test_a_poll_and_another_branch_keep_the_sort_the_reviewer_chose(self):
        other = with_path()
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.page(SORTS, steps=f"""s = st.polled(st.sortTree(s, "folder"), {json.dumps(other)});""")

        self.assertEqual(got, ["Reading order", "> Folders"])


def stale(*gone):
    """The released path as GET /api/review-path gives it once the files <gone> have no changes."""
    path = json.loads(json.dumps(PATH))
    top = path["stops"][0]
    for entry in [top, *top["side_files"], *top["children"], *path["skipped"]]:
        entry["in_changeset"] = entry["file"] not in gone
    return with_path(path, [f for f in NAMED if f not in gone])


class AnOutOfDatePath(Pages):
    def test_a_path_that_names_files_with_no_changes_is_shown_as_out_of_date(self):
        got = self.page("body().outOfDate", stale("README.md", "lib.py", "long.py"))

        self.assertEqual(got, "The review path is out of date: 3 files it names have no changes.")

    def test_one_such_file(self):
        self.assertEqual(self.page("body().outOfDate", stale("lib.py")),
                         "The review path is out of date: 1 file it names has no changes.")

    def test_a_file_the_path_lists_twice_counts_once(self):
        given = stale("lib.py")
        gone = {"file": "lib.py", "reason": "listed twice", "in_changeset": False}
        given["reviewPath"]["skipped"].append(gone)

        self.assertEqual(self.page("body().outOfDate", given),
                         "The review path is out of date: 1 file it names has no changes.")

    def test_it_says_so_by_folder_too(self):
        got = self.page("body().outOfDate", stale("lib.py"), steps='s = st.sortTree(s, "folder");')

        self.assertEqual(got, "The review path is out of date: 1 file it names has no changes.")

    def test_the_files_with_no_changes_are_marked_and_the_others_are_not(self):
        # A stop, a side file and a skipped file can each be out of date
        got = self.page("body().tree.filter((r) => r.kind === 'file').map((r) => [r.path, r.noDiff])",
                        stale("README.md", "lib.py", "long.py"))

        self.assertEqual(got, [["app.py", ""], ["README.md", "no changes"], ["lib.py", "no changes"],
                               ["long.py", "no changes"], ["notes.md", ""], ["review-path.md", ""]])

    def test_a_file_the_diff_does_not_show_yet_is_marked_as_not_in_this_view(self):
        # The path and the changeset are two calls: the diff can be the older one
        got = self.page("body().tree.filter((r) => r.noDiff).map((r) => [r.path, r.noDiff])",
                        with_path(PATH, [f for f in NAMED if f != "lib.py"]))

        self.assertEqual(got, [["lib.py", "not in this view"]])

    def test_a_path_that_is_up_to_date_or_none_says_nothing(self):
        for path in (PATH, None):
            self.assertEqual(self.page("body().outOfDate", with_path(path)), "")


# A file header's review path line, as the page's model has it
LINES = "Object.fromEntries(body().files.map((f) => [f.path, f.pathLine]))"


def with_stop(**changes):
    """The released path, its first stop (app.py) with <changes>."""
    path = json.loads(json.dumps(PATH))
    path["stops"][0].update(changes)
    return with_path(path)


def questions(*asked):
    return [{"question": q, "answer": "Because."} for q in asked]


class TheHeaderLine(Pages):
    def line(self, file, given=None):
        return self.page(f"({LINES})[{json.dumps(file)}]", given)

    def test_a_stop_shows_its_number_its_star_and_its_first_question(self):
        self.assertEqual(self.line("app.py"), {"badge": "1", "key": True, "text": "What is new?", "more": ""})
        self.assertEqual(self.line("lib.py"), {"badge": "1.1", "key": False, "text": "Why?", "more": ""})

    def test_and_how_many_questions_follow_the_first(self):
        given = with_stop(questions=questions("What is new?", "Why now?", "What else?"))

        self.assertEqual(self.line("app.py", given)["more"], "+2")

    def test_a_stop_with_no_questions_shows_its_lines(self):
        self.assertEqual(self.line("app.py", with_stop(questions=[])),
                         {"badge": "1", "key": True, "text": "Lines 1-2, 4", "more": ""})

    def test_with_no_lines_either_it_says_it_is_a_stop(self):
        self.assertEqual(self.line("app.py", with_stop(questions=[], ranges=[]))["text"], "Stop on the review path")

    def test_a_side_file_shows_its_note_and_the_stop_it_goes_with(self):
        self.assertEqual(self.line("README.md"), {"badge": "with 1", "key": False, "text": "What it says.", "more": ""})

    def test_a_side_file_without_a_note_names_its_stop(self):
        side = dict(PATH["stops"][0]["side_files"][0], text="")

        self.assertEqual(self.line("README.md", with_stop(side_files=[side]))["text"], "Side file of app.py")

    def test_a_skipped_file_shows_skipped_and_why(self):
        self.assertEqual(self.line("long.py"), {"badge": "Skipped", "key": False, "text": "numbers only", "more": ""})

    def test_a_skipped_file_with_no_reason(self):
        path = dict(PATH, skipped=[dict(PATH["skipped"][0], reason="")])

        self.assertEqual(self.line("long.py", with_path(path))["text"], "no reason given")

    def test_a_file_off_the_path_says_so(self):
        self.assertEqual(self.line("notes.md"), {"badge": "Not on the path", "key": False, "text": "", "more": ""})

    def test_it_is_one_line_whatever_the_agent_wrote(self):
        given = with_stop(questions=questions("What is\nnew?"))

        self.assertEqual(self.line("app.py", given)["text"], "What is new?")

    def test_without_a_review_path_no_header_has_the_line(self):
        self.assertEqual(self.page(LINES, with_path(None)), dict.fromkeys(NAMED))


# The open description (web/review_path.js's stop block), as the page's model has it: its file
# and its text, flattened, or null while none is open
SHOWN = """((d) => d && [d.file, ((flat) => flat(d.block).replace(/\\s+/g, " ").trim())(
  function flat(n) { return [n.text ?? "", ...n.kids.map(flat)].join(" "); })])(body().description)"""
# What opens each file's description in turn
EVERY = """Object.fromEntries(body().files.map((f) => {
  s = st.togglePath(s, f.path, "app.py");
  return [f.path, (SHOWN)?.[1] ?? null];
}))""".replace("SHOWN", SHOWN)


def toggle(file, top="app.py"):
    """The reviewer presses <file>'s review path line, with <top> the file at the top of the screen."""
    return f"s = st.togglePath(s, {json.dumps(file)}, {json.dumps(top)});"


class TheDescription(Pages):
    def test_no_description_shows_until_the_reviewer_asks_for_one(self):
        got = self.page("[body().description, body().files.filter((f) => 'stop' in f).length]")

        self.assertEqual(got, [None, 0])

    def test_each_files_line_opens_all_the_path_says_of_it(self):
        self.assertEqual(self.page(EVERY), {
            "app.py": 'Review path 1 app.py ★ Lines 1-2, 4 What is new? See "Greeting". Spec app.test.py "greets"'
                      ' Side file README.md (lines 1-2): What it says. Greeting It is an f-string.',
            "README.md": "Review path README.md (lines 1-2) Side file of 1 app.py What it says.",
            "lib.py": "Review path 1.1 lib.py Why? Because.",
            "long.py": "Review path Skipped: numbers only",
            "notes.md": "Review path Not on the review path: the coding agent named it nowhere.",
            "review-path.md": "Review path Not on the review path: the coding agent named it nowhere.",
        })

    def test_it_opens_by_folder_too(self):
        got = self.page(SHOWN, steps='s = st.sortTree(s, "folder");' + toggle("lib.py"))

        self.assertEqual(got, ["lib.py", "Review path 1.1 lib.py Why? Because."])

    def test_pressing_the_line_again_closes_it(self):
        self.assertIsNone(self.page(SHOWN, steps=toggle("lib.py") + toggle("lib.py")))

    def test_another_files_line_shows_that_file_instead(self):
        got = self.page(SHOWN, steps=toggle("lib.py") + toggle("long.py"))

        self.assertEqual(got, ["long.py", "Review path Skipped: numbers only"])

    def test_it_closes(self):
        self.assertIsNone(self.page(SHOWN, steps=toggle("lib.py") + "s = st.closePath(s);"))

    def test_a_poll_keeps_it_open_with_what_the_path_says_now(self):
        asked = with_stop(questions=questions("Why now?"))

        got = self.page(SHOWN, steps=toggle("app.py") + f"s = st.polled(s, {json.dumps(asked)});")

        self.assertIn("Why now?", got[1])

    def test_without_a_review_path_there_is_nothing_to_open(self):
        self.assertIsNone(self.page(SHOWN, with_path(None), toggle("lib.py")))


class ClosingTheDescription(Pages):
    def after(self, steps):
        """What shows once the reviewer, with app.py at the top of the screen, opened lib.py's
        description and <steps> happened."""
        return self.page(f"({SHOWN})?.[0] ?? null", steps=toggle("lib.py") + steps)

    def test_scrolling_with_the_same_file_at_the_top_keeps_it_open(self):
        self.assertEqual(self.after('s = st.scrolledTo(s, "app.py");'), "lib.py")

    def test_scrolling_to_another_file_closes_it(self):
        self.assertIsNone(self.after('s = st.scrolledTo(s, "README.md");'))

    def test_even_when_that_is_the_described_file(self):
        self.assertIsNone(self.after('s = st.scrolledTo(s, "lib.py");'))

    def test_a_scroll_with_none_open_changes_nothing(self):
        self.assertTrue(self.page("st.scrolledTo(s, 'lib.py') === s"))

    def test_another_tab_closes_it_for_good(self):
        self.assertIsNone(self.after('s = st.showTab(st.showTab(s, "conversation"), "files");'))

    def test_another_view_closes_it(self):
        staged = with_path()
        staged["changeset"] = dict(staged["changeset"], view="staged")

        self.assertIsNone(self.after(f"s = st.polled(s, {json.dumps(staged)});"))

    def test_another_review_closes_it(self):
        other = with_path()
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        self.assertIsNone(self.after(f"s = st.polled(s, {json.dumps(other)});"))

    def test_a_file_that_leaves_the_diff_takes_its_description_along(self):
        gone = with_path(PATH, [f for f in NAMED if f != "lib.py"])

        self.assertIsNone(self.after(f"s = st.polled(s, {json.dumps(gone)});"))


@unittest.skipUnless(shutil.which("node"), "needs node")
class WhereTheDescriptionGoes(unittest.TestCase):
    def place(self, line, width=1440, height=900):
        """Where the popover goes for a header line at <line> ({left, top, bottom}) in a window of
        <width> by <height>."""
        return run_js("scroll", f"console.log(JSON.stringify(m.popoverPlace({json.dumps(line)},"
                                f" {{ width: {width}, height: {height} }})));")

    def test_it_goes_under_the_line_down_to_the_windows_foot(self):
        got = self.place({"left": 450, "top": 244, "bottom": 266})

        self.assertEqual(got, {"left": 450, "width": 560, "top": 272, "bottom": None, "maxHeight": 612})

    def test_it_stays_inside_the_window_at_the_right_edge(self):
        got = self.place({"left": 1200, "top": 100, "bottom": 122})

        self.assertEqual((got["left"], got["width"]), (864, 560))

    def test_it_is_as_wide_as_a_narrow_window_leaves(self):
        got = self.place({"left": 120, "top": 100, "bottom": 122}, width=400)

        self.assertEqual((got["left"], got["width"]), (16, 368))

    def test_it_goes_above_a_line_near_the_windows_foot(self):
        got = self.place({"left": 450, "top": 800, "bottom": 822})

        self.assertEqual((got["top"], got["bottom"], got["maxHeight"]), (None, 106, 778))


# Under each file in Reading order: what its Viewed, next says, or null where it has none
NEXT = "body().files.map((f) => f.next && [f.next.text, f.next.label])"

# The page's actions, with an API that answers PUT /api/viewed only when the test says so
# (answer(i), refuse(i)), and what each scroll saw: its target, and the files folded by then
ACTING = """
import * as actions from "{ACTIONS}";
import { ApiError } from "{API}";
const puts = [], scrolls = [];
const folded = () => body().files.filter((f) => f.folded).map((f) => f.path);
const use = {
  api: (method, path, payload) => new Promise((resolve, reject) => puts.push({ method, path, payload, resolve, reject })),
  state: () => s,
  update: (change) => { s = change(s); },
  refresh: async () => {},
  scrollTo: (target) => scrolls.push({ target, folded: folded() }),
};
const next = (path) => actions.viewedNext(use, path);
const marked = [...s.server.viewed];
const answer = (i) => { marked.push(puts[i].payload.file); puts[i].resolve({ files: [...marked] }); };
const poll = (viewed) => { s = st.polled(s, { ...s.server, viewed }); };
const top = (file) => ({ file, row: null });"""


class ViewedNext(Pages):
    def act(self, steps, show, given=None):
        return self.page(show, given, ACTING + steps)

    def test_each_file_in_reading_order_ends_with_viewed_next(self):
        got = self.page(NEXT)

        self.assertEqual(got[:2], [["Viewed, next", "Next: README.md"], ["Viewed, next", "Next: lib.py"]])
        self.assertEqual(got[-1], ["Viewed", "The last file"])

    def test_by_folder_or_without_a_review_path_no_file_has_it(self):
        by_folder = self.page(NEXT, steps='s = st.sortTree(s, "folder");')

        self.assertEqual(by_folder, [None] * len(NAMED))
        self.assertEqual(self.page(NEXT, with_path(None)), [None] * len(NAMED))

    def test_it_folds_the_file_and_lands_on_the_next_files_top_twice_in_a_row_before_either_mark_arrives(self):
        got = self.act("""
next("app.py");
next("README.md");""", "[scrolls, puts.map((p) => [p.method, p.path, p.payload])]")

        self.assertEqual(got, [
            [{"target": {"file": "README.md", "row": None}, "folded": ["app.py"]},
             {"target": {"file": "lib.py", "row": None}, "folded": ["app.py", "README.md"]}],
            [["PUT", "/api/viewed", {"file": "app.py", "viewed": True}],
             ["PUT", "/api/viewed", {"file": "README.md", "viewed": True}]],
        ])

    def test_marks_that_arrive_late_move_nothing_and_leave_the_files_folded(self):
        got = self.act("""
const first = next("app.py"), second = next("README.md");
const seen = [];
poll([]);                              // a poll from before either mark was kept
seen.push(folded());
answer(0);
await first;
seen.push(folded());
answer(1);
await second;
poll(["app.py", "README.md"]);
seen.push(folded());""", "[seen, scrolls.map((x) => x.target.file)]")

        self.assertEqual(got, [[["app.py", "README.md"]] * 3, ["README.md", "lib.py"]])

    def test_a_file_picked_from_the_tree_folds_too_and_the_next_one_may_be_viewed_already(self):
        # The next file is the next in Reading order, viewed or not
        got = self.act("""
s = st.selectFile(s, "app.py");
const done = next("app.py");
answer(0);
await done;""", "[scrolls.map((x) => x.target), folded()]", dict(with_path(), viewed=["README.md"]))

        self.assertEqual(got, [[{"file": "README.md", "row": None}], ["app.py", "README.md"]])

    def test_the_last_file_is_marked_and_folded_with_nowhere_to_go(self):
        got = self.act("""
const done = next("review-path.md");
answer(0);
await done;""", "[scrolls, folded(), marked]")

        self.assertEqual(got, [[], ["review-path.md"], ["review-path.md"]])

    def test_a_refused_mark_opens_the_file_again_brings_it_back_and_says_why(self):
        got = self.act("""
const done = next("app.py");
puts[0].reject(new ApiError(404, "no such file in the changeset"));
const taken = await done;""", "[taken, scrolls.map((x) => x.target.file), folded(), m.pageModel(s).problem.includes('no such file')]")

        self.assertEqual(got, [False, ["README.md", "app.py"], [], True])


if __name__ == "__main__":
    unittest.main()
