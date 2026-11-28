"""Layout D's review mode, Submit review and Mark as Done (#261): what a comment box's buttons are,
the list of what is held, and the calls each control makes, in order (web/d/page.js and actions.js). Node
runs it, with API answers shaped like the released transcript's and a fake review API."""
import json
import shutil
import unittest
import urllib.parse

from browser_d import answers, released, run_js

BATCHED = {"mode": "batched", "held": []}
# GET /api/done's answers in the released transcript: not Done, and Done
UNDONE = released("GET", "/api/done", lambda a: not a["done"])
DONE = released("GET", "/api/done", lambda a: a["done"])


def open_thread():
    """An open general thread of the released transcript."""
    threads = released("GET", "/api/threads", lambda a: any(t["anchor"] is None and t["status"] == "open" for t in a))
    return next(t for t in threads if t["anchor"] is None and t["status"] == "open")


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheCommentBoxButtons(unittest.TestCase):
    def buttons(self, mode):
        """(send, start) of each kind of box in a review in <mode>: a draft's, a thread's reply
        box and the general thread's."""
        poll = answers(mode=mode, threads=[open_thread()])
        return run_js("page", f"""
import * as st from "{{STATE}}";
import {{ dragStart, dragEnd }} from "{{DRAFTS}}";
let s = st.polled(st.initialState("files"), {json.dumps(poll)});
s = dragEnd(dragStart(s, {{ path: "app.py", side: "new", line: 1 }}));
const draft = m.pageModel(s).body.files.flatMap((f) => f.rows).flatMap((r) => r.drafts ?? [])[0];
const talk = m.pageModel(st.showTab(s, "conversation")).body;
console.log(JSON.stringify([draft, talk.threads[0].reply, talk.general].map((b) => [b.send, b.start])));""")

    def test_in_a_live_review_every_box_has_comment_and_start_a_review(self):
        self.assertEqual(self.buttons({"mode": "live", "held": []}), [["Comment", "Start a review"]] * 3)

    def test_in_a_batched_review_every_box_has_add_review_comment_only(self):
        self.assertEqual(self.buttons(BATCHED), [["Add review comment", None]] * 3)


class Actions(unittest.TestCase):
    def run_actions(self, steps, show, **poll):
        """<show> after the JS lines <steps> on a page whose poll answered <poll>, with a fake
        review API. calls: what it was asked. refuse: {"METHOD /path": why} it refuses. onBranch:
        the review the folder is on. The next refresh polls what the API changed."""
        first = answers(**dict({"threads": [open_thread()], "changeset": dict(answers()["changeset"], view="HEAD")}, **poll))
        return run_js("actions", f"""
import * as st from "{{STATE}}";
import * as d from "{{DRAFTS}}";
import {{ pageModel }} from "{{PAGE}}";
const calls = [];
const refuse = {{}};
let s = st.polled(st.initialState("conversation"), {json.dumps(first)});
let server = s.server;
let onBranch = server.review.id, waitsForRun = false;
const use = {{
  api: async (method, path, payload) => {{
    calls.push(payload === undefined ? [method, path] : [method, path, payload]);
    const why = refuse[`${{method}} ${{path}}`];
    if (why) {{ const {{ ApiError }} = await import("{{API}}"); throw new ApiError(409, why); }}
    if (path === "/api/review") return {{ id: onBranch, waitingForRun: waitsForRun, ...server.mode }};
    // A batched review holds a new thread; a submit sends all that is held
    if (path === "/api/threads" && server.mode.mode === "batched") {{
      server = {{ ...server, mode: {{ ...server.mode, held: [...server.mode.held, "summary"] }} }};
    }}
    if (path === "/api/submit") {{
      const submitted = server.mode.held;
      server = {{ ...server, mode: {{ ...server.mode, held: [] }} }};
      return {{ ...server.mode, submitted }};
    }}
    if (path === "/api/mode") {{
      const submitted = payload.mode === "live" ? server.mode.held : [];
      server = {{ ...server, mode: {{ mode: payload.mode, held: payload.mode === "live" ? [] : server.mode.held }} }};
      return {{ ...server.mode, submitted }};
    }}
    if (path === "/api/done") {{
      server = {{ ...server, done: payload.done ? {json.dumps(DONE)} : {json.dumps(UNDONE)} }};
      return server.done;
    }}
    return {{}};
  }},
  state: () => s, update: (change) => {{ s = change(s); }},
  refresh: async () => {{ calls.push("refresh"); s = st.polled(s, server); }},
}};
const page = () => pageModel(s);
const general = page().body.general.key;
{steps}
console.log(JSON.stringify({show}));""")


