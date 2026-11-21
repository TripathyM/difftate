"""Seam: Dispatch's use cases, for running the loop, with a fake at every
driven port.

The review's use cases are bound as the watcher binds them, over the memory
store and a fake code reader. A fake coding agent gives each run a scripted
list of news, a fake reporter keeps what Dispatch reports, and a fake clock
gives the time. No process runs.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeClock, FakeCode, FakeCodingAgent, FakeHistory, FakeReporter, FakeRun  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.dispatch.model import (  # noqa: E402
    Dispatch, Exited, Finished, ModelChosen, Output, Reply, Said, AgentSessionStarted, Step, Unparsed,
)
from difftate.core.dispatch.use_cases.hold_for_branch import hold_for_branch  # noqa: E402
from difftate.core.dispatch.use_cases.stop_run import stop_run  # noqa: E402
from difftate.core.dispatch.use_cases.poll import poll  # noqa: E402
from difftate.core.dispatch.use_cases.recover_runs import recover_runs  # noqa: E402
from difftate.core.review.model import Anchor, CouldNotRead, Review, RunEnded  # noqa: E402
from difftate.main import bind_review  # noqa: E402


class StoreThatCannotKeepARunsEnd(MemoryStore):
    """A store that can't write for a while (a full disk, say): the first
    <fails> times it is given a run's end."""

    def __init__(self, fails=0):
        super().__init__()
        self.fails = fails

    def append(self, events):
        if self.fails and any(isinstance(e, RunEnded) for e in events):
            self.fails -= 1
            raise CouldNotRead("could not write the review")
        super().append(events)


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.store = StoreThatCannotKeepARunsEnd()
        self.code = FakeCode({"app.py": "def greet(name):\n    return f'hello {name}'\n"})
        self.review = bind_review(self.store, self.code, FakeHistory(), {"id": "r", "branch": "feature", "base": "main"})
        self.clock = FakeClock()
        self.dispatch = Dispatch(self.review, clock=self.clock)
        self.report = FakeReporter()

    def a_thread(self, body="Why an f-string here?"):
        return self.review.open_thread("reviewer", body).thread.id

    def poll(self, agent, times=1):
        for _ in range(times):
            poll(self.dispatch, agent, self.report)
            self.clock.wait(1)

    def comments(self, tid):
        [listed] = [t for t in self.review.list_threads() if t.thread.id == tid]
        return [(c.kind, c.body) for c in listed.thread.comments]

    def state(self, tid):
        return next(t.state for t in self.review.list_threads() if t.thread.id == tid)


class AWholeRun(DispatchTest):
    def test_a_waiting_thread_gets_a_progress_note_with_the_steps_then_the_reply_and_done(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([
            [Step("Read  app.py")],
            [Reply(tid, "Because it reads better."), Said("Replied to 1 thread."),
             Finished(True, cost=0.0123), Exited(0)],
        ]))

        self.poll(agent)  # the run starts
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string here?"),
                                              ("progress", "⏳ **Thinking…** (0s)")])
        self.assertEqual(self.state(tid), "working")
        self.assertEqual(agent.started[0][1], [tid])
        self.assertIn(f"### Thread {tid[:8]}", agent.started[0][0])

        self.poll(agent)  # a step
        self.assertEqual(self.comments(tid)[-1], ("progress", "⏳ **Working…** (1s)\n- ⏳ `Read app.py`"))

        self.poll(agent)  # the reply, and the end
        self.assertEqual(self.comments(tid), [
            ("comment", "Why an f-string here?"),
            ("progress", "✅ **Done** in 2s"),
            ("reply", "Because it reads better."),
        ])
        self.assertEqual(self.state(tid), "replied")
        self.assertEqual(self.report.reported, [
            ("dispatching", "fake"),
            ("step", "Read  app.py", False),
            ("said", "Replied to 1 thread."),
            ("finished", True, 2, 0.0123),
        ])
        self.assertIsNone(self.dispatch.run)


    def test_the_coding_agents_own_lines_are_reported_as_they_come(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([
            [ModelChosen("opus", "--model"), AgentSessionStarted("fake-session", "fake-model"), Output("not json"),
             Unparsed("bad event"), Step("Bash  false", failed=True)],
            [Reply(tid, "Done."), Finished(True, cost=None), Exited(0)],
        ]))

        self.poll(agent, times=3)

        self.assertEqual(self.report.reported, [
            ("dispatching", "fake"),
            ("model_chosen", "opus", "--model"),
            ("agent_session_started", "fake-session", "fake-model"),
            ("output", "not json"),
            ("unparsed", "bad event"),
            ("step", "Bash  false", True),
            ("finished", True, 2, None),
        ])
        self.assertEqual(self.comments(tid)[1], ("progress", "✅ **Done** in 2s"))

    def test_the_progress_notes_show_the_time_every_few_seconds_while_nothing_happens(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([]))

        self.poll(agent, times=3)
        self.assertEqual(self.comments(tid)[-1], ("progress", "⏳ **Thinking…** (0s)"))
        self.poll(agent)
        self.assertEqual(self.comments(tid)[-1], ("progress", "⏳ **Thinking…** (3s)"))

    def test_once_the_coding_agent_finished_its_progress_notes_keep_the_time_it_took(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[], [Finished(True)]]))  # its process lingers after it finished

        self.poll(agent, times=8)

        self.assertEqual(self.comments(tid)[-1], ("progress", "✅ **Done** in 2s"))

    def test_the_progress_note_shows_the_last_eight_steps(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[Step(f"Read  file{n}.py") for n in range(10)]]))

        self.poll(agent, times=2)

        self.assertEqual(self.comments(tid)[-1][1].split("\n"), [
            "⏳ **Working…** (1s)", "- ✅ …2 earlier steps",
            *[f"- ✅ `Read file{n}.py`" for n in range(2, 9)], "- ⏳ `Read file9.py`"])


