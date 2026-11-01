"""Dispatch: send the waiting threads to the agent, one run at a time.

While a run works, threads that become waiting get a queued note right away.
The run's progress notes are kept by lib/stream_fmt.py through the review API.
When the run ends, a thread it didn't reply to is failed ("no reply"): its
progress note says so, and it isn't sent again until the reviewer comments.
"""
import json
import os
import time

from . import prompt
from .agent import Run
from .store import StoreError

QUEUED_NOTE = "🕒 **Queued** — agent is busy with another comment, will pick this up next."


def now():
    return time.strftime("%H:%M:%S")


class Dispatch:
    def __init__(self, review, how_to_reply, agent, cwd, interval, api, problem):
        self.review = review
        self.how_to_reply = how_to_reply  # the prompt's rule for how the agent replies
        self.agent = agent
        self.cwd = cwd
        self.interval = interval
        self.api = api  # ApiAddress, for the progress notes
        self.problem = problem  # () -> None, or why the watcher must exit
        self.run = None
        self.started = None  # when the run in progress started

    def _open_threads(self):
        try:
            return self.review.threads("open")
        except StoreError:
            return []

    def forever(self):
        """Runs until the store goes away (returns its message) or Ctrl+C."""
        while True:
            problem = self.problem()
            if problem:
                return problem
            self.once()
            time.sleep(self.interval)

    def once(self):
        open_threads = self._open_threads()
        waiting = [t for t in open_threads if t["state"] == "waiting"]
        if not waiting:
            return
        print(f"[{now()}] New/changed threads detected — dispatching to {self.agent.name}")

        ids = [t["id"] for t in waiting]
        new_ids = [cid for t in waiting for cid in self.review.unsent(t)]
        argv, said = self.agent.command(prompt.build(open_threads, ids, new_ids, self.how_to_reply))
        for line in said:
            print(line)
        # A thread that ends in its queued note gets that note back as its progress note
        queued = {t["id"]: t["comments"][-1]["id"] for t in waiting if t["comments"][-1]["kind"] == "queued"}
        # The progress notes go through the review API. Only the formatter gets the
        # token file, never the agent.
        fmt_env = dict(os.environ, **self.api.env(), DT_THREAD_IDS=",".join(ids),
                       DT_QUEUED_NOTES=json.dumps(queued))
        self.started = time.time()
        self.review.start_run(waiting)
        self.run = Run(self.agent.name, argv, self.cwd, fmt_env)
        # Threads that arrive meanwhile get a queued note right away. Runs stay one at a time.
        while self.run.running():
            for tid in self.post_queued_notes():
                print(f"[{now()}] Queued thread {tid[:8]} (agent busy)")
            time.sleep(self.interval)
        code = self.run.exit_code()
        if code:
            print(f"[{now()}] Warning: dispatch to {self.agent.name} failed (exit {code})")
        self.run = None
        self.end_run()

    def end_run(self, why="", say=True):
        """The run ended: the threads it didn't reply to are failed, and their progress notes say so."""
        try:
            failed = self.review.end_run()
        except StoreError:
            return
        for t in failed:
            if say:
                print(f"[{now()}] No reply to thread {t['id'][:8]} — it waits for your next comment")
            self.note_no_reply(t, int(time.time() - self.started), why)

    def stop_run(self, say=True):
        """Stop the run in progress, and every process it started."""
        if self.run and self.run.running():
            if say:
                print(f"Stopping running agent (pid {self.run.pid})...")
            self.run.stop()
            self.run = None
            self.end_run(" (the watcher stopped)", say=False)

    def post_queued_notes(self):
        posted = []
        for t in self._open_threads():
            if t["state"] != "queued" or self._has_queued_note(t):
                continue
            try:
                self.review.add_comment(t["id"], "queued", QUEUED_NOTE)
                posted.append(t["id"])
            except StoreError:
                pass
        return posted

    @staticmethod
    def _has_queued_note(thread):
        """A queued note was posted since the thread's last run."""
        kinds = [c["kind"] for c in thread["comments"]]
        since = len(kinds) - kinds[::-1].index("progress") if "progress" in kinds else 0
        return "queued" in kinds[since:]

    def note_no_reply(self, thread, secs, why=""):
        """The run's progress note on <thread> ends as failed, with "no reply" (and <why>)."""
        note = next((c for c in reversed(thread["comments"]) if c["kind"] == "progress"), None)
        failed = f"❌ **Failed** after {secs}s — no reply{why}"
        try:
            if note is None:
                self.review.add_comment(thread["id"], "progress", failed)
            elif note["body"].startswith("❌"):
                # The run already failed: keep why, and add that this thread got no reply
                self.review.edit_note(note["id"], "progress", f"{note['body']}\n\nNo reply{why}.")
            else:
                self.review.edit_note(note["id"], "progress", failed)
        except StoreError:
            pass