@unittest.skipUnless(shutil.which("node"), "needs node")
class StartAReview(Actions):
    def test_it_switches_the_review_to_batched_then_posts_the_comment(self):
        calls, box = self.run_actions(
            's = d.typeIn(s, general, "Why?"); await m.send(use, general, { start: true });',
            show="[calls, page().body.general]")

        self.assertEqual(calls, [
            ["GET", "/api/review"], ["PUT", "/api/mode", {"mode": "batched"}],
            ["POST", "/api/threads", {"anchor": None, "body": "Why?", "view": "HEAD"}], "refresh"])
        self.assertEqual((box["text"], box["send"], box["start"]), ("", "Add review comment", None))

    def test_while_the_review_waits_for_a_run_it_changes_nothing_the_mode_neither(self):
        calls, box = self.run_actions(
            'waitsForRun = true; s = d.typeIn(s, general, "Why?"); await m.send(use, general, { start: true });',
            show="[calls, page().body.general]")

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])
        self.assertEqual((box["text"], box["send"], box["sending"]), ("Why?", "Comment", False))
        self.assertEqual(box["error"], "Another branch is checked out now: the draft waits for its own branch.")

    def test_what_the_last_change_said_goes(self):
        notice = self.run_actions("""
await m.setMode(use, "live"); await m.confirmLive(use);
s = d.typeIn(s, general, "Why?"); await m.send(use, general, { start: true });""",
                                  show="page().notice", mode={"mode": "batched", "held": ["a"]})

        self.assertEqual(notice, "")

    def test_in_a_reply_box_it_asks_which_review_is_on_before_it_switches_the_mode(self):
        thread = open_thread()

        calls = self.run_actions(
            f's = d.typeIn(s, d.replyKey("{thread["id"]}"), "And?"); '
            f'await m.send(use, d.replyKey("{thread["id"]}"), {{ start: true }});', show="calls")
        other = self.run_actions(
            f's = d.typeIn(s, d.replyKey("{thread["id"]}"), "And?"); onBranch = "other-12345678"; '
            f'await m.send(use, d.replyKey("{thread["id"]}"), {{ start: true }});', show="calls")

        self.assertEqual([c[:2] for c in calls[:-1]], [
            ["GET", "/api/review"], ["PUT", "/api/mode"], ["POST", f"/api/threads/{urllib.parse.quote(thread['id'], safe='')}/comments"]])
        self.assertEqual(other, [["GET", "/api/review"], "refresh"], "the other branch's review keeps its mode")

    def test_a_refused_switch_posts_nothing_and_the_box_keeps_its_text(self):
        calls, box = self.run_actions(
            'refuse["PUT /api/mode"] = "no"; s = d.typeIn(s, general, "Why?"); await m.send(use, general, { start: true });',
            show="[calls, page().body.general]")

        self.assertEqual([c[:2] for c in calls], [["GET", "/api/review"], ["PUT", "/api/mode"]])
        self.assertEqual((box["text"], box["error"], box["sending"]), ("Why?", "no", False))

    def test_when_the_comment_is_refused_after_the_switch_the_page_shows_the_review_batched(self):
        box = self.run_actions(
            'refuse["POST /api/threads"] = "no"; s = d.typeIn(s, general, "Why?"); await m.send(use, general, { start: true });',
            show="page().body.general")

        self.assertEqual((box["text"], box["error"], box["send"]), ("Why?", "no", "Add review comment"))


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheReviewMode(Actions):
    def test_the_header_has_both_modes_with_the_polls_one_current(self):
        modes = self.run_actions("", show="page().header.modes", mode=BATCHED)

        self.assertEqual([(m["mode"], m["text"], m["current"]) for m in modes],
                         [("live", "Live", False), ("batched", "Batched", True)])

    def test_choosing_the_other_one_changes_it_and_polls_again(self):
        calls, modes = self.run_actions('await m.setMode(use, "batched");', show="[calls, page().header.modes]")

        self.assertEqual(calls, [["GET", "/api/review"], ["PUT", "/api/mode", {"mode": "batched"}], "refresh"])
        self.assertEqual([m["current"] for m in modes], [False, True])

    def test_choosing_the_one_the_review_is_in_asks_nothing(self):
        self.assertEqual(self.run_actions('await m.setMode(use, "live");', show="calls"), [])

    def test_going_live_with_held_threads_says_they_were_submitted(self):
        before, after, moved = self.run_actions("""
const before = page().header.modes[0].title;
await m.setMode(use, "live"); await m.confirmLive(use);
const after = page().notice;
s = st.showTab(s, "files");""", show="[before, after, page().notice]", mode={"mode": "batched", "held": ["a", "b"]})

        self.assertEqual(before, "Each comment goes to the coding agent as you write it. Switching to Live sends held comments to the coding agent, after asking you.")
        self.assertEqual(after, "Live: 2 held threads were submitted to the coding agent.")
        self.assertEqual(moved, "", "gone once the reviewer moves on")

    def test_a_switch_that_submits_nothing_says_what_comments_do_from_now(self):
        batched = self.run_actions('await m.setMode(use, "batched");', show="page().notice")
        live = self.run_actions('await m.setMode(use, "live");', show="page().notice", mode=BATCHED)

        self.assertEqual((batched, live), ("Batched: comments are held until you submit the review.",
                                           "Live: comments go to the coding agent as you write them."))

    def test_after_a_checkout_the_other_branchs_review_keeps_its_mode(self):
        calls, problem = self.run_actions(
            'onBranch = "other-12345678"; await m.setMode(use, "batched");', show="[calls, page().problem]")

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])
        self.assertEqual(problem, "Another branch is checked out now: nothing was changed.")

    def test_an_answer_that_comes_after_a_checkout_changes_nothing_of_the_other_branchs_review(self):
        other = answers(mode={"mode": "live", "held": []})
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        got = self.run_actions(f"""
const ask = use.api;
use.api = async (method, path, payload) => {{
  const answer = await ask(method, path, payload);
  if (method === "PUT") {{ server = {json.dumps(other)}; s = st.polled(s, server); }}
  return answer;
}};
use.refresh = async () => {{}};
await m.setMode(use, "batched");""", show="[page().header.branch, page().header.modes[0].current, page().notice]")

        self.assertEqual(got, ["other", True, ""])

    def test_a_refused_change_says_why_and_the_mode_stays(self):
        problem, modes = self.run_actions(
            'refuse["PUT /api/mode"] = "no"; await m.setMode(use, "batched");', show="[page().problem, page().header.modes]")

        self.assertEqual((problem, modes[0]["current"]), ("no", True))