class ThePrompt(DispatchTest):
    def test_it_shows_the_coding_agent_who_wrote_each_comment(self):
        tid = self.review.open_thread("reviewer", "Why an f-string here?", by="Ada").thread.id
        other = self.review.open_thread("reviewer", "And the docs?", by="docs-bot").thread.id
        self.review.add_comment("reviewer", tid, "comment", "Is it safe?", by="security-bot")
        agent = FakeCodingAgent(FakeRun([[Reply(tid[:8], "Yes."), Reply(other[:8], "Done."), Finished(True),
                                          Exited(0)]]),
                                FakeRun([[Finished(True), Exited(0)]]))

        self.poll(agent)
        self.review.add_comment("reviewer", tid, "comment", "Thanks.")
        self.poll(agent, times=3)

        first, second = agent.started[0][0], agent.started[1][0]
        self.assertIn("reviewer Ada (new): Why an f-string here?", first)
        self.assertIn("reviewer security-bot (new): Is it safe?", first)
        self.assertIn("reviewer docs-bot (new): And the docs?", first)
        self.assertIn("reviewer Ada: Why an f-string here?", second)
        self.assertIn("reviewer (new): Thanks.", second, "a comment with no name names no one")
        self.assertIn("reviewer docs-bot: And the docs?", self.other_threads(second),
                      "the other threads name them too")

    def other_threads(self, text):
        """The prompt's "other threads" section, its heading first, up to the rules."""
        return text.split("## Other threads")[1].split("\nRules:")[0]

    def test_it_shows_another_thread_in_full_with_a_long_middle_comment_uncut_and_no_notes(self):
        other = self.a_thread("And the docs?")
        long_middle = "See " + "why " * 100 + "https://example.com/a-link-at-the-end"
        self.review.add_comment("reviewer", other, "comment", long_middle)
        self.review.add_comment("reviewer", other, "comment", "Last word.")
        agent = FakeCodingAgent(FakeRun([[Reply(other, "Done."), Finished(True), Exited(0)]]),
                                FakeRun([[Finished(True), Exited(0)]]))
        self.poll(agent, times=2)
        tid = self.a_thread()
        self.poll(agent, times=2)

        others = self.other_threads(agent.started[1][0])
        self.assertIn(f"### Thread {other[:8]}", others)
        self.assertLess(others.index("reviewer: And the docs?"), others.index(long_middle))
        self.assertLess(others.index(long_middle), others.index("reviewer: Last word."))
        self.assertIn("you: Done.", others)
        self.assertNotIn("**", others, "its run's progress note is left out")
        self.assertNotIn(tid[:8], others)

    def test_it_shows_resolved_and_dismissed_threads_with_their_status_and_sends_only_the_waiting_one(self):
        resolved = self.a_thread("Use a constant here.")
        dismissed = self.a_thread("Rename it to hi?")
        replied = self.a_thread("Is this tested?")
        agent = FakeCodingAgent(FakeRun([[Reply(resolved, "Fixed."), Reply(dismissed, "Shall I?"),
                                          Reply(replied, "Yes."), Finished(True), Exited(0)]]),
                                FakeRun([[Finished(True), Exited(0)]]))
        self.poll(agent, times=2)
        self.review.set_status("reviewer", resolved, "resolved")
        self.review.set_status("reviewer", dismissed, "dismissed")
        tid = self.a_thread()
        self.poll(agent, times=2)

        text, reply_to = agent.started[1]
        mine = text.split("## Reply to these threads")[1].split("## Other threads")[0]
        self.assertEqual(re.findall(r"^### Thread (\w{8})", mine, re.M), [tid[:8]])
        others = self.other_threads(text)
        self.assertIn(f"### Thread {resolved[:8]} — general thread (not tied to a line) — resolved", others)
        self.assertIn(f"### Thread {dismissed[:8]} — general thread (not tied to a line) — dismissed", others)
        self.assertIn(f"### Thread {replied[:8]} — general thread (not tied to a line) — open", others)
        self.assertIn("reviewer: Use a constant here.\nyou: Fixed.", others)
        self.assertIn("context only", others.split("\n")[0], "in the section's heading")
        self.assertEqual(sorted(reply_to), sorted([tid, replied]), "a run may reply to the open threads only")

    COMMITS = ["Greet with an f-string\n\nChose an f-string over +: it reads better.", "Spell out three"]

    def started_with(self, code):
        """The prompt of a run on one thread, written in a view of one commit,
        with <code> as the code reader."""
        self.review = bind_review(self.store, code, FakeHistory(), {"id": "r", "branch": "feature", "base": "main"})
        self.dispatch = Dispatch(self.review, clock=self.clock)
        self.review.open_thread("reviewer", "Why an f-string here?", Anchor("app.py", "new", 2, 2, view=code.commit))
        agent = FakeCodingAgent(FakeRun([[Finished(True), Exited(0)]]))
        self.poll(agent)
        return agent.started[0][0]

    def test_it_has_every_commit_message_of_the_review_before_the_threads_even_in_a_view_of_one_commit(self):
        text = self.started_with(FakeCode(self.code.files, messages=self.COMMITS))

        decisions = text.index("## The decisions behind the code")
        self.assertLess(decisions, text.index("## Reply to these threads"))
        self.assertLess(text.index("Greet with an f-string\n\nChose an f-string over +: it reads better."),
                        text.index("Spell out three"), "oldest first")
        self.assertLess(text.index("Spell out three"), text.index("## Reply to these threads"))

    def test_it_has_no_commit_section_when_the_review_has_no_commits(self):
        text = self.started_with(FakeCode(self.code.files))

        self.assertNotIn("decisions behind the code", text)
        self.assertIn("## Reply to these threads", text)

    def test_a_run_starts_without_the_commit_section_when_the_commits_cant_be_read(self):
        class CommitsThatCantBeRead(FakeCode):
            def commit_messages(self):
                raise CouldNotRead("could not read the review's commits")

        text = self.started_with(CommitsThatCantBeRead(self.code.files))

        self.assertNotIn("decisions behind the code", text)
        self.assertIn("reviewer (new): Why an f-string here?", text)


