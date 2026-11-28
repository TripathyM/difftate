"""Layout D with its Vim keys (#264, web/d/vim.js): what presses do to the page, seen in the
page's model, the calls made and where it scrolls. Node runs it, with a fake review API and a
fake screen."""
import json
import shutil
import unittest

from browser_d import answers, changed, run_js

# Unified rows of a.py: 0 hunk, 1 line 1, 2 old 2, 3 new 2, 4 line 3, 5 line 4, 6 hunk,
# 7 line 10, 8 new 11, 9 old 11 / new 12
A = changed("a.py", "@@ -1,4 +1,4 @@", " one", "-two", "+TWO", " three", " four",
            "@@ -10,2 +10,3 @@", " ten", "+ten and a half", " eleven")
B = changed("b.py", "@@ -1 +1 @@", "-old", "+new")


def thread(tid, file="a.py", line=3, status="open", **more):
    anchor = None if file is None else {"file": file, "side": "new", "startLine": line, "endLine": line, "code": "x"}
    return dict({"id": tid, "anchor": anchor, "status": status, "state": "replied" if status == "open" else None,
                 "outdated": False,
                 "comments": [{"id": f"c-{tid}", "author": "reviewer", "body": f"about {tid}", "time": "2026-01-01T00:00:00Z"}]},
                **more)


# The page, a fake screen that records where it is sent, and a fake API that records what it is
# asked. FIRST is the first line on screen; a cursor is on screen unless OFF says it isn't.
HARNESS = """
const { initialState, polled, setSetting } = await import("{STATE}");
const { pageModel } = await import("{PAGE}");
const { typeIn } = await import("{DRAFTS}");
const { filterPicker } = await import("{PICKER}");
const filter = (query) => { state = filterPicker(state, query); };
const poll = POLL;
let state = polled(initialState("TAB", KEPT), poll);
const calls = [], did = [];
let FIRST = { file: "a.py", row: 1 }, OFF = false, SCROLLED_AWAY = false, REFUSE = null;
const note = (...what) => did.push(what);
const screen = {
  firstShown: () => FIRST,
  isShown: () => !OFF,
  isThreadShown: () => !SCROLLED_AWAY,
  fileInView: () => "a.py",
  halfScreen: () => 3,
  reveal: (target) => note("reveal", target),
  scrollLines: (n) => note("scrollLines", n),
  scrollEnd: (bottom) => note("scrollEnd", bottom),
  showThread: (target, id) => note("showThread", target, id),
  focusBox: (key) => note("focusBox", key),
  leaveBox: (key) => note("leaveBox", key),
  top: () => note("top"),
};
const use = {
  state: () => state,
  update: (change) => { state = change(state); },
  refresh: async () => {},
  copy: async (text) => note("copy", text),
  scrollTo: (target) => note("scrollTo", target),
  screen,
  async api(method, path, payload) {
    if (method === "GET" && path === "/api/review") return state.server.review;
    calls.push(payload === undefined ? [method, path] : [method, path, payload]);
    if (REFUSE) { const { ApiError } = await import("{API}"); throw new ApiError(409, REFUSE); }
    if (path === "/api/viewed") return { files: payload.viewed ? [payload.file] : [] };
    if (path === "/api/mode") return { mode: payload.mode, held: [], submitted: [] };
    if (path === "/api/done") return { ...state.server.done, done: payload.done };
    if (path === "/api/agent") return { ...state.server.agent, agent: payload.agent, source: "review" };
    if (path.startsWith("/api/export")) return "the export";
    return {};
  },
};
const BODY = { tagName: "BODY" };
// "j", "Space", "C-d", or a keydown event's own fields
const event = (p) => {
  if (typeof p !== "string") return { target: BODY, ...p };
  const ctrl = p.startsWith("C-");
  const key = ctrl ? p.slice(2) : p === "Space" ? " " : p === "Esc" ? "Escape" : p;
  return { key, ctrlKey: ctrl, target: BODY };
};
const took = [];
async function press(...presses) {
  for (const p of presses) {
    const done = m.keyPress(use, event(p));
    took.push(Boolean(done));
    await done;
  }
}
const leader = (key) => press("Space", "r", key);
const page = () => pageModel(state);
const vim = () => page().vim;
const files = () => page().body.files;
// Where the cursor is drawn: [file, row, side]
const cursor = () => files().flatMap((f) => f.rows.flatMap((r, row) => (r.cursor ? [[f.path, row, r.cursor]] : [])));
const drafts = () => files().flatMap((f) => f.rows.flatMap((r) => r.drafts ?? []).concat(f.top.drafts));
const picked = () => files().flatMap((f) => f.rows.flatMap((r, row) => (r.picked?.length ? [row] : [])));
const out = (value) => console.log(JSON.stringify(value));
"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class Keys(unittest.TestCase):
    def run_keys(self, body, threads=(), tab="files", kept=None, diff=A + B, **more):
        poll = answers(changeset={"view": "", "diff": diff, "versions": {}}, threads=list(threads), **more)
        script = HARNESS.replace('"TAB"', json.dumps(tab)).replace("KEPT", json.dumps(kept or {}))
        script = script.replace("POLL", json.dumps(poll))
        return run_js("vim", script + body)


class TheLineCursor(Keys):
    def test_j_and_k_move_it_and_the_page_scrolls_to_it(self):
        got = self.run_keys("""