def held_thread(id, anchor, *comments):
    """A held thread of the released transcript's shape: <id> on <anchor> (None: the whole
    changeset), with <comments> as (kind, body), the kinds the API's."""
    base = open_thread()
    author = {"comment": "reviewer", "reply": "agent", "progress": "difftate", "queued": "difftate"}
    return dict(base, id=id, anchor=anchor, state="held", comments=[
        dict(base["comments"][0], id=f"{id}-{i}", kind=kind, author=author[kind], body=body)
        for i, (kind, body) in enumerate(comments)])


LINES = {"file": "app.py", "side": "new", "startLine": 5, "endLine": 7, "code": "a\nb\nc"}


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheSubmitReviewButtonAndPanel(Actions):
    def test_in_a_live_review_the_button_stays_off_and_says_why_with_no_panel(self):
        submit = self.run_actions("s = st.openSubmit(s, true);", show="page().header.submit")

        self.assertEqual(submit, {
            "text": "Submit review", "count": 0, "panel": None,
            "off": "Live: comments go to the coding agent as you write them, so there is nothing to submit."})

    def test_in_a_batched_review_it_shows_the_number_held_that_get_api_mode_gives(self):
        threads = [held_thread("a", None, ("comment", "One")), held_thread("b", LINES, ("comment", "Two"))]

        submit = self.run_actions("", show="page().header.submit", threads=threads,
                                  mode={"mode": "batched", "held": ["b", "a"]})
        later = self.run_actions('server = { ...server, mode: { mode: "batched", held: [] } }; await use.refresh();',
                                 show="page().header.submit", threads=threads,
                                 mode={"mode": "batched", "held": ["b", "a"]})

        self.assertEqual(submit, {"text": "Submit review", "count": 2, "off": "", "panel": None})
        self.assertEqual(later["count"], 0)

    def test_its_panel_lists_the_held_threads_in_get_api_modes_order_with_their_held_comments(self):
        threads = [
            held_thread("other", None, ("comment", "Not held")),
            held_thread("a", None, ("comment", "One"), ("queued", "Queued"), ("comment", "And this")),
            held_thread("b", LINES, ("comment", "Sent"), ("progress", "Finished"), ("reply", "Done that"),
                        ("comment", "Not quite")),
        ]

        panel = self.run_actions("s = st.openSubmit(s, true);", show="page().header.submit.panel", threads=threads,
                                 mode={"mode": "batched", "held": ["b", "a"]})

        self.assertEqual(panel["held"], [
            {"id": "b", "where": "app.py, lines 5–7", "comments": ["Not quite"]},
            {"id": "a", "where": "On the whole changeset", "comments": ["One", "And this"]}])
        self.assertEqual(panel["none"], "")

    def held_comments(self, *comments):
        threads = [held_thread("a", None, *comments)]
        panel = self.run_actions("s = st.openSubmit(s, true);", show="page().header.submit.panel", threads=threads,
                                 mode={"mode": "batched", "held": ["a"]})
        return panel["held"][0]["comments"]

    def test_a_reply_posted_outside_a_run_answers_what_was_held(self):
        self.assertEqual(self.held_comments(("comment", "Asked"), ("reply", "Answered"), ("comment", "New")), ["New"])

    def test_a_comment_written_during_a_run_stays_listed_after_the_runs_reply(self):
        during = (("comment", "Sent"), ("progress", "Working"), ("comment", "Also this"), ("reply", "Done that"))

        self.assertEqual(self.held_comments(*during), ["Also this"])
        self.assertEqual(self.held_comments(*during, ("comment", "And that")), ["Also this", "And that"])

    def test_a_held_thread_never_lists_no_comment(self):
        comments = self.held_comments(("comment", "Sent"), ("progress", "Working"), ("comment", "Also this"),
                                      ("reply", "Part one"), ("reply", "Part two"))

        self.assertEqual(comments, ["Also this"])

    def test_a_change_to_live_closes_the_panel_so_that_batched_again_starts_with_it_closed(self):
        panel = self.run_actions("""
s = st.openSubmit(s, true);
await m.setMode(use, "live");
await m.setMode(use, "batched");""", show="page().header.submit.panel", mode=BATCHED)

        self.assertIsNone(panel)

    def test_with_nothing_held_the_panel_says_so_and_has_the_summary_box(self):
        panel = self.run_actions("s = st.openSubmit(s, true);", show="page().header.submit.panel", mode=BATCHED)

        self.assertEqual((panel["held"], panel["none"]), ([], "No comment is held."))
        box = panel["box"]
        self.assertEqual((box["title"], box["send"], box["start"], box["cancels"], box["text"]),
                         ("Summary (optional)", "Submit review", None, False, ""))
        self.assertEqual(box["hint"], "A summary is posted as a general thread, then all that is held is submitted.")

    def test_a_poll_keeps_the_panel_and_what_is_typed_in_it_and_a_checkout_closes_it(self):
        other = answers(mode=BATCHED)
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        kept, closed = self.run_actions(f"""
s = st.openSubmit(s, true);
const key = page().header.submit.panel.box.key;
s = d.typeIn(s, key, "Half");
server = {{ ...server, viewed: ["app.py"] }}; await use.refresh();
const kept = page().header.submit.panel.box.text;
s = st.polled(s, {json.dumps(other)});""", show="[kept, page().header.submit.panel]", mode=BATCHED)

        self.assertEqual((kept, closed), ("Half", None))

    def test_escape_in_the_summary_closes_the_panel_and_keeps_the_text(self):
        closed, text = self.run_actions("""
s = st.openSubmit(s, true);
const key = page().header.submit.panel.box.key;
s = d.escapeBox(d.typeIn(s, key, "Half"), key);
const closed = page().header.submit.panel;
s = st.openSubmit(s, true);""", show="[closed, page().header.submit.panel.box.text]", mode=BATCHED)

        self.assertEqual((closed, text), (None, "Half"))


