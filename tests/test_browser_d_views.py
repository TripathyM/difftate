"""Layout D's views (#263; GLOSSARY.md, View): the view picker with the commit box, and the
call that switches the view the watcher shows (web/d/views.js and actions.js). Node runs it, with
API answers shaped like the released transcript's and a fake review API."""
import json
import shutil
import unittest

from browser_d import answers, changed, released, run_js


def in_view(view, **changes):
    """One poll's answers of a watcher showing <view>."""
    return answers(changeset=dict(answers()["changeset"], view=view), **changes)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheViewPicker(unittest.TestCase):
    def picker(self, view):
        return run_js("page", f"""
import * as st from "{{STATE}}";
const s = st.polled(st.initialState("files"), {json.dumps(in_view(view))});
console.log(JSON.stringify(m.pageModel(s).body.picker));""")

    def test_it_offers_todays_views_with_the_one_shown_current_and_on_its_button(self):
        picker = self.picker("staged")

        self.assertEqual([(c["view"], c["text"]) for c in picker["choices"]], [
            ("", "All changes"), ("HEAD", "Uncommitted"), ("staged", "Staged"), ("unstaged", "Unstaged"),
            ("HEAD~1", "Last commit"), ("HEAD~2", "Last 2 commits"), ("HEAD~3", "Last 3 commits")])
        self.assertEqual([c["view"] for c in picker["choices"] if c["current"]], ["staged"])
        self.assertEqual(picker["text"], "Staged")

    def test_a_view_from_the_commit_box_is_offered_too_while_it_is_shown(self):
        picker = self.picker("abc1234")

        self.assertEqual(picker["choices"][-1], {"view": "abc1234", "text": "Commits after abc1234", "current": True})
        self.assertEqual(picker["text"], "Commits after abc1234")

    def test_the_pages_title_names_a_view_that_shows_part_of_the_review(self):
        titles = run_js("page", f"""
import * as st from "{{STATE}}";
console.log(JSON.stringify({json.dumps([in_view(""), in_view("HEAD~2")])}
  .map((poll) => m.pageModel(st.polled(st.initialState("files"), poll)).title)));""")

        self.assertEqual(titles, ["difftate · feature", "difftate · feature · the commits after HEAD~2"])


