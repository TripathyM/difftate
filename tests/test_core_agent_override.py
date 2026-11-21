"""The agent override of a review (GLOSSARY.md, Agent override): a reviewer
picks another agent for one review, and clears the pick. It is a review event,
like the review mode, kept in the review and its history; only a reviewer sets
it. The core doesn't know the agent list: the names are checked at the watcher."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from core_fakes import FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import AgentOverridden, NotAllowed, NotesInProgress, Review  # noqa: E402
from difftate.core.review.use_cases.read_agent_override import read_agent_override  # noqa: E402
from difftate.core.review.use_cases.set_agent_override import set_agent_override  # noqa: E402


class AgentOverrideTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.history = FakeHistory()
        self.notes = NotesInProgress()

    def choose(self, name, author="reviewer"):
        return set_agent_override(self.store, self.notes, self.history, author, name)

    def override(self):
        return read_agent_override(self.store)


class TheAgentOverride(AgentOverrideTest):
    def test_a_new_review_has_none(self):
        self.assertEqual(self.override(), "")

    def test_a_reviewer_sets_it_and_it_is_kept_in_the_review_and_the_history(self):
        self.assertEqual(self.choose("work"), "work")

        self.assertEqual(self.override(), "work")
        self.assertEqual([type(e) for e in self.store.load()], [AgentOverridden])
        self.assertEqual([(e.agent) for e in self.history.recorded], ["work"])

    def test_a_later_choice_replaces_it_and_clearing_goes_back_to_none(self):
        self.choose("work")
        self.choose("opencode")
        self.assertEqual(self.override(), "opencode")

        self.assertEqual(self.choose(""), "")

        self.assertEqual(self.override(), "")
        self.assertEqual([e.agent for e in self.history.recorded], ["work", "opencode", ""], "every change is recorded")

    def test_choosing_what_is_chosen_already_or_clearing_none_leaves_no_event(self):
        self.choose("")
        self.choose("work")
        self.choose("work")

        self.assertEqual([e.agent for e in self.store.load()], ["work"])
        self.assertEqual([e.agent for e in self.history.recorded], ["work"])

    def test_only_a_reviewer_sets_it_and_nothing_is_kept_for_anyone_else(self):
        for author in ("agent", "difftate"):
            with self.subTest(author=author):
                with self.assertRaises(NotAllowed):
                    self.choose("work", author)
                with self.assertRaises(NotAllowed):
                    self.choose("", author)

        self.assertEqual((self.override(), self.store.load(), self.history.recorded), ("", [], []))

    def test_a_review_replayed_from_its_events_has_the_last_choice(self):
        events = [AgentOverridden("work", "t1"), AgentOverridden("opencode", "t2")]

        self.assertEqual(Review.from_events(events).agent_override(), "opencode")
        self.assertEqual(Review.from_events(events[:1] + [AgentOverridden("", "t3")]).agent_override(), "")


if __name__ == "__main__":
    unittest.main()