@unittest.skipUnless(shutil.which("node"), "needs node")
class GoingLiveWithHeldComments(Actions):
    # Two held threads with three comments that wait
    THREADS = [held_thread("a", None, ("comment", "One"), ("comment", "And this")),
               held_thread("b", LINES, ("comment", "Sent"), ("progress", "Finished"), ("reply", "Done that"),
                           ("comment", "Not quite"))]
    HELD = {"mode": "batched", "held": ["a", "b"]}

    def live(self, steps, show, threads=THREADS, mode=HELD):
        return self.run_actions(f'await m.setMode(use, "live");\n{steps}', show, threads=threads, mode=mode)

    def test_what_another_viewer_held_since_the_last_poll_is_asked_about_too(self):
        calls, confirm = self.run_actions(f"""
server = {{ ...server, threads: {json.dumps(self.THREADS)}, mode: {json.dumps(self.HELD)} }};
await m.setMode(use, "live");""", show="[calls, page().confirm?.text]", mode=BATCHED)

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])
        self.assertEqual(confirm, "Send 3 held comments to the agent now?")

    def test_when_what_is_held_cant_be_read_nothing_is_sent(self):
        calls, confirm, problem = self.run_actions(
            'refuse["GET /api/review"] = "no"; await m.setMode(use, "live");',
            show="[calls, page().confirm, page().problem]", mode=BATCHED)

        self.assertEqual((calls, confirm, problem), ([["GET", "/api/review"]], None, "no"))

    def test_it_never_asks_about_fewer_comments_than_there_are_held_threads(self):
        confirm = self.live("", show="page().confirm", threads=[])  # held, but not among the threads read yet

        self.assertEqual(confirm["text"], "Send 2 held comments to the agent now?")

    def test_it_asks_first_with_the_number_of_held_comments_and_sends_nothing(self):
        calls, confirm, modes = self.live("", show="[calls, page().confirm, page().header.modes]")

        self.assertEqual(calls, [])
        self.assertEqual(confirm, {"text": "Send 3 held comments to the agent now?", "yes": "Send and go live", "no": "Cancel"})
        self.assertEqual([m["current"] for m in modes], [False, True])

    def test_with_one_it_says_one_comment(self):
        confirm = self.live("", show="page().confirm", threads=[held_thread("a", None, ("comment", "One"))],
                            mode={"mode": "batched", "held": ["a"]})

        self.assertEqual(confirm["text"], "Send 1 held comment to the agent now?")

    def test_yes_changes_to_live_which_sends_them(self):
        calls, current, confirm = self.live(
            "await m.confirmLive(use);", show="[calls, page().header.modes.map((m) => m.current), page().confirm]")

        self.assertEqual(calls, [["GET", "/api/review"], ["PUT", "/api/mode", {"mode": "live"}], "refresh"])
        self.assertEqual((current, confirm), ([True, False], None))

    def test_a_second_yes_sends_nothing_more(self):
        calls = self.live("await Promise.all([m.confirmLive(use), m.confirmLive(use)]);", show="calls")

        self.assertEqual(calls.count(["PUT", "/api/mode", {"mode": "live"}]), 1)

    def test_cancel_keeps_the_review_batched_and_sends_nothing(self):
        calls, current, count, confirm = self.live(
            "s = st.closeAskLive(s); await m.confirmLive(use);",
            show="[calls, page().header.modes.map((m) => m.current), page().header.submit.count, page().confirm]")

        self.assertEqual(calls, [])
        self.assertEqual((current, count, confirm), ([False, True], 2, None))

    def test_a_poll_keeps_the_question_with_the_number_held_now(self):
        confirm = self.live('server = { ...server, mode: { mode: "batched", held: ["a"] } }; await use.refresh();',
                            show="page().confirm")

        self.assertEqual(confirm["text"], "Send 2 held comments to the agent now?")

    def test_the_question_goes_once_there_is_nothing_left_for_it_to_ask(self):
        other = answers(mode=self.HELD, threads=self.THREADS)
        other["review"] = dict(other["review"], id="other-12345678", branch="other")

        gone = [self.live(f"{poll} await use.refresh();", show="page().confirm") for poll in (
            'server = { ...server, mode: { mode: "batched", held: [] } };',  # submitted in another viewer
            'server = { ...server, mode: { mode: "live", held: [] } };',
            f"server = {json.dumps(other)};")]  # a checkout

        self.assertEqual(gone, [None, None, None])

    def test_after_a_checkout_that_no_poll_saw_yes_changes_nothing(self):
        calls, problem = self.live('onBranch = "other-12345678"; await m.confirmLive(use);', show="[calls, page().problem]")

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])
        self.assertEqual(problem, "Another branch is checked out now: nothing was changed.")


