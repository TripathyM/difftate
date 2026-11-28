"""Layout D's export (#263; GLOSSARY.md, Export), in the header's overflow menu: the call, the
copy to the clipboard, and what the page says (web/d/actions.js and api.js). Node runs it, with the
released transcript's answers and a fake fetch and clipboard."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js

EXPORT = released("GET", "/api/export")


@unittest.skipUnless(shutil.which("node"), "needs node")
class Exporting(unittest.TestCase):
    def export(self, reply=None, copies=True, on_branch=None):
        """(whether it was taken, the URLs asked for, what was copied, the page's notice and
        problem) after an export of a review whose folder is /home/me/my repo, with the API
        answering <reply> and a clipboard that <copies>, or refuses."""
        reply = reply or {"status": 200, "type": "text/plain; charset=utf-8", "text": EXPORT}
        poll = answers()
        poll["review"] = dict(poll["review"], folder="/home/me/my repo")
        return run_js("actions", f"""
import * as st from "{{STATE}}";
import {{ pageModel }} from "{{PAGE}}";
import {{ reviewApi }} from "{{API}}";
const reply = {json.dumps(reply)}, asked = [], copied = [];
const api = reviewApi(async (url) => {{
  if (url.startsWith("/api/review?")) {{
    const review = {{ id: {json.dumps(on_branch or poll["review"]["id"])} }};
    return {{ ok: true, status: 200, headers: new Headers({{ "Content-Type": "application/json" }}), text: async () => JSON.stringify(review) }};
  }}
  asked.push(url);
  return {{ ok: reply.status < 400, status: reply.status, headers: new Headers({{ "Content-Type": reply.type }}), text: async () => reply.text }};
}}, "/home/me/my repo");
let s = st.polled(st.initialState("files"), {json.dumps(poll)});
const use = {{
  api, state: () => s, update: (change) => {{ s = change(s); }}, refresh: async () => {{}},
  copy: async (text) => {{ {'copied.push(text);' if copies else 'throw new Error("the browser refused to copy");'} }},
}};
const took = await m.exportReview(use);
console.log(JSON.stringify([took, asked, copied, noticeOf(pageModel(s)), problemOf(pageModel(s))]));""")

    def test_it_copies_the_export_whose_reply_command_names_the_reviews_folder(self):
        took, asked, copied, notice, problem = self.export()

        self.assertEqual(asked, ["/api/export?reply_folder=%2Fhome%2Fme%2Fmy%20repo&folder=%2Fhome%2Fme%2Fmy%20repo"])
        self.assertTrue(copied[0].startswith("# Review export"))
        self.assertEqual(copied, [EXPORT], "the whole text, as it came")
        self.assertEqual((took, notice, problem), (True, "Export copied: paste it into an agent session.", ""))

    def test_after_a_checkout_the_other_branchs_review_is_not_copied_for_this_one(self):
        took, asked, copied, notice, problem = self.export(on_branch="other-12345678")

        self.assertEqual((took, asked, copied, notice), (False, [], [], ""))
        self.assertEqual(problem, "Could not export: another branch is checked out now.")

    def test_a_refused_export_copies_nothing_and_says_why(self):
        took, _, copied, notice, problem = self.export(
            {"status": 502, "type": "application/json", "text": json.dumps({"error": "git could not be read"})})

        self.assertEqual((took, copied, notice, problem), (False, [], "", "Could not export: git could not be read"))

    def test_an_empty_export_is_not_copied_over_what_the_clipboard_holds(self):
        took, _, copied, _, problem = self.export({"status": 200, "type": "text/plain; charset=utf-8", "text": "  \n"})

        self.assertEqual((took, copied, problem),
                         (False, [], "Could not export: The watcher gave no export (is it up to date?)"))

    def test_a_browser_that_refuses_to_copy_is_said_so(self):
        took, _, _, notice, problem = self.export(copies=False)

        self.assertEqual((took, notice, problem), (False, "", "Could not export: the browser refused to copy"))


if __name__ == "__main__":
    unittest.main()
