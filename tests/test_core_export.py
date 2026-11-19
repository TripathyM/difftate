"""Seam: exporting a review (GLOSSARY.md, Export), with a fake at every driven
port.

The export is the review's commit messages, every thread in full with its
thread status and thread state, which threads need an answer, and how to
reply: and no other instruction. It keeps nothing.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_fakes import FakeCode, FakeHistory  # noqa: E402
from difftate.adapters.outbound.memory_store import MemoryStore  # noqa: E402
from difftate.core.review.model import Anchor, CouldNotRead, NotesInProgress  # noqa: E402
from difftate.core.review.use_cases.add_comment import add_comment  # noqa: E402
from difftate.core.review.use_cases.end_run import end_run  # noqa: E402
from difftate.core.review.use_cases.export_review import export_review  # noqa: E402
from difftate.core.review.use_cases.list_threads import list_threads  # noqa: E402
from difftate.core.review.use_cases.open_thread import open_thread  # noqa: E402
from difftate.core.review.use_cases.set_mode import set_mode  # noqa: E402
from difftate.core.review.use_cases.set_status import set_status  # noqa: E402
from difftate.core.review.use_cases.start_run import start_run  # noqa: E402


def reply_command(folder=None):
    """How the fake reply channel names its command: with the folder when one was given."""
    return "dt-reply" if folder is None else f"dt-reply --folder {folder}"


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.code = FakeCode({"app.py": "def greet(name):\n    return f'hello {name}'\n"},
                             base={"app.py": "def greet(name):\n    return 'hi ' + name\n"}, messages=["Greet with an f-string\n\nIt reads better than +.", "Spell out three"])
        self.history = FakeHistory()
        self.notes = NotesInProgress()

    def a_thread(self, body="Why an f-string?", by=None):
        anchor = Anchor("app.py", "new", 2, 2, view="")
        return open_thread(self.store, self.notes, self.code, self.history, "reviewer", body, anchor,
                           by=by).thread.id

    def reply(self, tid, body="Because it reads better."):
        """A run on the thread answers it: the reply comes after the run took its comments."""
        threads = [t.thread for t in list_threads(self.store, self.notes, self.code) if t.thread.id == tid]
        start_run(self.store, self.notes, self.history, threads)
        add_comment(self.store, self.notes, self.history, "agent", tid, "reply", body)
        end_run(self.store, self.notes, self.history, "done")

    def export(self, folder=None, code=None):
        return export_review(self.store, self.notes, code or self.code, reply_command, folder)

    def section(self, text, heading):
        """The part of <text> under <heading> (its line starts with it), up to the next heading."""
        start = next(i for i, line in enumerate(text.split("\n")) if line.startswith(heading))
        lines = text.split("\n")[start:]
        end = next((i for i, line in enumerate(lines[1:], 1) if line.startswith("## ")), len(lines))
        return "\n".join(lines[:end])


class TheCommitMessages(ExportTest):
    def test_come_oldest_first_each_in_full(self):
        text = self.export()

        self.assertIn("## The decisions behind the code", text)
        self.assertLess(text.index("Greet with an f-string\n\nIt reads better than +."), text.index("Spell out three"))

    def test_have_no_section_when_there_are_none(self):
        text = self.export(code=FakeCode(self.code.files))

        self.assertNotIn("decisions behind the code", text)

    def test_that_cant_be_read_fail_the_export_instead_of_leaving_them_out(self):
        class Unreadable(FakeCode):
            def commit_messages(self):
                raise CouldNotRead("could not read the review's commits")

        with self.assertRaises(CouldNotRead):
            self.export(code=Unreadable(self.code.files))


class TheThreads(ExportTest):
    def test_all_come_in_full_open_resolved_and_dismissed_each_with_its_thread_status(self):
        open_one = self.a_thread("Why an f-string?")
        resolved = self.a_thread("Use a constant here.")
        dismissed = self.a_thread("Rename it to hi?")
        for tid in (open_one, resolved, dismissed):
            self.reply(tid, f"Answer {tid[:8]}.")
        set_status(self.store, self.notes, self.history, "reviewer", resolved, "resolved")
        set_status(self.store, self.notes, self.history, "reviewer", dismissed, "dismissed")

        text = self.export()

        self.assertIn(f"### Thread {open_one[:8]} — app.py:2 — open", text)
        self.assertIn(f"### Thread {resolved[:8]} — app.py:2 — resolved", text)
        self.assertIn(f"### Thread {dismissed[:8]} — app.py:2 — dismissed", text)
        self.assertIn("reviewer: Use a constant here.\ncoding agent: Answer " + resolved[:8] + ".", text)

    def test_show_their_comments_and_replies_uncut_in_order_without_notes(self):
        tid = self.a_thread("First.", by="Ada")
        long_middle = "See " + "why " * 100 + "https://example.com/a-link-at-the-end"
        add_comment(self.store, self.notes, self.history, "reviewer", tid, "comment", long_middle)
        self.reply(tid, "Done.")
        add_comment(self.store, self.notes, self.history, "difftate", tid, "progress", "**Working** on it")

        text = self.export()

        self.assertLess(text.index("reviewer Ada: First."), text.index(long_middle))
        self.assertLess(text.index(long_middle), text.index("coding agent: Done."))
        self.assertNotIn("**", text)

    def test_show_the_code_they_were_written_on(self):
        self.a_thread()

        self.assertIn("Code:\n```\n    return f'hello {name}'\n```", self.export())

    def test_show_an_outdated_thread_as_such_with_the_code_it_was_written_on(self):
        version = self.code.changeset("").versions["app.py"].new
        self.code.files["app.py"] = self.code.files["app.py"].replace("hello", "hi")
        anchor = Anchor("app.py", "new", 2, 2, "    return f'hello {name}'", view="", snapshot_id=version)
        tid = open_thread(self.store, self.notes, self.code, self.history, "reviewer", "Why hello?", anchor).thread.id

        text = self.export()

        self.assertIn(f"### Thread {tid[:8]} — app.py:2 — open (waiting) — outdated", text)
        self.assertIn("Code when the thread was written:\n```\n    return f'hello {name}'\n```", text)

    def test_name_the_thread_state_of_an_open_thread_and_none_for_the_others(self):
        waiting = self.a_thread("Waiting.")
        replied = self.a_thread("Replied.")
        resolved = self.a_thread("Resolved.")
        self.reply(replied)
        self.reply(resolved)
        set_status(self.store, self.notes, self.history, "reviewer", resolved, "resolved")

        text = self.export()

        self.assertIn(f"### Thread {waiting[:8]} — app.py:2 — open (waiting)", text)
        self.assertIn(f"### Thread {replied[:8]} — app.py:2 — open (replied)", text)
        self.assertIn(f"### Thread {resolved[:8]} — app.py:2 — resolved\n", text)

    def test_name_the_held_state_of_a_thread_in_a_batched_review(self):
        set_mode(self.store, self.notes, self.history, "reviewer", "batched")
        tid = self.a_thread("Held until I submit.")

        self.assertIn(f"### Thread {tid[:8]} — app.py:2 — open (held)", self.export())

    def test_include_a_general_thread(self):
        tid = open_thread(self.store, self.notes, self.code, self.history, "reviewer", "Is this ready?").thread.id

        self.assertIn(f"### Thread {tid[:8]} — general thread (not tied to a line) — open (waiting)", self.export())


class TheThreadsThatNeedAnAnswer(ExportTest):
    def test_are_the_open_threads_with_no_reply_to_the_latest_comment_and_are_marked_as_such(self):
        waiting = self.a_thread("Waiting.")
        replied = self.a_thread("Replied.")
        resolved = self.a_thread("Resolved, no reply.")
        self.reply(replied)
        set_status(self.store, self.notes, self.history, "reviewer", resolved, "resolved")
        set_mode(self.store, self.notes, self.history, "reviewer", "batched")
        held = self.a_thread("Held.")

        text = self.export()

        needing = self.section(text, "## Threads that need an answer")
        self.assertIn("(2)", needing.split("\n")[0])
        self.assertIn(f"### Thread {waiting[:8]}", needing)
        self.assertIn(f"### Thread {held[:8]}", needing)
        others = self.section(text, "## Other threads")
        self.assertIn("(2)", others.split("\n")[0])
        self.assertIn(f"### Thread {replied[:8]}", others)
        self.assertIn(f"### Thread {resolved[:8]}", others)
        self.assertNotIn(f"### Thread {replied[:8]}", needing)

    def test_say_so_when_there_are_none(self):
        self.reply(self.a_thread())

        needing = self.section(self.export(), "## Threads that need an answer")

        self.assertIn("(0)", needing)
        self.assertIn("None.", needing)

    def test_say_so_when_the_review_has_no_thread_at_all(self):
        text = self.export()

        self.assertIn("(0)", self.section(text, "## Threads that need an answer"))
        self.assertIn("(0)", self.section(text, "## Other threads"))


class HowToReply(ExportTest):
    def test_names_the_command_for_the_session(self):
        self.a_thread()

        how = self.section(self.export(), "## How to reply")

        self.assertIn('dt-reply <thread> "<answer>"', how)
        self.assertNotIn("--folder", how)

    def test_names_the_folder_in_the_command_when_one_was_given(self):
        self.a_thread()

        how = self.section(self.export(folder="/work/demo"), "## How to reply")

        self.assertIn('dt-reply --folder /work/demo <thread> "<answer>"', how)

    def test_comes_last(self):
        self.a_thread()

        text = self.export()

        self.assertGreater(text.index("## How to reply"), text.index("## Other threads"))
        self.assertTrue(text.index("## How to reply") > text.index("## Threads that need an answer"))


class TheRules(ExportTest):
    def test_the_export_gives_no_instruction_but_how_to_reply(self):
        self.a_thread()

        text = self.export()

        for rule in ("Change code", "NEVER", "Never", "Rules:", "Simplified Technical English", "Summarize"):
            self.assertNotIn(rule, text)

    def test_exporting_changes_no_thread_and_keeps_and_records_nothing(self):
        self.a_thread()
        events, recorded = list(self.store.load()), list(self.history.recorded)

        self.export()
        self.export(folder="/work/demo")

        self.assertEqual(self.store.load(), events)
        self.assertEqual(self.history.recorded, recorded)


if __name__ == "__main__":
    unittest.main()