@unittest.skipUnless(shutil.which("node"), "needs node")
class SubmittingTheReview(Actions):
    HELD = {"mode": "batched", "held": ["a", "b"]}
    SUMMARY = ["POST", "/api/threads", {"anchor": None, "body": "Overall: good", "view": "HEAD"}]
    OPEN = "s = st.openSubmit(s, true); const key = page().header.submit.panel.box.key;"

    def submit(self, steps, show, mode=HELD):
        return self.run_actions(f"{self.OPEN}\n{steps}", show, mode=mode)

    def test_the_summary_is_posted_as_a_general_thread_then_the_held_threads_are_submitted(self):
        calls, submit, notice, typed = self.submit(
            's = d.typeIn(s, key, " Overall: good "); await m.submitReview(use);',
            show="[calls, page().header.submit, page().notice, d.boxOf(s, key).text]")

        self.assertEqual(calls, [["GET", "/api/review"], self.SUMMARY, ["POST", "/api/submit", {}], "refresh"])
        self.assertEqual(submit, {"text": "Submit review", "count": 0, "off": "", "panel": None})
        self.assertEqual(notice, "Submitted 3 held threads to the coding agent.")
        self.assertEqual(typed, "")

    def test_without_a_summary_only_the_submit_is_sent(self):
        calls = self.submit("await m.submitReview(use);", show="calls")

        self.assertEqual(calls, [["GET", "/api/review"], ["POST", "/api/submit", {}], "refresh"])

    def test_the_summary_boxes_send_which_ctrl_enter_presses_submits_the_review(self):
        calls = self.submit('s = d.typeIn(s, key, "Overall: good"); await m.send(use, key);', show="calls")

        self.assertEqual(calls[1:3], [self.SUMMARY, ["POST", "/api/submit", {}]])

    def test_with_nothing_held_and_no_summary_nothing_is_sent_and_the_panel_says_why(self):
        calls, error = self.submit("await m.submitReview(use);",
                                   show="[calls, page().header.submit.panel.box.error]", mode=BATCHED)

        self.assertEqual(calls, [])
        self.assertEqual(error, "There is nothing to submit: no comment is held and the summary is empty.")

    def test_a_refused_summary_submits_nothing_and_keeps_its_text(self):
        calls, box = self.submit(
            'refuse["POST /api/threads"] = "no"; s = d.typeIn(s, key, "Overall: good"); await m.submitReview(use);',
            show="[calls, page().header.submit.panel.box]")

        self.assertEqual(calls, [["GET", "/api/review"], self.SUMMARY])
        self.assertEqual((box["text"], box["error"], box["sending"]), ("Overall: good", "no", False))

    def test_when_the_submit_fails_after_the_summary_pressing_again_does_not_post_it_twice(self):
        calls, error, closed = self.submit("""
refuse["POST /api/submit"] = "no"; s = d.typeIn(s, key, "Overall: good"); await m.submitReview(use);
const error = page().header.submit.panel.box.error;
delete refuse["POST /api/submit"]; calls.length = 0; await m.submitReview(use);""",
                                           show="[calls, error, page().header.submit.panel]")

        self.assertEqual(calls, [["GET", "/api/review"], ["POST", "/api/submit", {}], "refresh"])
        self.assertEqual(error, "Your summary is posted, but the review isn't submitted: no")
        self.assertIsNone(closed)

    def test_a_failure_after_the_panel_was_closed_is_said_on_the_page(self):
        open_still, closed = [self.submit(f"""
refuse["POST /api/submit"] = "no"; s = d.typeIn(s, key, "Overall: good");
const sending = m.submitReview(use); {close}
await sending;""", show="page().problem") for close in ("", "s = st.openSubmit(s, false);")]

        self.assertEqual(open_still, "", "the panel says why")
        self.assertEqual(closed, "Your summary is posted, but the review isn't submitted: no")

    def test_a_second_press_while_it_is_being_sent_sends_nothing(self):
        calls = self.submit('await Promise.all([m.submitReview(use), m.submitReview(use)]);', show="calls")

        self.assertEqual(calls.count(["POST", "/api/submit", {}]), 1)

    def test_after_a_checkout_nothing_is_sent_and_the_summary_waits_for_its_branch(self):
        calls, text, problem = self.submit(
            's = d.typeIn(s, key, "Overall: good"); onBranch = "other-12345678"; await m.submitReview(use);',
            show="[calls, d.boxOf(s, key).text, page().problem]")

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])
        self.assertEqual((text, problem), ("Overall: good",
                                           "Another branch is checked out now: the draft waits for its own branch."))


