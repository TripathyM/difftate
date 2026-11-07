"""Seam: Dispatch's use cases, for running the loop, with a fake at every
driven port.

The review's use cases are bound as the watcher binds them, over the memory
store and a fake code reader. A fake coding agent gives each run a scripted
list of news, a fake reporter keeps what Dispatch reports, and a fake clock
gives the time. No process runs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeClock, FakeCode, FakeCodingAgent, FakeHistory, FakeReporter, FakeRun  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.dispatch.model import (  # noqa: E402
    ContextUsed, Dispatch, Exited, Finished, ModelChosen, Output, Reply, Said, AgentSessionStarted, Step, Unparsed,
)
from difftate.core.dispatch.use_cases.stop_run import stop_run  # noqa: E402
from difftate.core.dispatch.use_cases.poll import poll  # noqa: E402
from difftate.core.dispatch.use_cases.recover_runs import recover_runs  # noqa: E402
from difftate.core.review.model import CouldNotRead, Review, RunEnded  # noqa: E402
from difftate.watcher import bind_review  # noqa: E402


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
            ("finished", True, 2, 0.0123, ""),
        ])
        self.assertIsNone(self.dispatch.run)


    def test_the_coding_agents_own_lines_are_reported_as_they_come(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([
            [ModelChosen("opus", "session"), AgentSessionStarted("fake-session", "fake-model"), Output("not json"),
             Unparsed("bad event"), Step("Bash  false", failed=True)],
            [Reply(tid, "Done."), ContextUsed(tokens=150_000), ContextUsed(window=200_000),
             Finished(True, cost=None), Exited(0)],
        ]))

        self.poll(agent, times=3)

        self.assertEqual(self.report.reported, [
            ("dispatching", "fake"),
            ("model_chosen", "opus", "session"),
            ("agent_session_started", "fake-session", "fake-model"),
            ("output", "not json"),
            ("unparsed", "bad event"),
            ("step", "Bash  false", True),
            ("finished", True, 2, None, "🧠 context 150k / 200k (75%) ⚠️ consider /compact"),
        ])
        self.assertEqual(self.comments(tid)[1], ("progress", "✅ **Done** in 2s · 🧠 context 150k / 200k (75%) "
                                                             "⚠️ consider /compact"))

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
        self.assertIn(("finished", False, 2, None, ""), self.report.reported)

    def test_a_coding_agent_that_exits_without_finishing_fails_its_threads(self):
        tid = self.a_thread()
        agent = FakeCodingAgent(FakeRun([[Exited(1)]]))

        self.poll(agent, times=2)

        self.assertEqual(self.comments(tid)[1], ("progress", "❌ **Failed** after 1s\n\nAgent exited without "
                                                             "finishing — check the watcher terminal.\n\nNo reply."))
        self.assertEqual(self.report.reported[1:], [
            ("finished", False, 1, None, ""),
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