await press("j"); const first = cursor();
await press("j", "j"); const down = cursor();
await press("k");
out([first, down, cursor(), did.at(-1), took]);""")

        self.assertEqual(got, [[["a.py", 1, "new"]], [["a.py", 3, "new"]], [["a.py", 2, "old"]],
                               ["reveal", {"file": "a.py", "row": 2}], [True] * 4])

    def test_gg_G_and_half_a_screen(self):
        got = self.run_keys("""
const at = [];
for (const keys of [["G"], ["g", "g"], ["C-d"], ["C-u"]]) { await press(...keys); at.push(cursor()[0]); }
out(at);""")

        self.assertEqual(got, [["b.py", 2, "new"], ["a.py", 1, "new"], ["a.py", 4, "new"], ["a.py", 1, "new"]])

    def test_when_the_cursor_is_off_screen_it_starts_again_from_the_first_line_there(self):
        got = self.run_keys("""
await press("j");
OFF = true; FIRST = { file: "a.py", row: 7 };
await press("j");
out(cursor());""")

        self.assertEqual(got, [["a.py", 7, "new"]])

    def test_h_and_l_pick_the_side_in_split_view(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 2 };
await press("j"); const start = cursor();
await press("h"); const old = cursor();
await press("l");
out([start, old, cursor()]);""", kept={"layout": "split"})

        self.assertEqual(got, [[["a.py", 2, "new"]], [["a.py", 2, "old"]], [["a.py", 2, "new"]]])

    def test_a_held_key_goes_on_moving_but_does_nothing_else_again(self):
        got = self.run_keys("""
await press("j", { key: "j", repeat: true }, { key: "j", repeat: true });
const moved = cursor();
await press("Space", { key: " ", repeat: true });
out([moved, vim().which.title, calls]);""")

        self.assertEqual(got, [[["a.py", 3, "new"]], "Space …", []])

    def test_on_the_conversation_tab_the_moves_scroll_the_page(self):
        got = self.run_keys("""
await press("j", "k", "C-d", "G", "g", "g");
out(did);""", tab="conversation")

        self.assertEqual(got, [["scrollLines", 1], ["scrollLines", -1], ["scrollLines", 3],
                               ["scrollEnd", True], ["scrollEnd", False]])

    def test_another_review_has_no_cursor(self):
        other = dict(answers()["review"], id="other-12345678")

        got = self.run_keys(f"""
await press("j", "V");
state = polled(state, {{ ...state.server, review: {json.dumps(other)} }});
out([cursor(), picked()]);""")

        self.assertEqual(got, [[], []])


class SelectingAndCommenting(Keys):
    def test_V_selects_lines_and_Space_r_c_drafts_a_comment_on_them(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 3 };