@unittest.skipUnless(shutil.which("node"), "needs node")
class MarkingTheReviewDone(Actions):
    SHOW = "[calls, page().header.state, page().header.doneButton]"

    def test_a_review_that_isnt_done_reads_in_review_and_can_be_marked(self):
        _, state, button = self.run_actions("", show=self.SHOW, done=UNDONE)

        self.assertEqual((state, button["text"], button["mark"]), ("In review", "Mark as Done", True))
        self.assertIn("gates nothing", button["title"])

    def test_mark_as_done_puts_it_through_the_existing_call_and_the_header_reads_done(self):
        calls, state, button = self.run_actions("await m.setDone(use, true);", show=self.SHOW, done=UNDONE)

        self.assertEqual(calls, [["GET", "/api/review"], ["PUT", "/api/done", {"done": True}], "refresh"])
        self.assertEqual((state, button["text"], button["mark"]), ("Done", "Undo Done", False))

    def test_undo_puts_it_back_in_review(self):
        calls, state, button = self.run_actions("await m.setDone(use, false);", show=self.SHOW, done=DONE)

        self.assertEqual(calls[1], ["PUT", "/api/done", {"done": False}])
        self.assertEqual((state, button["text"]), ("In review", "Mark as Done"))

    def test_a_refused_mark_says_why_and_the_review_stays_in_review(self):
        problem, state = self.run_actions(
            'refuse["PUT /api/done"] = "another branch is checked out"; await m.setDone(use, true);',
            show="[page().problem, page().header.state]", done=UNDONE)

        self.assertEqual((problem, state), ("another branch is checked out", "In review"))

    def test_after_a_checkout_the_other_branchs_review_isnt_marked(self):
        calls = self.run_actions('onBranch = "other-12345678"; await m.setDone(use, true);', show="calls", done=UNDONE)

        self.assertEqual(calls, [["GET", "/api/review"], "refresh"])

    def test_beside_done_the_header_says_what_is_still_open_and_running_done_or_not(self):
        said = [self.run_actions("", show="page().header.stillOpen", done=dict(was, openThreads=threads, runsInFlight=runs))
                for was, threads, runs in ((UNDONE, 2, 1), (DONE, 1, 0), (UNDONE, 0, 3), (UNDONE, 0, 0))]

        self.assertEqual(said, ["2 threads still open · 1 run still working", "1 thread still open",
                                "3 runs still working", ""])


if __name__ == "__main__":
    unittest.main()
