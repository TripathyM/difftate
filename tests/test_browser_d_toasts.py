"""Layout D's toasts (#281): the one pinned place for what the page tells the reviewer, as the
page's model has them (web/d/toasts.js). Node runs it, with API answers shaped like the released
transcript's."""
import json
import shutil
import unittest

from browser_d import answers, run_js

BATCHED = {"mode": "batched", "held": []}
OPENED = "Opened on Files changed: no open thread is replied or failed."


@unittest.skipUnless(shutil.which("node"), "needs node")
class Toasts(unittest.TestCase):
    def toasts(self, steps="", show="toasts()", poll=None, address=None):
        """[[id, kind, text]] of the page's toasts, opened at an address naming the tab <address>,
        after a poll answering <poll>, then <steps>."""
        return run_js("page", f"""
import * as st from "{{STATE}}";
import * as a from "{{ACTIONS}}";
import {{ ApiError }} from "{{API}}";
const mode = {json.dumps(BATCHED)}, review = {json.dumps(answers()["review"])};
// What a change gets: "<METHOD path>" in refuse is refused with that reason
const refuse = {{}};
const api = async (method, path) => {{
  const call = `${{method}} ${{path.split("?")[0]}}`;
  if (refuse[call]) throw new ApiError(409, refuse[call]);
  return {{ "GET /api/review": review, "PUT /api/mode": {{ ...mode, submitted: [] }}, "GET /api/export": "# Review export" }}[call] ?? {{}};
}};
const use = {{ api, state: () => s, update: (change) => {{ s = change(s); }}, refresh: async () => {{}}, copy: async () => {{}} }};
let s = st.polled(st.initialState({json.dumps(address)}), {json.dumps(poll or answers(threads=[]))});
const toasts = () => m.pageModel(s).toasts.map((t) => [t.id, t.kind, t.text]);
{steps}
console.log(JSON.stringify({show}));""")

    def test_why_the_review_opened_on_its_tab_is_an_info_toast(self):
        self.assertEqual(self.toasts(), [["why", "info", OPENED]])

    def test_what_a_change_did_is_an_info_toast(self):
        # The Files changed tab the address names says nothing of itself
        exported = self.toasts("await a.exportReview(use);", address="files")
        switched = self.toasts('await a.setMode(use, "batched");', address="files")

        self.assertEqual(exported, [["notice", "info", "Export copied: paste it into an agent session."]])
        self.assertEqual(switched, [["notice", "info", "Batched: comments are held until you submit the review."]])

    def test_a_refused_change_and_a_failed_poll_are_error_toasts(self):
        refused = self.toasts('refuse["PUT /api/mode"] = "no such mode"; await a.setMode(use, "batched");', address="files")
        failed = self.toasts('s = st.pollFailed(s, "Can\'t reach the watcher");', address="files")

        self.assertEqual(refused, [["refused", "error", "no such mode"]])
        self.assertEqual(failed, [["problem", "error", "Can't reach the watcher"]])

    def test_a_closed_toast_goes(self):
        self.assertEqual(self.toasts('s = st.closeToast(s, "why");'), [])
        self.assertEqual(self.toasts('s = st.closeToast(st.noted(s, "Export copied"), "notice");', address="files"), [])
        self.assertEqual(self.toasts('s = st.closeToast(st.refused(s, "no such mode"), "refused");', address="files"), [])
        self.assertEqual(self.toasts('s = st.closeToast(st.pollFailed(s, "gone"), "problem");', address="files"), [])

    def test_a_closed_poll_error_stays_closed_while_the_polls_fail_the_same_way(self):
        again, otherwise, after_a_good_poll = self.toasts("""
s = st.closeToast(st.pollFailed(s, "Can't reach the watcher"), "problem");
s = st.pollFailed(s, "Can't reach the watcher");
const again = toasts();
const otherwise = (s = st.pollFailed(s, "This page's watcher has stopped"), toasts());
s = st.closeToast(s, "problem");
s = st.polled(s, s.server);
s = st.pollFailed(s, "This page's watcher has stopped");""", show="[again, otherwise, toasts()]", address="files")

        self.assertEqual(again, [])
        self.assertEqual(otherwise, [["problem", "error", "This page's watcher has stopped"]])
        self.assertEqual(after_a_good_poll, [["problem", "error", "This page's watcher has stopped"]])

    def test_a_refusal_stays_on_its_tab_until_closed_covering_nothing_on_the_other(self):
        there, other, back = self.toasts("""
s = st.refused(s, "No commit named x");
const there = toasts();
const other = (s = st.showTab(s, "conversation"), toasts());
s = st.polled(st.showTab(s, "files"), s.server);""", show="[there, other, toasts()]", address="files")

        self.assertEqual((there, other, back), ([["refused", "error", "No commit named x"]], [],
                                                [["refused", "error", "No commit named x"]]))

    def test_the_same_refusal_on_the_other_tab_is_shown_there(self):
        said = self.toasts("""
s = st.showTab(st.refused(s, "no"), "conversation");
s = st.refused(s, "no");""", address="files")

        self.assertEqual(said, [["refused", "error", "no"]])

    def test_a_watcher_that_stopped_is_said_on_whichever_tab_is_shown(self):
        said = self.toasts('s = st.showTab(st.pollFailed(s, "gone"), "conversation");', address="files")

        self.assertEqual(said, [["problem", "error", "gone"]])

    def test_a_change_refused_for_the_polls_reason_is_one_toast_which_closes_for_both(self):
        both, closed = self.toasts("""
s = st.refused(st.pollFailed(s, "gone"), "gone");
const both = toasts();
s = st.closeToast(s, both[0][0]);""", show="[both, toasts()]", address="files")

        self.assertEqual(both, [["refused", "error", "gone"]])
        self.assertEqual(closed, [])

    def timed(self, steps):
        """What happens as the toasts shown change: <steps> calls shown([[id, kind, text]]) and
        pass(ms); gives [[ms, id]] for each toast whose time was up."""
        return run_js("toasts", f"""
let now = 0;
const timers = new Map(), up = [];
let last = 0;
const clock = {{ set: (does, ms) => {{ timers.set(++last, {{ does, at: now + ms }}); return last; }}, clear: (timer) => timers.delete(timer) }};
const show = m.toastTimes(clock, (id) => up.push([now, id]));
const shown = (list) => show(list.map(([id, kind, text]) => ({{ id, kind, text }})));
function pass(ms) {{
  for (const end = now + ms; now < end;) {{
    now += 1000;
    for (const [id, t] of [...timers]) if (t.at <= now) {{ timers.delete(id); t.does(); }}
  }}
}}
{steps}
console.log(JSON.stringify(up));""")

    def test_an_info_toast_goes_after_8_seconds_however_often_the_page_is_drawn(self):
        up = self.timed("""
const toast = [["notice", "info", "Export copied"]];
shown(toast); pass(5000); shown(toast); pass(10000);""")

        self.assertEqual(up, [[8000, "notice"]])

    def test_an_error_toast_never_goes_by_itself(self):
        self.assertEqual(self.timed('shown([["refused", "error", "no"]]); pass(600000);'), [])

    def test_a_toast_saying_something_new_has_its_full_time(self):
        up = self.timed("""
shown([["notice", "info", "Batched"]]); pass(5000);
shown([["notice", "info", "Live"]]); pass(20000);""")

        self.assertEqual(up, [[13000, "notice"]])

    def test_a_toast_that_went_and_came_back_starts_again_and_one_that_went_has_no_time_left(self):
        up = self.timed("""
const toast = [["notice", "info", "Export copied"]];
shown(toast); pass(5000); shown([]); pass(5000); shown(toast); pass(20000);
shown([]); shown([["why", "info", "Opened"]]); shown([]); pass(20000);""")

        self.assertEqual(up, [[18000, "notice"]])


if __name__ == "__main__":
    unittest.main()