await press("j", "V", "j", "j");
const marked = picked();
await leader("c");
const [draft] = drafts();
out([marked, draft.title, state.own.boxes[draft.key].anchor.code, did.at(-1)[0], did.at(-1)[1] === draft.key, vim().line]);""")

        self.assertEqual(got, [[3, 4, 5], "Comment on lines 2–4", "TWO\nthree\nfour", "focusBox", True, ""])

    def test_Space_r_c_comments_on_the_cursors_line(self):
        got = self.run_keys("""
await press("j"); await leader("c");
out(drafts().map((d) => d.title));""")

        self.assertEqual(got, ["Comment on line 1"])

    def test_v_selects_too_and_pressed_again_or_Esc_stops(self):
        got = self.run_keys("""
await press("j", "v", "j"); const on = [picked(), vim().line];
await press("v"); const off = picked();
await press("v", "Esc");
out([on, off, picked(), vim().line]);""")

        self.assertEqual(got, [[[1, 3], "Selecting lines: Space r c comments on them, Esc stops"], [], [], ""])

    def test_lines_with_a_gap_between_them_are_too_many_for_one_comment(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 5 };
await press("j", "V", "j"); await leader("c");
out([drafts(), vim().line]);""")

        self.assertEqual(got, [[], "Those lines aren't all in one piece of the diff: select fewer"])

    def test_a_cursor_whose_line_a_poll_took_away_takes_no_comment(self):
        got = self.run_keys(f"""
await press("j"); await leader("c");
FIRST = {{ file: "b.py", row: 1 }}; OFF = true;
await press("j");
state = polled(state, {{ ...state.server, changeset: {{ ...state.server.changeset, diff: {json.dumps(A)} }} }});
did.length = 0;
await leader("c");
out([did, vim().line]);""")

        self.assertEqual(got, [[], "Put the cursor on a line first (j)"])

    def test_nor_does_one_in_a_file_that_is_folded_now(self):
        got = self.run_keys("""
FIRST = { file: "b.py", row: 1 };
await press("j"); await leader("v"); // the last file: it folds, with the cursor in it
await leader("c");
out([Object.keys(state.own.boxes), vim().line]);""")

        self.assertEqual(got, [[], "Put the cursor on a line first (j)"])

    def test_with_no_cursor_Space_r_c_says_how_to_get_one(self):
        got = self.run_keys("""
await leader("c");
out([drafts(), vim().line]);""")

        self.assertEqual(got, [[], "Put the cursor on a line first (j)"])


class Jumps(Keys):
    def test_next_change_and_file_go_to_computed_targets(self):
        got = self.run_keys("""
const at = [];
for (const keys of [["]", "h"], ["]", "h"], ["]", "h"], ["]", "h"], ["[", "h"], ["[", "f"], ["]", "f"]]) {
  await press(...keys);
  at.push(did.at(-1)[1]);
}
out([at, vim().line]);""")

        a2, a8, b1 = {"file": "a.py", "row": 2}, {"file": "a.py", "row": 8}, {"file": "b.py", "row": 1}
        # from the first line on screen; ]f and [f go to a file's top
        self.assertEqual(got[0], [a2, a8, b1, a2, b1, {"file": "a.py", "row": None}, {"file": "b.py", "row": None}])

    def test_a_jump_round_the_end_says_so(self):
        got = self.run_keys("""
await press("G", "]", "h");
out([did.at(-1)[1], vim().line]);""")

        self.assertEqual(got, [{"file": "a.py", "row": 2}, "Back to the first change on screen"])

    def test_next_file_opens_a_folded_one_and_puts_the_cursor_in_it(self):
        got = self.run_keys("""
await press("j", "]", "f");
out([files()[1].folded, cursor()]);""", viewed=["b.py"])

        self.assertEqual(got, [False, [["b.py", 1, "old"]]])

    def test_next_open_thread_goes_to_its_lines_from_either_tab(self):
        got = self.run_keys("""
await press("]", "r");
out([page().tab, did.at(-1), cursor(), files()[0].rows.flatMap((r) => r.threads ?? []).map((t) => [t.id, Boolean(t.focused)])]);""",
                            threads=[thread("t1", line=3)], tab="conversation")

        self.assertEqual(got, ["files", ["showThread", {"file": "a.py", "row": 4}, "t1"], [["a.py", 4, "new"]], [["t1", True]]])

    def test_a_general_thread_is_gone_to_on_the_conversation_tab(self):
        got = self.run_keys("""
await press("]", "r");
out([page().tab, did.at(-1), page().body.threads.map((t) => Boolean(t.focused))]);""", threads=[thread("g", file=None)])

        self.assertEqual(got, ["conversation", ["showThread", None, "g"], [True]])

    def test_going_to_a_thread_shows_the_comments_the_reviewer_hid(self):
        got = self.run_keys("""
state = { ...state, own: { ...state.own, hideComments: true } };
await press("[", "r");
out([page().body.commentsHidden, did.at(-1)]);""", threads=[thread("t1", line=3)])

        self.assertEqual(got, [False, ["showThread", {"file": "a.py", "row": 4}, "t1"]])

    def test_with_no_open_thread_it_says_so(self):
        got = self.run_keys('await press("]", "r"); out(vim().line);')

        self.assertEqual(got, "No open threads")


