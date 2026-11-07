"""Seam: the coding agents' adapters (adapters/outbound/coding_agents/).

Each coding agent's reader turns one event of its stream into news for
Dispatch. A run is a process read into news: here a small Python script
stands in for the coding agent, so no real coding agent starts.
"""
import json
import os
import sys
import textwrap
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

from difftate.adapters.outbound.coding_agents.claude_code.events import ClaudeEvents  # noqa: E402
from difftate.adapters.outbound.coding_agents.events import read_line  # noqa: E402
from difftate.adapters.outbound.coding_agents.opencode.events import OpenCodeEvents  # noqa: E402
from difftate.adapters.outbound.coding_agents.reply_channel import RunFolder  # noqa: E402
from difftate.adapters.outbound.coding_agents.run import AgentRun  # noqa: E402
from difftate.core.dispatch.model import (  # noqa: E402
    ContextUsed, CouldNotStart, Exited, Finished, Output, Reply, Said, SessionStarted, Step, Unparsed,
)


def lines(events, *stream):
    return [n for event in stream for n in read_line(json.dumps(event), events)]


class ReadingClaudeCodesEvents(unittest.TestCase):
    def test_a_run_that_finishes(self):
        news = lines(
            ClaudeEvents(),
            {"type": "system", "subtype": "init", "session_id": "3f1c9a20-aaaa", "model": "claude-opus-5-5"},
            {"type": "assistant", "message": {
                "usage": {"input_tokens": 10, "cache_read_input_tokens": 27000, "cache_creation_input_tokens": 900,
                          "output_tokens": 90},
                "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "src/app.ts"}},
                            {"type": "text", "text": "Done reading."}, {"type": "text", "text": "  "}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": "x" * 200}},
                {"type": "tool_use", "name": "TodoWrite", "input": {"todos": []}}]}},
            {"type": "result", "is_error": False, "total_cost_usd": 0.1429,
             "modelUsage": {"claude-opus-5-5": {"contextWindow": 1_000_000}}},
        )

        self.assertEqual(news, [
            SessionStarted("3f1c9a20-aaaa", "claude-opus-5-5"),
            ContextUsed(tokens=28000),
            Step("Read  src/app.ts"),
            Said("Done reading."),
            Step("Bash  " + "x" * 119 + "…"),
            Step("TodoWrite"),
            ContextUsed(window=1_000_000),
            Finished(True, 0.1429),
        ])

    def test_a_run_that_fails_says_why(self):
        news = lines(ClaudeEvents(), {"type": "result", "subtype": "error_max_turns", "is_error": True,
                                      "result": "The model is\noverloaded.", "modelUsage": {}})

        self.assertEqual(news, [Finished(False, None, "The model is overloaded.")])


class ReadingOpenCodesEvents(unittest.TestCase):
    def test_a_run_that_finishes_adds_up_its_cost(self):
        news = lines(
            OpenCodeEvents(),
            {"type": "tool_use", "part": {"tool": "read", "state": {"input": {"filePath": "app.py"}}}},
            {"type": "tool_use", "part": {"tool": "bash", "state": {"input": {"command": "false"}, "status": "error"}}},
            {"type": "text", "part": {"text": "Looking."}},
            {"type": "step_finish", "part": {"cost": 0.01, "reason": "tool-calls",
                                             "tokens": {"input": 1000, "output": 20, "cache": {"read": 500}}}},
            {"type": "step_finish", "part": {"cost": 0.02, "reason": "stop", "tokens": {}}},
        )

        self.assertEqual(news, [
            Step("read  app.py"),
            Step("bash  false", failed=True),
            Said("Looking."),
            ContextUsed(tokens=1520),
            Finished(True, 0.03),
        ])

    def test_an_error_fails_the_run(self):
        news = lines(OpenCodeEvents(), {"type": "error", "error": "Rate limited"})

        self.assertEqual(news, [Finished(False, 0.0, "Rate limited")])


class ReadingALine(unittest.TestCase):
    def test_a_line_that_isnt_json_is_shown_as_it_is_and_a_blank_one_is_skipped(self):
        self.assertEqual(read_line("Error: not logged in\n", ClaudeEvents()), [Output("Error: not logged in")])
        self.assertEqual(read_line("  \n", ClaudeEvents()), [])

    def test_an_event_the_reader_cant_read_is_unparsed(self):
        self.assertEqual(read_line('{"type": "assistant", "message": {"content": [1]}}', ClaudeEvents()),
                         [Unparsed("'int' object has no attribute 'get'")])


class ARun(unittest.TestCase):
    """A run of a script that prints Claude Code's events and replies the way
    dt-reply does."""

    def start(self, script):
        folder = RunFolder.create(["thread-1"])
        self.addCleanup(folder.remove)
        env = dict(os.environ, DT_RUN_DIR=folder.path, PYTHONPATH=os.path.join(ROOT, "lib"))
        run = AgentRun([sys.executable, "-c", textwrap.dedent(script)], ROOT, env, ClaudeEvents(), folder)
        self.addCleanup(run.stop)
        return run, folder

    def news_until_over(self, run, timeout=10):
        found, deadline = [], time.time() + timeout
        while time.time() < deadline:
            found += run.news()
            if found and isinstance(found[-1], Exited):
                return found
            time.sleep(0.05)
        self.fail(f"the run didn't end: {found}")

    def test_its_news_are_its_steps_and_replies_then_its_end_and_its_folder_goes(self):
        run, folder = self.start("""
            import json, os
            from difftate.adapters.outbound.coding_agents.reply_channel import RunFolder
            print(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "app.py"}}]}}), flush=True)
            RunFolder(os.environ["DT_RUN_DIR"]).write_reply("thread", "An answer.")
            print(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.5}), flush=True)
        """)

        news = self.news_until_over(run)

        self.assertCountEqual(news[:-1], [Step("Read  app.py"), Reply("thread-1", "An answer."), Finished(True, 0.5)])
        self.assertEqual(news[-1], Exited(0))
        self.assertFalse(os.path.exists(folder.path))
        self.assertEqual(run.news(), [])

    def test_a_stopped_run_stops_what_it_started_and_gives_the_replies_it_left(self):
        run, folder = self.start("""
            import os, subprocess, sys, time
            from difftate.adapters.outbound.coding_agents.reply_channel import RunFolder
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            with open(os.path.join(os.environ["DT_RUN_DIR"], "child"), "w") as f:
                f.write(str(child.pid))
            RunFolder(os.environ["DT_RUN_DIR"]).write_reply("thread-1", "Half done.")
            time.sleep(60)
        """)
        child = os.path.join(folder.path, "child")
        deadline = time.time() + 10
        while not os.path.exists(child) and time.time() < deadline:
            time.sleep(0.05)
        with open(child) as f:
            child_pid = int(f.read())

        run.stop()
        news = run.news()

        self.assertEqual(news[0], Reply("thread-1", "Half done."))
        self.assertIsInstance(news[-1], Exited)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)

    def test_a_command_that_cant_run_cant_start_and_leaves_no_folder(self):
        folder = RunFolder.create(["thread-1"])

        with self.assertRaises(CouldNotStart):
            AgentRun([os.path.join(ROOT, "no-such-agent")], ROOT, dict(os.environ), ClaudeEvents(), folder)

        self.assertFalse(os.path.exists(folder.path))


if __name__ == "__main__":
    unittest.main()