class ARunWithNoReply(DispatchTest):
    def test_a_thread_the_run_didnt_reply_to_is_failed_until_the_reviewer_comments(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[Finished(True), Exited(0)]]),
                                FakeRun([[Reply("x", "")]]))

        self.poll(agent, times=4)

        self.assertEqual(self.comments(tid)[1], ("progress", "❌ **Failed** after 1s — no reply"))
        self.assertEqual(self.state(tid), "failed")
        self.assertEqual(self.report.of("no_reply"), [(tid, False)])
        self.assertEqual(len(agent.started), 1, "not sent again")

        self.review.add_comment("reviewer", tid, "comment", "Please try again.")
        self.poll(agent)
        self.assertEqual(len(agent.started), 2)
        self.assertIn("reviewer (new): Please try again.", agent.started[1][0])

    def test_a_run_that_fails_keeps_the_coding_agents_error_and_says_no_reply(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[Step("Read  app.py")],
                                         [Finished(False, error="The model is overloaded."), Exited(0)]]))

        self.poll(agent, times=3)

        self.assertEqual(self.comments(tid)[1], ("progress", "❌ **Failed** after 2s\n- ✅ `Read app.py`\n\n"
                                                             "The model is overloaded.\n\nNo reply."))
        self.assertIn(("coding_agent_failed", "The model is overloaded."), self.report.reported)
        self.assertIn(("finished", False, 2, None), self.report.reported)

    def test_a_coding_agent_that_exits_without_finishing_fails_its_threads(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[Exited(1)]]))

        self.poll(agent, times=2)

        self.assertEqual(self.comments(tid)[1], ("progress", "❌ **Failed** after 1s\n\nAgent exited without "
                                                             "finishing — check the watcher terminal.\n\nNo reply."))
        self.assertEqual(self.report.reported[1:], [
            ("finished", False, 1, None),
            ("warning", "dispatch to fake failed (exit 1)"),
            ("no_reply", tid, False),
        ])
        self.assertEqual([r.outcome for r in Review.from_events(self.store.load()).runs()], ["failed"])

    def test_a_coding_agent_that_cant_start_fails_its_threads_and_dispatch_goes_on(self):
        tid = self.a_thread()
        agent = FakeCodingAgent()
        agent.cant_start = "no such file"

        self.poll(agent)

        self.assertEqual(self.comments(tid)[1], ("progress", "❌ **Failed** after 0s — no reply "
                                                             "(could not start fake: no such file)"))
        self.assertIn(("warning", "could not start fake: no such file"), self.report.reported)
        self.assertIsNone(self.dispatch.run)

    def test_a_reply_to_a_thread_that_wasnt_open_when_the_run_started_is_dropped(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[]]))
        self.poll(agent)
        later = self.a_thread("Rename greet?")
        self.dispatch.run.handle.script = [[Reply(later, "Sneaky."), Reply(tid, "Fine."), Finished(True), Exited(0)]]

        self.poll(agent)

        self.assertNotIn(("reply", "Sneaky."), self.comments(later))
        self.assertIn(("reply", "Fine."), self.comments(tid))
        self.assertIn(("warning", f"dropped a reply to thread {later[:8]}: it isn't open in this run"),
                      self.report.reported)