class ThreadActions(Keys):
    def test_Space_r_R_resolves_the_thread_on_the_cursors_line_and_Space_r_O_reopens(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
await press("j"); await leader("R");
const said = vim().line;
state = polled(state, { ...state.server, threads: [{ ...state.server.threads[0], status: "resolved" }] });
await leader("O");
out([calls, said, vim().line]);""", threads=[thread("t1")])

        self.assertEqual(got, [[["PATCH", "/api/threads/t1/status", {"status": "resolved"}],
                                ["PATCH", "/api/threads/t1/status", {"status": "open"}]], "Resolved", "Reopened"])

    def test_the_thread_gone_to_is_the_one_the_keys_act_on(self):
        got = self.run_keys("""
await press("]", "r"); await leader("R");
out(calls);""", threads=[thread("g", file=None)])

        self.assertEqual(got, [["PATCH", "/api/threads/g/status", {"status": "resolved"}]])

    def test_a_refusal_is_said(self):
        got = self.run_keys("""
REFUSE = "Another branch is checked out";
FIRST = { file: "a.py", row: 4 };
await press("j"); await leader("R");
out(vim().line);""", threads=[thread("t1")])

        self.assertEqual(got, "Another branch is checked out")

    def test_with_no_thread_there_it_says_what_is_missing(self):
        got = self.run_keys("""
const said = [];
await leader("R"); said.push(vim().line);
await press("j"); await leader("R"); said.push(vim().line);
await leader("O"); said.push(vim().line);
await leader("t"); said.push(vim().line);
out(said);""")

        self.assertEqual(got, ["Put the cursor on a line first (j), or go to a thread with ]r", "No open thread on this line",
                               "No resolved or dismissed thread on this line", "No thread on this line"])

    def test_a_thread_or_line_out_of_sight_is_not_acted_on(self):
        got = self.run_keys("""
await press("]", "r");
SCROLLED_AWAY = true; OFF = true;
await leader("R");
out([calls, vim().line]);""", threads=[thread("t1")])

        self.assertEqual(got, [[], "Put the cursor on a line first (j), or go to a thread with ]r"])

    def test_with_the_thread_gone_to_out_of_sight_the_cursors_line_counts(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
await press("j", "[", "r"); // back to the outdated thread at the file's top, which moves no cursor
SCROLLED_AWAY = true;
await leader("R");
out(calls.map((c) => c[1]));""", threads=[thread("old", line=9, outdated=True), thread("near", line=3)])

        self.assertEqual(got, ["/api/threads/near/status"])

    def test_with_several_threads_on_the_line_it_asks_which(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
await press("j"); await leader("R");
const asked = vim().picker;
m.pickerKey(use, { key: "ArrowDown" });
await m.pickerKey(use, { key: "Enter" });
out([asked.title, asked.items.map((i) => i.text), calls, vim().picker]);""", threads=[thread("t1"), thread("t2")])

        self.assertEqual(got, ["Which thread?", ["a.py, line 3: about t1", "a.py, line 3: about t2"],
                               [["PATCH", "/api/threads/t2/status", {"status": "resolved"}]], None])

    def test_read_unfolds_a_resolved_thread_and_comment_on_it_focuses_its_reply_box(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
const folded = () => files()[0].rows.flatMap((r) => r.threads ?? []).map((t) => t.folded);
await press("j"); const before = folded();
await leader("t");
out([before, folded(), did.at(-1)[0]]);""", threads=[thread("done", status="resolved")])
        reply = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
