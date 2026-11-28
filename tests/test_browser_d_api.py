"""Layout D's calls to the review API (#257): signed in by the launch link (the cookie, with the
page's header, naming the folder), what it says when a call fails (web/d/api.js), and marking a
file viewed through the existing call (web/d/actions.js). Node runs it with a fake fetch."""
import json
import shutil
import unittest

from browser_d import answers, run_js

# A fake fetch: it keeps each request, and answers with `reply`
FAKE_FETCH = """
const sent = [];
let reply = { status: 200, body: {} };
const fetch = async (url, options) => {
  sent.push([url, options]);
  return { ok: reply.status < 400, status: reply.status, text: async () => JSON.stringify(reply.body) };
};"""

# The page's state and a fake review API, for an action: `marks` is what the watcher has viewed
PAGE = """
import * as st from "{STATE}";
const calls = [];
let marks = [], refusal = null;
let s = st.polled(st.initialState(), FIRST);
const use = {
  api: async (method, path, payload) => {
    calls.push([method, path, payload]);
    if (refusal) throw refusal;
    marks = payload.viewed ? [...marks, payload.file] : marks.filter((f) => f !== payload.file);
    return { files: marks };
  },
  update: (change) => { s = change(s); },
  refresh: async () => { calls.push("refresh"); },
};"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheCalls(unittest.TestCase):
    def test_a_call_names_the_pages_folder_and_signs_in_with_the_cookie_and_the_pages_header(self):
        sent = run_js("api", f"""
{FAKE_FETCH}
const api = m.reviewApi(fetch, "/home/me/my repo");
await api("GET", "/api/review");
await api("PUT", "/api/viewed?x=1", {{ file: "a.py", viewed: true }});
console.log(JSON.stringify(sent));""")

        self.assertEqual(sent[0], ["/api/review?folder=%2Fhome%2Fme%2Fmy%20repo",
                                   {"method": "GET", "credentials": "same-origin", "headers": {"X-Difftate": "page"}}])
        self.assertEqual(sent[1][0], "/api/viewed?x=1&folder=%2Fhome%2Fme%2Fmy%20repo")
        self.assertEqual((sent[1][1]["headers"]["Content-Type"], json.loads(sent[1][1]["body"])),
                         ("application/json", {"file": "a.py", "viewed": True}))

    def test_a_failed_call_says_why_in_words_for_the_reviewer(self):
        said = run_js("api", f"""
{FAKE_FETCH}
const api = m.reviewApi(fetch, "/repo");
const why = async (status, body) => {{
  reply = {{ status, body }};
  try {{ await api("GET", "/api/review"); }} catch (e) {{ return m.problemText(e); }}
}};
console.log(JSON.stringify([await why(401, {{ error: "missing or wrong token" }}), await why(409, {{ error: "another branch" }}),
  m.problemText(new TypeError("fetch failed"))]));""")

        self.assertEqual(said, ["This page's watcher has stopped. Open the link a running difftate prints.",
                                "another branch",
                                "Can't reach the watcher: is difftate still running in this repository?"])


@unittest.skipUnless(shutil.which("node"), "needs node")
class MarkingAFileViewed(unittest.TestCase):
    def run_action(self, steps, show):
        return run_js("actions", f"""
{PAGE.replace("FIRST", json.dumps(answers()))}
{steps}
console.log(JSON.stringify({show}));""")

    def test_it_calls_the_viewed_call_folds_the_file_and_polls_again(self):
        got = self.run_action('const took = await m.markViewed(use, "app.py", true);',
                              show="[took, calls, s.server.viewed, st.isFolded(s, 'app.py')]")

        self.assertEqual(got, [True, [["PUT", "/api/viewed", {"file": "app.py", "viewed": True}], "refresh"],
                               ["app.py"], True])

    def test_a_refused_mark_changes_nothing_and_says_why_until_a_change_is_taken(self):
        got = self.run_action("""
import { ApiError } from "{API}";
refusal = new ApiError(409, "another branch is checked out");
const took = await m.markViewed(use, "app.py", true);
const refused = [took, s.server.viewed, st.isFolded(s, "app.py"), s.refused, calls.length];
refusal = null;
await m.markViewed(use, "app.py", true);""", show="[...refused, s.refused]")

        self.assertEqual(got, [False, [], False, "another branch is checked out", 1, ""])


if __name__ == "__main__":
    unittest.main()