class QueuedThreads(DispatchTest):
    def test_a_thread_written_during_a_run_is_queued_then_its_queued_note_becomes_the_next_runs_progress_note(self):
        first = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[]]), FakeRun([]))
        self.poll(agent)
        second = self.a_thread("Rename greet?")

        self.poll(agent)
        self.assertEqual(self.comments(second)[-1], ("queued", "🕒 **Queued** — agent is busy with another "
                                                                "comment, will pick this up next."))
        self.assertEqual(self.state(second), "queued")
        self.assertEqual(self.report.of("queued"), [(second,)])
        self.dispatch.run.handle.script = [[Reply(first, "Yes."), Finished(True), Exited(0)]]

        self.poll(agent, times=2)  # the first run ends; the next starts
        self.assertEqual(agent.started[1][1], sorted([first, second]), "the open threads it may reply to")
        self.assertEqual(self.comments(second), [("comment", "Rename greet?"), ("progress", "⏳ **Thinking…** (0s)")])

    def test_a_queued_note_with_a_comment_after_it_says_it_was_picked_up(self):
        self.a_thread()
        agent = FakeCodingAgent(FakeRun([[]]), FakeRun([]))
        self.poll(agent)
        second = self.a_thread("Rename greet?")
        self.poll(agent)
        self.review.add_comment("reviewer", second, "comment", "Or to hello?")
        self.dispatch.run.handle.script = [[Finished(True), Exited(0)]]

        self.poll(agent, times=2)

        self.assertEqual(self.comments(second), [
            ("comment", "Rename greet?"),
            ("queued", "🕒 **Queued** — picked up by the next run (below)."),
            ("comment", "Or to hello?"),
            ("progress", "⏳ **Thinking…** (0s)"),
        ])