await press("j"); await leader("a");
out(did.at(-1));""", threads=[thread("t1")])

        self.assertEqual(got, [[True], [False], "showThread"])
        self.assertEqual(reply, ["focusBox", "reply:t1"])

    def test_comment_on_a_thread_stays_on_the_conversation_tab(self):
        got = self.run_keys("""
await press("]", "r"); await press("2"); // the page's own key, which the Vim keys leave
state = { ...state, own: { ...state.own, tab: "conversation" } };
await leader("a");
out([page().tab, did.at(-1)]);""", threads=[thread("t1")])

        self.assertEqual(got, ["conversation", ["focusBox", "reply:t1"]])

    def test_Space_r_e_expands_every_closed_thread_or_folds_them_again(self):
        got = self.run_keys("""
const folded = () => files()[0].rows.flatMap((r) => r.threads ?? []).map((t) => t.folded);
const seen = [folded()];
for (let i = 0; i < 2; i++) { await leader("e"); seen.push([folded(), vim().line]); }
out(seen);""", threads=[thread("one", status="resolved"), thread("two", line=4, status="dismissed")])

        self.assertEqual(got, [[True, True], [[False, False], "Every thread is expanded"],
                               [[True, True], "Resolved and dismissed threads are one line"]])


class ReviewActions(Keys):
    def test_Space_r_v_marks_the_cursors_file_viewed_and_goes_on_to_the_next(self):
        got = self.run_keys("""
await press("j"); await leader("v");
out([calls, did.filter((d) => d[0] === "scrollTo"), cursor(), files()[0].folded, vim().line]);""")

        self.assertEqual(got, [[["PUT", "/api/viewed", {"file": "a.py", "viewed": True}]],
                               [["scrollTo", {"file": "b.py", "row": None}]], [["b.py", 1, "old"]], True,
                               "Viewed a.py"])

    def test_Space_r_v_on_a_viewed_file_unmarks_it(self):
        got = self.run_keys("""
await leader("v");
out([calls, files()[0].folded, vim().line]);""", viewed=["a.py"])

        self.assertEqual(got, [[["PUT", "/api/viewed", {"file": "a.py", "viewed": False}]], False, "Not viewed: a.py"])

    def test_mode_done_and_export_make_the_calls_the_buttons_make_and_say_so(self):
        got = self.run_keys("""
const said = [];
for (const key of ["M", "D", "E"]) { await leader(key); said.push(vim().line); }
out([calls.map((c) => c.slice(0, 2)), calls[0][2], calls[1][2], said, did.filter((d) => d[0] === "copy")]);""")

        calls, mode, done, said, copied = got
        self.assertEqual(calls[:2], [["PUT", "/api/mode"], ["PUT", "/api/done"]])
        self.assertTrue(calls[2][1].startswith("/api/export"))
        self.assertEqual((mode, done), ({"mode": "batched"}, {"done": True}))
        self.assertEqual(said, ["Batched: comments are held until you submit the review.", "Marked Done",
                                "Export copied: paste it into an agent session."])
        self.assertEqual(copied, [["copy", "the export"]])

    def test_submit_opens_the_panel_of_a_batched_review_and_a_live_one_has_nothing_held(self):
        got = self.run_keys("""
await leader("S"); const live = [vim().line, page().header.submit];
await leader("M"); await leader("S");
out([live, Boolean(page().header.submit.panel), did.at(-1), calls.length]);""")

        self.assertEqual(got[0], ["Live: nothing is held, so there is nothing to submit", None])
        self.assertEqual(got[1], True)
        self.assertEqual(got[2], ["focusBox", "summary:" + answers()["review"]["id"]])
        self.assertEqual(got[3], 1)  # only the mode: nothing is submitted until the reviewer sends

    def test_split_or_unified_the_file_tree_and_a_general_thread(self):
        got = self.run_keys("""
