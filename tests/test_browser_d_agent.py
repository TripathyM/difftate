"""Layout D's coding agent choice (#263; GLOSSARY.md, Agent override), in its settings: what the
choice offers (web/d/settings.js, with the page's model) and the call that takes it (actions.js).
Node runs it, with API answers shaped like the released transcript's and a fake review API."""
import json
import shutil
import unittest

from browser_d import answers, released, run_js

# GET /api/agent in the released transcript: the machine's default, and a reviewer's choice
INHERITED = released("GET", "/api/agent", lambda a: a["source"] == "machine")
CHOSEN = released("PUT", "/api/agent", lambda a: a["source"] == "review")


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheAgentChoice(unittest.TestCase):
    def offered(self, agent):
        got = run_js("page", f"""
import * as st from "{{STATE}}";
const s = st.polled(st.initialState("files"), {json.dumps(answers(agent=agent))});
console.log(JSON.stringify(m.pageModel(s).settings.agent));""")
        return [(c["value"], c["text"]) for c in got["choices"]], got["value"], got["disabled"]

    def test_with_no_choice_of_its_own_the_first_entry_names_the_agent_that_replies_and_why(self):
        self.assertEqual(self.offered(INHERITED), (
            [("", "Default (personal, machine)"), ("personal", "personal"), ("work", "work")], "", False))

    def test_a_reviews_own_choice_is_the_value_and_the_first_entry_clears_it(self):
        self.assertEqual(self.offered(CHOSEN),
                         ([("", "Default"), ("personal", "personal"), ("work", "work")], "work", False))

    def test_a_chosen_agent_that_left_the_list_is_still_shown(self):
        choices, value, _ = self.offered(dict(CHOSEN, agent="gone"))

        self.assertEqual((choices[-1], value), (("gone", "gone"), "gone"))

    def test_an_agent_list_that_cannot_be_read_offers_no_choice(self):
        self.assertEqual(self.offered(None), ([("", "agent list not readable")], "", True))


@unittest.skipUnless(shutil.which("node"), "needs node")
class ChoosingAnAgent(unittest.TestCase):
    def run_actions(self, steps, show, agent=INHERITED):
        return run_js("actions", f"""
import * as st from "{{STATE}}";
import {{ pageModel }} from "{{PAGE}}";
const first = {json.dumps(answers(agent=agent))};
const calls = [], refuse = {{}};
let onBranch = first.review.id, server = first;
let s = st.polled(st.initialState("files"), first);
const use = {{
  api: async (method, path, payload) => {{
    calls.push(payload === undefined ? [method, path] : [method, path, payload]);
    const why = refuse[`${{method}} ${{path}}`];
    if (why) {{ const {{ ApiError }} = await import("{{API}}"); throw new ApiError(400, why); }}
    if (path === "/api/review") return {{ id: onBranch }};
    const answer = payload.agent ? {json.dumps(CHOSEN)} : {json.dumps(INHERITED)};
    server = {{ ...server, agent: answer }};
    return answer;
  }},
  state: () => s, update: (change) => {{ s = change(s); }},
  refresh: async () => {{ calls.push("refresh"); s = st.polled(s, server); }},
}};
const page = () => pageModel(s);
{steps}
console.log(JSON.stringify({show}));""")

    def test_it_puts_the_name_and_says_it_replies_from_the_next_run(self):
        took, calls, value, notice = self.run_actions(
            'const took = await m.setAgent(use, "work");', show="[took, calls, page().settings.agent.value, page().notice]")

        self.assertTrue(took)
        self.assertEqual(calls, [["GET", "/api/review"], ["PUT", "/api/agent", {"agent": "work"}], "refresh"])
        self.assertEqual((value, notice), ("work", "work replies in this review, from the next run."))

    def test_default_clears_the_reviews_choice(self):
        calls, notice = self.run_actions('await m.setAgent(use, "");', show="[calls, page().notice]", agent=CHOSEN)

        self.assertEqual(calls[1], ["PUT", "/api/agent", {"agent": None}])
        self.assertEqual(notice, "This review's agent override is cleared: personal (machine) replies, from the next run.")

    def test_picking_what_is_chosen_asks_nothing(self):
        self.assertEqual(self.run_actions('const took = await m.setAgent(use, "");', show="[took, calls]"), [True, []])

    def test_a_refused_choice_leaves_the_review_as_it_was_and_says_why(self):
        took, value, problem = self.run_actions(
            'refuse["PUT /api/agent"] = "no agent \'work\' in the agent list"; const took = await m.setAgent(use, "work");',
            show="[took, page().settings.agent.value, page().problem]")

        self.assertEqual((took, value, problem), (False, "", "no agent 'work' in the agent list"))

    def test_after_a_checkout_nothing_is_chosen_for_the_other_branchs_review(self):
        took, calls = self.run_actions(
            'onBranch = "other-12345678"; const took = await m.setAgent(use, "work");', show="[took, calls]")

        self.assertEqual((took, calls), (False, [["GET", "/api/review"], "refresh"]))


if __name__ == "__main__":
    unittest.main()