class WaitingForABranch(DispatchTest):
    NOTE = ("🕒 **Waiting** — branch `feature` is checked out in no folder difftate serves: "
            "check it out to get a reply.")

    def test_a_waiting_thread_gets_a_note_when_no_folder_has_the_branch_and_the_run_reuses_it(self):
        tid = self.a_thread()

        hold_for_branch(self.dispatch, "feature")

        self.assertEqual(self.comments(tid), [("comment", "Why an f-string here?"), ("queued", self.NOTE)])
        self.assertEqual(self.state(tid), "waiting")
        agent = FakeCodingAgent(FakeRun([[]]))
        self.poll(agent)
        self.assertEqual(self.comments(tid), [("comment", "Why an f-string here?"),
                                              ("progress", "⏳ **Thinking…** (0s)")], "the note goes when the run starts")

    def test_the_note_is_kept_once_and_replaces_a_busy_note(self):
        first = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[]]))
        self.poll(agent)
        second = self.a_thread("Rename greet?")
        self.poll(agent)  # busy: the second thread has a queued note

        hold_for_branch(self.dispatch, "feature")
        hold_for_branch(self.dispatch, "feature")

        self.assertEqual(self.comments(second), [("comment", "Rename greet?"), ("queued", self.NOTE)])
        self.assertEqual(self.comments(first)[-1][0], "progress", "a thread in the run has no such note")

    def test_a_resolved_thread_gets_no_note(self):
        tid = self.a_thread()
        self.review.set_status("reviewer", tid, "resolved")

        hold_for_branch(self.dispatch, "feature")

        self.assertEqual(self.comments(tid), [("comment", "Why an f-string here?")])


class StoppingARun(DispatchTest):
    def test_a_stopped_run_posts_the_replies_it_left_and_fails_the_threads_with_none(self):
        replied, silent = self.a_thread(), self.a_thread("Rename greet?")
        run = FakeRun([[]], left_on_stop=[Reply(replied, "Yes.")])
        self.poll(FakeCodingAgent(run))

        stop_run(self.dispatch, self.report)

        self.assertTrue(run.stopped)
        self.assertEqual(self.comments(replied)[1:], [("progress", "⏹ **Stopped** after 1s (the watcher stopped)"),
                                                      ("reply", "Yes.")])
        self.assertEqual(self.comments(silent)[1],
                         ("progress", "❌ **Failed** after 1s — no reply (the watcher stopped)"))
        self.assertEqual(self.report.of("stopping"), [(4242,)])
        self.assertEqual(self.report.of("no_reply"), [], "the watcher says it stopped instead")
        self.assertEqual([r.outcome for r in Review.from_events(self.store.load()).runs()], ["stopped"])

    def test_a_run_that_finished_before_it_was_stopped_keeps_its_ending(self):
        tid = self.a_thread()
        run = FakeRun([[]], left_on_stop=[Reply(tid, "Yes."), Finished(True)])
        self.poll(FakeCodingAgent(run))

        stop_run(self.dispatch, self.report)

        self.assertEqual(self.comments(tid)[1:], [("progress", "✅ **Done** in 1s"), ("reply", "Yes.")])

    def test_a_run_its_watcher_was_killed_during_is_recovered_by_the_next_watcher(self):
        tid = self.a_thread()
        self.poll(FakeCodingAgent(FakeRun([[]])))
        next_watcher = Dispatch(self.review, clock=self.clock)

        recover_runs(next_watcher.review, self.report)

        self.assertEqual(self.state(tid), "failed")
        self.assertEqual(self.comments(tid)[-1], ("progress", "❌ **Failed** — no reply (the watcher stopped)"))
        self.assertEqual(self.report.of("no_reply"), [(tid, True)])


class AStoreThatCantKeepARunsEnd(DispatchTest):
    def setUp(self):
        super().setUp()
        self.tid = self.a_thread()
        self.agent = FakeCodingAgent(FakeRun([[Finished(True), Exited(0)]]), FakeRun([]))

    def test_an_end_the_store_could_not_keep_is_kept_before_the_next_run_starts(self):
        self.store.fails = 1
        self.poll(self.agent, times=2)
        self.assertEqual(self.state(self.tid), "working", "the run is still in progress in the review")
        self.a_thread("Another one")

        self.poll(self.agent)

        self.assertEqual(self.state(self.tid), "failed")
        self.assertEqual([r.outcome for r in Review.from_events(self.store.load()).runs()], ["done", None],
                         "the end is kept, then the next run starts")
        self.assertIn(("warning", "could not record the end of the run (could not write the review): "
                                  "no run starts until it is recorded"), self.report.reported)
        self.assertIn(("no_reply", self.tid, False), self.report.reported)

    def test_a_store_that_keeps_failing_is_warned_about_once(self):
        self.store.fails = 3
        self.poll(self.agent, times=4)

        self.assertEqual(len(self.report.of("warning")), 1)
        self.assertEqual(self.state(self.tid), "working")


if __name__ == "__main__":
    unittest.main()