await leader("d"); const split = page().body.layout;
await leader("F"); const hidden = page().body.sidebar;
await leader("F");
const shown = page().body.sidebar;
await leader("G");
out([split, hidden, shown, page().tab, did.at(-1)]);""")

        self.assertEqual(got, ["split", False, True, "conversation", ["focusBox", "general:" + answers()["review"]["id"]]])

    def test_the_view_and_the_agent_are_picked_from_lists(self):
        got = self.run_keys("""
await leader("V");
const views = vim().picker;
filter("staged");
await m.pickerKey(use, { key: "Enter" });
await leader("A");
const agents = vim().picker;
m.pickerKey(use, { key: "k", ctrlKey: true }); // round to the last
await m.pickerKey(use, { key: "Enter" });
out([views.title, views.items[0], agents.items.length, calls, vim().line]);""")

        title, first, agents, calls, line = got
        self.assertEqual((title, first["text"], first["current"]), ("Choose the view", "All changes", True))
        self.assertEqual(calls[0], ["PUT", "/api/view", {"view": "staged"}])
        self.assertEqual(calls[1][:2], ["PUT", "/api/agent"])
        self.assertEqual(agents, len(answers()["agent"]["names"]) + 1)
        self.assertIn("replies in this review, from the next run.", line)

    def test_the_file_picker_filters_and_goes_to_the_file(self):
        got = self.run_keys("""
await leader("f");
filter("B.PY");
const items = vim().picker.items.map((i) => i.text);
await m.pickerKey(use, { key: "Enter" });
out([items, did.at(-1), cursor()]);""")

        self.assertEqual(got, [["b.py"], ["reveal", {"file": "b.py", "row": None}], [["b.py", 1, "old"]]])

    def test_the_thread_picker_lists_general_ones_first_open_ones_first_and_Esc_closes_it(self):
        got = self.run_keys("""
await leader("s");
const items = vim().picker.items.map((i) => [i.text, i.hint]);
m.pickerKey(use, { key: "Escape" });
out([items, vim().picker, did]);""", threads=[thread("closed", line=1, status="resolved"), thread("late", "b.py", 1),
                                              thread("early", line=3), thread("g", file=None)])

        # each with the labels its card has
        self.assertEqual(got, [[["On the whole changeset: about g", "Replied"], ["a.py, line 3: about early", "Replied"],
                                ["b.py, line 1: about late", "Replied"], ["a.py, line 1: about closed", "Resolved"]],
                               None, []])


class InThePicker(Keys):
    def test_Enter_on_an_item_the_keyboard_went_to_is_that_items(self):
        got = self.run_keys("""
await leader("V");
const mine = m.pickerKey(use, { key: "Enter", target: { tagName: "BUTTON" } });
out([mine, calls, vim().picker.title]);""")

        self.assertEqual(got, [False, [], "Choose the view"])


class InACommentBox(Keys):
    # A press in the box <key>, as main.js gives it
    BOX = """
const box = (key, p) => ({ target: { tagName: "TEXTAREA" }, box: key, ...p });
await press("j"); await leader("c");
const key = drafts()[0].key;
const type = (text) => { state = typeIn(state, key, text); };
"""

    def test_no_vim_key_works_while_the_reviewer_types(self):
        got = self.run_keys(self.BOX + """
took.length = 0;
await press(...["j", " ", "r", "c", "?", "i", "q", "V"].map((k) => box(key, { key: k })),
  { key: "j", target: { tagName: "INPUT", type: "search" } });
out([took, drafts().length, cursor()]);""")

        self.assertEqual(got, [[False] * 9, 1, [["a.py", 1, "new"]]])

    def test_Ctrl_S_sends_what_the_box_holds(self):
        got = self.run_keys(self.BOX + """
