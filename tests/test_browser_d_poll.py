"""How layout D reads the review (#257): the calls of a poll, which are today's viewer's, and that
only the newest poll counts (web/d/poll.js). Node runs it with a fake review API."""
import json
import shutil
import unittest

from browser_d import answers, run_js

# A fake of the page's api(method, path): it keeps the calls, and fails the paths in `broken`
FAKE_API = """
const calls = [], broken = new Set();
const api = async (method, path) => {
  calls.push(`${method} ${path}`);
  const route = path.split("?")[0];
  if (broken.has(route)) throw new Error(`${route} is broken`);
  return structuredClone(served[route]);
};"""


@unittest.skipUnless(shutil.which("node"), "needs node")
class ThePoll(unittest.TestCase):
    def read(self, view="", broken=(), last=None):
        """(the calls, the answers) of one poll of a watcher showing <view>."""
        poll = answers()
        served = {"/api/review": poll["review"], "/api/mode": poll["mode"], "/api/agent": poll["agent"],
                  "/api/changeset": dict(poll["changeset"], view=view), "/api/threads": poll["threads"],
                  "/api/viewed": {"files": ["app.py"]}, "/api/review-path": {"path": {"stops": []}},
                  "/api/done": poll["done"]}
        return run_js("poll", f"""
const served = {json.dumps(served)};
{FAKE_API}
for (const route of {json.dumps(list(broken))}) broken.add(route);
const got = await m.readReview(api, {json.dumps(last)});
console.log(JSON.stringify([calls, got]));""")

    def test_a_poll_makes_todays_viewers_calls_with_the_view_the_watcher_shows(self):
        calls, got = self.read(view="HEAD~2")

        self.assertEqual(calls[0], "GET /api/review", "first: the watcher follows the checked-out branch")
        self.assertEqual(sorted(calls[1:]), [
            "GET /api/agent", "GET /api/changeset", "GET /api/done", "GET /api/mode",
            "GET /api/review-path?view=HEAD~2", "GET /api/threads?view=HEAD~2", "GET /api/viewed"])
        self.assertEqual((got["viewed"], got["reviewPath"], got["changeset"]["view"]),
                         (["app.py"], {"stops": []}, "HEAD~2"))
        self.assertEqual(sorted(got), sorted(answers()))

    def test_an_unreadable_agent_list_and_a_failed_review_path_call_do_not_fail_the_poll(self):
        last = answers(reviewPath={"stops": ["the one shown"]})

        _, got = self.read(broken=["/api/agent", "/api/review-path"], last=last)

        self.assertEqual((got["agent"], got["reviewPath"]), (None, {"stops": ["the one shown"]}))

    def test_a_poll_that_a_newer_one_overtook_changes_nothing_nor_does_its_failure(self):
        got = run_js("poll", """
const waiting = [], seen = [];
const refresh = m.newestOnly(() => new Promise((resolve, reject) => waiting.push({ resolve, reject })),
  (a) => seen.push(a), (e) => seen.push(`failed: ${e.message}`));
const slow = refresh(), fails = refresh(), newest = refresh();
waiting[2].resolve("newest");
waiting[0].resolve("slow");
waiting[1].reject(new Error("old"));
await Promise.all([slow, fails, newest]);
const last = refresh();
waiting[3].reject(new Error("now"));
await last;
console.log(JSON.stringify(seen));""")

        self.assertEqual(got, ["newest", "failed: now"])


    def test_an_overtaken_refresh_ends_only_once_the_newer_news_is_on_the_page(self):
        # What awaits it (showing a thread in the view just picked) reads the page next
        got = run_js("poll", """
const waiting = [], seen = [];
const refresh = m.newestOnly(() => new Promise((resolve) => waiting.push(resolve)), (a) => seen.push(a), () => {});
let sawAtEnd = null;
const mine = refresh().then(() => { sawAtEnd = [...seen]; });
refresh(); // the poll's, started while mine reads
waiting[0]("overtaken");
await new Promise((r) => setTimeout(r, 5));
const early = sawAtEnd;
waiting[1]("newest");
await mine;
console.log(JSON.stringify([early, sawAtEnd]));""")

        self.assertEqual(got, [None, ["newest"]])

    def test_a_failed_review_path_call_never_keeps_another_reviews_path(self):
        last = answers(reviewPath={"stops": ["the other branch's"]})
        last["review"] = dict(last["review"], id="other-12345678")

        _, got = self.read(broken=["/api/review-path"], last=last)

        self.assertIsNone(got["reviewPath"])


if __name__ == "__main__":
    unittest.main()