@unittest.skipUnless(shutil.which("node"), "needs node")
class SwitchingTheView(unittest.TestCase):
    def run_actions(self, steps, show, **poll):
        """<show> after the JS lines <steps> on a page whose poll answered <poll>. The fake review
        API shows the view it was put to, and answers each view's calls from `inView`."""
        return run_js("actions", f"""
import * as st from "{{STATE}}";
import * as d from "{{DRAFTS}}";
import {{ pageModel }} from "{{PAGE}}";
import {{ readReview, newestOnly }} from "{{POLL}}";
const first = {json.dumps(in_view("", **poll))};
const inView = {{
  "": {{ diff: first.changeset.diff, threads: first.threads, path: {{ stops: [], skipped: [], not_on_the_path: ["app.py"], sections: [] }} }},
  staged: {{ diff: {json.dumps(changed("staged.py"))}, threads: [], path: {{ stops: [], skipped: [], not_on_the_path: ["staged.py"], sections: [] }} }},
}};
const calls = [], refuse = {{}};
let view = "";
const api = async (method, path, payload) => {{
  calls.push(payload === undefined ? `${{method}} ${{path}}` : [method, path, payload]);
  const why = refuse[`${{method}} ${{path.split("?")[0]}}`];
  if (why) {{ const {{ ApiError }} = await import("{{API}}"); throw new ApiError(400, why); }}
  if (method === "PUT" && path === "/api/view") return {{ view: (view = payload.view) }};
  const route = path.split("?")[0];
  if (route === "/api/changeset") return {{ ...first.changeset, view, diff: inView[view].diff }};
  if (route === "/api/threads") return inView[view].threads;
  if (route === "/api/review-path") return {{ path: inView[view].path }};
  return {{ "/api/review": first.review, "/api/mode": first.mode, "/api/agent": first.agent, "/api/done": first.done,
    "/api/viewed": {{ files: [] }} }}[route];
}};
let s = st.polled(st.initialState("files"), first);
const update = (change) => {{ s = change(s); }};
const refresh = newestOnly(() => readReview(api, s.server), (a) => update((now) => st.polled(now, a)), (e) => {{ throw e; }});
const use = {{ api, state: () => s, update, refresh }};
const page = () => pageModel(s);
{steps}
console.log(JSON.stringify({show}));""")

    def test_it_puts_the_view_then_reads_its_changeset_threads_and_review_path(self):
        took, calls, files, tree, threads = self.run_actions(
            'const took = await m.setView(use, "staged");',
            show="[took, calls, page().body.files.map((f) => f.path), page().body.tree.map((r) => r.path ?? r.name), "
                 "s.server.threads]")

        self.assertTrue(took)
        self.assertEqual(calls[0], ["PUT", "/api/view", {"view": "staged"}])
        for call in ("GET /api/changeset", "GET /api/threads?view=staged", "GET /api/review-path?view=staged"):
            self.assertIn(call, calls)
        self.assertEqual(files, ["staged.py"])
        self.assertIn("staged.py", tree)
        self.assertEqual(threads, [])

    def test_the_view_the_page_still_shows_is_put_too_as_another_may_be_on_its_way(self):
        watcher, shown = self.run_actions("""
const slow = m.setView(use, "staged"), back = m.setView(use, "");
await Promise.all([slow, back]);""", show='[view, page().body.picker.text]')

        self.assertEqual((watcher, shown), ("", "All changes"))

    def test_a_view_that_is_not_one_changes_nothing_and_says_why(self):
        why = released("PUT", "/api/view", bool)  # the transcript's first answer that took
        self.assertEqual(why, {"view": "HEAD"})

        took, shown, problem = self.run_actions(
            'refuse["PUT /api/view"] = "no view \'nope\'"; const took = await m.setView(use, "nope");',
            show="[took, page().body.picker.text, page().problem]")

        self.assertEqual((took, shown, problem), (False, "All changes", "no view 'nope'"))

    def test_a_review_path_call_that_fails_never_keeps_another_views_path(self):
        path = self.run_actions("""
await refresh();
refuse["GET /api/review-path"] = "git could not be read";
await m.setView(use, "staged");""", show="s.server.reviewPath")

        self.assertIsNone(path)

    def test_a_pick_of_lines_and_an_empty_draft_end_with_the_view_and_a_written_draft_stays(self):
        drafts, drag, active = self.run_actions("""
s = d.dragEnd(d.dragStart(s, { path: "app.py", side: "new", line: 1 }));
const empty = d.draftsOf(s).length;
await m.setView(use, "staged");
const afterEmpty = d.draftsOf(s).length;
await m.setView(use, "");
s = d.dragEnd(d.dragStart(s, { path: "app.py", side: "new", line: 1 }));
s = d.typeIn(s, s.own.active, "Why?");
s = d.dragStart(s, { path: "app.py", side: "new", line: 1 });
await m.setView(use, "staged");""", show="[[empty, afterEmpty, d.draftsOf(s).map((x) => x.text)], s.own.drag, s.own.active]")

        self.assertEqual(drafts, [1, 0, ["Why?"]])
        self.assertIsNone(drag)
        self.assertIsNone(active)

    def test_show_it_in_its_view_switches_there_and_gives_where_its_lines_are(self):
        thread = elsewhere_thread()
        took, target, offered = self.run_actions("""
inView.staged.threads = [{ ...inView[""].threads[0], inView: true, anchor: { ...inView[""].threads[0].anchor, file: "staged.py", side: "new", startLine: 1, endLine: 1 } }];
const target = await m.showThreadIn(use, "elsewhere", "staged");""",
            show='[s.server.changeset.view, target, pageModel(st.showTab(s, "conversation")).body.threads[0].elsewhere]',
            threads=[thread])

        self.assertEqual(took, "staged")
        self.assertEqual(target, {"file": "staged.py", "row": 2})  # the hunk, the old line, then this one
        self.assertIsNone(offered, "its lines are in the view shown now")


def elsewhere_thread(**changes):
    """A thread of the released transcript written in the staged view, whose code the view shown
    doesn't have."""
    threads = released("GET", "/api/threads", lambda a: any(t["anchor"] for t in a))
    thread = next(t for t in threads if t["anchor"])
    return dict(thread, **dict({"id": "elsewhere", "status": "open", "outdated": False, "inView": False,
                                "anchor": dict(thread["anchor"], file="app.py", view="staged")}, **changes))


@unittest.skipUnless(shutil.which("node"), "needs node")
class AThreadTheViewDoesNotShow(unittest.TestCase):
    def offered(self, thread):
        """What the thread's card offers on the Conversation tab."""
        return run_js("page", f"""
import * as st from "{{STATE}}";
const s = st.polled(st.initialState("conversation"), {json.dumps(in_view("", threads=[thread]))});
console.log(JSON.stringify(m.pageModel(s).body.threads[0].elsewhere));""")

    def test_it_offers_the_view_it_was_written_in(self):
        self.assertEqual(self.offered(elsewhere_thread()), {"view": "staged", "text": "Show it in staged changes"})

    def test_an_outdated_thread_and_one_written_in_the_view_shown_offer_none(self):
        outdated = elsewhere_thread(outdated=True)
        here = elsewhere_thread()
        here["anchor"] = dict(here["anchor"], view="")
        general = elsewhere_thread(anchor=None)

        self.assertEqual([self.offered(t) for t in (outdated, here, general)], [None, None, None])


if __name__ == "__main__":
    unittest.main()