type("Why?");
await press(box(key, { key: "s", ctrlKey: true }));
out([took.at(-1), calls.map((c) => [c[0], c[1], c[2].body]), drafts().length]);""")

        self.assertEqual(got, [True, [["POST", "/api/threads", "Why?"]], 0])

    def test_a_box_that_stays_once_sent_is_left_so_the_next_key_is_a_vim_key(self):
        got = self.run_keys("""
FIRST = { file: "a.py", row: 4 };
await press("j"); await leader("a");
state = typeIn(state, "reply:t1", "Done?");
await press({ key: "s", ctrlKey: true, target: { tagName: "TEXTAREA" }, box: "reply:t1" });
const sent = did.at(-1);
REFUSE = "No";
state = typeIn(state, "reply:t1", "Again?");
did.length = 0;
await press({ key: "s", ctrlKey: true, target: { tagName: "TEXTAREA" }, box: "reply:t1" });
out([sent, did]);""", threads=[thread("t1")])

        self.assertEqual(got, [["leaveBox", "reply:t1"], []])  # a refused one keeps the caret

    def test_after_Esc_i_goes_back_into_the_box_and_Ctrl_S_still_sends_it(self):
        got = self.run_keys(self.BOX + """
type("Why?");
state = m.escapedBox(state, key); // what the box's own Esc does
const line = vim().line;
await press("i");
const back = did.at(-1);
state = m.escapedBox(state, key);
await press("C-s");
out([line, back[0], back[1] === key, calls.length]);""")

        self.assertEqual(got, ["i goes back into the box · q closes it, keeping the text", "focusBox", True, 1])

    def test_without_a_box_just_left_i_stays_the_pages_own_key(self):
        got = self.run_keys(self.BOX + """
type("Why?");
took.length = 0;
await press("i");
state = m.escapedBox(state, key);
await press("j", "i"); // any other key leaves the box behind
out(took);""")

        self.assertEqual(got, [False, True, False])

    def test_q_closes_a_draft_keeping_its_text_which_commenting_there_again_brings_back(self):
        got = self.run_keys(self.BOX + """
type("Why?");
state = m.escapedBox(state, key);
await press("q");
const closed = [drafts().length, picked(), vim().line];
await leader("c");
out([closed, drafts().map((d) => d.text)]);""")

        self.assertEqual(got, [[0, [], "Draft kept: comment on those lines again to get it back"], ["Why?"]])

    def test_q_says_so_when_the_draft_has_to_stay_in_sight(self):
        got = self.run_keys(self.BOX + f"""
type("Why?");
state = polled(state, {{ ...state.server, changeset: {{ ...state.server.changeset, diff: {json.dumps(B)} }} }});
state = m.escapedBox(state, key);
await press("q");
out([vim().line, page().body.loose.length]);""")

        self.assertEqual(got, ["The draft stays in sight: the diff no longer shows the lines you picked", 1])

    def test_sent_after_Esc_there_is_no_box_to_go_back_to(self):
        got = self.run_keys(self.BOX + """
type("Why?");
state = m.escapedBox(state, key);
await press("C-s");
took.length = 0;
const line = vim().line;
await press("i");
out([line, took]);""")

        self.assertEqual(got, ["", [False]])

    def test_a_closed_draft_shows_again_once_the_diff_no_longer_has_its_lines(self):
        got = self.run_keys(self.BOX + f"""
type("Why?");
state = m.escapedBox(state, key);
await press("q");
state = polled(state, {{ ...state.server, changeset: {{ ...state.server.changeset, diff: {json.dumps(B)} }} }});
out(page().body.loose.map((d) => d.text));""")

        self.assertEqual(got, ["Why?"])

    def test_Esc_on_an_empty_draft_drops_it_so_there_is_nothing_to_go_back_to(self):
        got = self.run_keys(self.BOX + """
state = m.escapedBox(state, key);
out([drafts().length, vim().line]);""")

        self.assertEqual(got, [0, ""])


class WhatThePageSays(Keys):
    def test_Space_shows_which_key_until_the_keys_end_or_Esc(self):
        got = self.run_keys("""
