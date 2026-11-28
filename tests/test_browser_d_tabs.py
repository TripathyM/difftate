"""Layout D's two tabs (#258): which one a review opens on and why, and what needs the reviewer
(web/d/tabs.js). Node runs it, with threads shaped like the released transcript's."""
import json
import shutil
import unittest

from browser_d import released, run_js


def thread(state, status="open"):
    """A thread of the released transcript, standing as <state> says."""
    return dict(released("GET", "/api/threads")[0], id=f"{status}-{state}", status=status, state=state)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheFirstTab(unittest.TestCase):
    def first(self, address, *threads):
        return run_js("tabs", f"console.log(JSON.stringify(m.firstTab({json.dumps(address)}, {json.dumps(threads)})));")

    def test_a_review_with_a_replied_or_failed_open_thread_opens_on_conversation_saying_why(self):
        one = self.first(None, thread("replied"), thread("waiting"))
        two = self.first(None, thread("replied"), thread("failed"))

        self.assertEqual(one, {"tab": "conversation",
                               "why": "Opened on Conversation: 1 thread needs you (replied or failed)."})
        self.assertEqual(two, {"tab": "conversation",
                               "why": "Opened on Conversation: 2 threads need you (replied or failed)."})

    def test_else_it_opens_on_files_changed_saying_why(self):
        others = [thread(s) for s in ("held", "waiting", "queued", "working")]
        closed = [thread(None, "resolved"), thread(None, "dismissed")]

        got = self.first(None, *others, *closed)

        self.assertEqual(got, {"tab": "files", "why": "Opened on Files changed: no open thread is replied or failed."})

    def test_the_tab_the_address_names_wins_saying_nothing(self):
        self.assertEqual(self.first("files", thread("replied")), {"tab": "files", "why": ""})
        self.assertEqual(self.first("conversation"), {"tab": "conversation", "why": ""})


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheTabInTheAddress(unittest.TestCase):
    def test_the_address_names_a_tab_or_none(self):
        searches = ["?folder=%2Frepo&tab=conversation", "?folder=%2Frepo&tab=files", "?folder=%2Frepo",
                    "?folder=%2Frepo&tab=commits", ""]

        got = run_js("tabs", f"console.log(JSON.stringify({json.dumps(searches)}.map(m.tabIn)));")

        self.assertEqual(got, ["conversation", "files", None, None, None])

    def test_keeping_the_tab_in_the_address_leaves_the_rest_of_it(self):
        href = "http://127.0.0.1:5000/d?folder=%2Fmy%20repo"

        got = run_js("tabs", f"""
const kept = m.addressWithTab({json.dumps(href)}, "conversation");
console.log(JSON.stringify([m.tabIn(new URL(kept).search), new URL(kept).searchParams.get("folder"),
  new URL(kept).pathname, new URL(m.addressWithTab(kept, "files")).searchParams.getAll("tab")]));""")

        self.assertEqual(got, ["conversation", "/my repo", "/d", ["files"]])


if __name__ == "__main__":
    unittest.main()