await press("Space"); const space = vim().which;
await press("Esc");
out([space, vim().which]);""")

        self.assertEqual(got, [{"title": "Space …", "keys": [{"key": "r", "text": "+review"}]}, None])

    def test_question_mark_shows_all_keys_where_one_is_changed_or_turned_off(self):
        got = self.run_keys("""
const { setKey, closeKeys } = await import("{SETTINGS}");
await press("?");
const rows = () => vim().help.groups.flatMap((g) => g.rows);
const row = (name) => rows().find((r) => r.name === name).key;
state = setKey(setKey(state, "down", "n"), "up", "");
const changed = [row("down"), row("up")];
await press("j"); // the dialog has the keys while it is open
const during = cursor();
state = closeKeys(state);
await press("n", "n");
await press("k", "j");
out([changed, during, cursor(), vim().help, took]);""")

        self.assertEqual(got, [["n", ""], [], [["a.py", 2, "old"]], None, [True, False, True, True, False, False]])

    def test_a_focused_control_keeps_Space_when_the_keyboard_put_the_focus_there(self):
        got = self.run_keys("""
await press({ key: " ", target: { tagName: "BUTTON" }, ringed: true });
out([took, vim().which]);""")

        self.assertEqual(got, [[False], None])

    def test_the_browsers_own_shortcuts_are_left_alone(self):
        got = self.run_keys("""
await press("C-f", { key: "j", metaKey: true }, { key: "j", altKey: true }, { key: "j", isComposing: true },
  { key: "j", defaultPrevented: true }, { key: "Shift" }, "Esc", "C-s");
await press("Space", "C-c");
out(took);""")

        self.assertEqual(got, [False] * 8 + [True, False])

    def test_the_extension_notice_shows_until_the_reviewer_has_seen_it(self):
        got = self.run_keys("""
const { seeVimNotice } = await import("{SETTINGS}");
const first = vim().notice;
state = seeVimNotice(state);
await press("?");
out([first, vim().notice, vim().help.extension]);""")

        self.assertIn("Vimium", got[0])
        self.assertIn("turn it off", got[0])
        self.assertEqual(got[1], "")
        self.assertIn("Vimium", got[2])

    def test_turned_off_there_is_no_cursor_notice_or_key_but_the_pages_own(self):
        got = self.run_keys("""
const { setVim } = await import("{SETTINGS}");
await press("j", "V");
state = setVim(state, false);
took.length = 0;
await press("j", " ", "?", "C-s");
out([took, cursor(), picked(), vim().on, vim().notice, vim().which, page().settings.vim]);""")

        self.assertEqual(got, [[False] * 4, [], [], False, "", None, False])

    def test_off_and_changed_keys_are_kept_in_the_browser(self):
        got = self.run_keys("""
const { setKey, setVim, seeVimNotice, resetKeys, readSettings, keepSettings } = await import("{SETTINGS}");
const stored = new Map();
const storage = { getItem: (k) => stored.get(k) ?? null, setItem: (k, v) => stored.set(k, v), removeItem: (k) => stored.delete(k) };
const change = (next) => { keepSettings(storage, state.own.settings, next.own.settings); state = next; };
change(setKey(state, "down", "n"));
change(setKey(state, "up", ""));
change(setVim(state, false));
change(seeVimNotice(state));
const kept = readSettings(storage);
change(resetKeys(state));
const reset = readSettings(storage);
stored.set("difftate.keys", "not json");
const broken = readSettings(storage);
stored.set("difftate.keys", JSON.stringify({ down: 3, nothing: "x", up: "u" }));
const odd = readSettings(storage).keys;
change(setKey(setKey(state, "down", "n"), "down", "j")); // back to its default: no change to keep
out([kept, reset.keys ?? null, broken.keys ?? null, odd, state.own.settings.keys, stored.has("difftate.keys")]);""")

        kept, reset, broken, odd, back, stored = got
        self.assertEqual(kept, {"keys": {"down": "n", "up": ""}, "vim": "off", "vimNotice": "seen"})
        self.assertEqual((reset, broken, odd), (None, None, {"up": "u"}))
        self.assertEqual((back, stored), ({}, False))


if __name__ == "__main__":
    unittest.main()
