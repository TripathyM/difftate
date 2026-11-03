"""Dispatch: send the waiting threads to the coding agent, one run at a time.

While a run works, threads that become waiting get a queued note right away.
Before a run starts, Dispatch posts a progress note on each of its threads, and
the store keeps the run (which comments it was sent). lib/stream_fmt.py edits
the notes through the review API while the run works.
The coding agent answers with dt-reply into the run's folder, and Dispatch posts each
answer as a reply, during the run and when it ends.
When the run ends (done, failed, or stopped by Ctrl+C), Dispatch writes each
progress note's final line. A thread the run didn't reply to is failed ("no
reply"): its progress note says so, and it isn't sent again until the reviewer comments.
A run whose watcher was killed is ended by the next watcher: its threads with
no reply are failed the same way.
"""
import json
import os
import time

from . import prompt
from .agent import Run, RunAccess
from .runfolder import RunFolder
from .store import StoreError

QUEUED_NOTE = "🕒 **Queued** — agent is busy with another comment, will pick this up next."
PICKED_UP_NOTE = "🕒 **Queued** — picked up by the next run (below)."
THINKING_NOTE = "⏳ **Thinking…** (0s)"
TAMPERED = ("⚠️ The stored review was changed outside difftate during this run "
            "(only difftate may write it): difftate restored it.")


def now():
    return time.strftime("%H:%M:%S")


class Dispatch:
    def __init__(self, review, agent, cwd, review_folder, interval, api, problem):
        self.review = review
        self.agent = agent
        self.cwd = cwd
        self.review_folder = review_folder  # the store and the token: kept out of the coding agent's reach
        self.interval = interval
        self.api = api  # ApiAddress, for the progress notes
        self.problem = problem  # () -> None, or why the watcher must exit
        self.run = None
        self.run_folder = None  # where the coding agent leaves its replies
        self.reply_to = frozenset()  # the threads the run in progress may reply to
        self.started = None  # when the run in progress started
        self.notes = {}  # thread id: its progress note, for the run in progress
        self.tampered = set()  # threads whose stored lines were changed outside difftate during the run

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
        self.reply_to = frozenset(t["id"] for t in open_threads)
        self.started = time.time()
        self.run_folder = RunFolder.create(self.reply_to)
        access = RunAccess(write=[self.run_folder.path], deny_write=[self.review_folder], deny_read=[self.api.token_file])
        argv, said = self.agent.command(prompt.build(open_threads, ids, new_ids), access)
        for line in said:
            print(line)
        # A thread that ends in its queued note gets that note back as its progress note
        queued = {t["id"]: t["comments"][-1]["id"] for t in waiting if t["comments"][-1]["kind"] == "queued"}
        self.close_queued_notes(waiting, queued)
        self.notes = self.post_progress_notes(waiting, queued)
        # The formatter edits the progress notes through the review API. Only the
        # formatter gets the token file, never the coding agent.
        fmt_env = dict(os.environ, **self.api.env(), DT_NOTES=json.dumps(self.notes))
        agent_env = dict(os.environ, DT_RUN_DIR=self.run_folder.path)
        try:
            self.review.start_run(waiting)
        except StoreError as e:
            print(f"[{now()}] Warning: could not record the run ({e}): a restarted watcher may send it again")
        try:
            self.run = Run(self.agent.name, argv, self.cwd, fmt_env, agent_env)
        except OSError as e:
            # A prompt too long for the command line, or a --cmd that can't run any more
            print(f"[{now()}] Warning: could not start {self.agent.name}: {e}")
            self.end_run(f" (could not start {self.agent.name}: {e})", outcome="failed")
            return
        # Threads that arrive meanwhile get a queued note right away. Runs stay one at a time.
        while self.run.running():
            self.post_replies()
            for tid in self.post_queued_notes():
                print(f"[{now()}] Queued thread {tid[:8]} (agent busy)")
            time.sleep(self.interval)
        code = self.run.exit_code()
        if code:
            print(f"[{now()}] Warning: dispatch to {self.agent.name} failed (exit {code})")
        self.run = None
        self.end_run(outcome="failed" if code else "done")

    def post_replies(self, last_try=False):
        """Post the answers the coding agent left in the run's folder as replies.

        Only threads that were open when the run started get one: the coding agent
        can write anything into its folder. A reply the store refuses stays for
        the next try; after the last one it is printed, so it isn't lost."""
        for name, tid, body in self.run_folder.replies() if self.run_folder else []:
            if tid not in self.reply_to:
                print(f"[{now()}] Warning: dropped a reply to thread {tid[:8]}: it isn't open in this run")
                self.run_folder.posted(name)
                continue
            try:
                self.review.add_comment(tid, "reply", body)
            except StoreError as e:
                if last_try:
                    print(f"[{now()}] Warning: could not post the reply to thread {tid[:8]} ({e}). The reply:")
                    print(body)
                continue
            self.run_folder.posted(name)

    def post_progress_notes(self, threads, queued):
        """A progress note on each of <threads> ({thread id: note id}). A thread
        that ends in its queued note (<queued>) gets that note back."""
        notes = {}
        for t in threads:
            try:
                if t["id"] in queued:
                    note = self.review.edit_note(queued[t["id"]], "progress", THINKING_NOTE)
                else:
                    note = self.review.add_comment(t["id"], "progress", THINKING_NOTE)
                notes[t["id"]] = note["id"]
            except StoreError as e:
                print(f"[{now()}] Warning: could not post the progress note on thread {t['id'][:8]} ({e})")
        return notes

    def end_run(self, why="", say=True, stopped=False, outcome="done"):
        """The run ended: its last replies are posted, the threads it didn't reply
        to are failed, and every progress note gets its final line."""
        self.post_replies(last_try=True)
        if self.run_folder:
            self.run_folder.remove()
            self.run_folder = None
        self.reply_to = frozenset()
        notes, self.notes = self.notes, {}
        secs = int(time.time() - self.started)
        try:
            failed = self.review.end_run("stopped" if stopped else outcome)
            threads = {t["id"]: t for t in self.review.threads()}
        except StoreError:
            self.tampered = set()
            return
        for t in failed:
            if say:
                print(f"[{now()}] No reply to thread {t['id'][:8]} — it waits for your next comment")
            self.note_no_reply(t, secs, why, notes.get(t["id"]))
        failed_ids = {t["id"] for t in failed}
        for tid, note_id in notes.items():
            if tid not in failed_ids and tid in threads:
                self.finish_note(threads[tid], note_id, secs, stopped)
        self.tampered = set()

    def finish_note(self, thread, note_id, secs, stopped):
        """The final line of a progress note on a thread the run didn't fail. It is
        the formatter's, unless the formatter didn't get to finish it."""
        note = next((c for c in thread["comments"] if c["id"] == note_id), None)
        if note is None:
            return
        body = note["body"]
        if body.startswith("⏳"):
            body = f"⏹ **Stopped** after {secs}s (the watcher stopped)" if stopped else f"✅ **Done** in {secs}s"
        self._final(thread["id"], note_id, body)

    def _final(self, thread_id, note_id, body):
        if thread_id in self.tampered:
            body += f"\n\n{TAMPERED}"
        try:
            self.review.edit_note(note_id, "progress", body, final=True)
        except StoreError:
            pass

    def close_interrupted(self, threads):
        """<threads> were in a run whose watcher was killed, and got no reply."""
        for t in threads:
            print(f"[{now()}] No reply to thread {t['id'][:8]} — the watcher stopped during its run")
            self.note_no_reply(t, None, " (the watcher stopped)")

    def warn_tampered(self, thread_ids):
        """Stored lines were changed outside difftate (and restored): a run in
        progress says so in the final progress notes of the threads they name."""
        if self.notes:
            self.tampered.update(thread_ids)

    def stop_run(self, say=True):
        """Stop the run in progress, and every process it started. A run whose
        coding agent already exited (Ctrl+C before Dispatch saw it) still ends:
        its last replies are posted."""
        if self.run and self.run.running():
            if say:
                print(f"Stopping running agent (pid {self.run.pid})...")
            self.run.stop()
        self.run = None
        if self.run_folder:
            self.end_run(" (the watcher stopped)", say=False, stopped=True)

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

    def close_queued_notes(self, threads, reused):
        """A queued note that a later comment pushed up the thread can't become the
        progress note (that must come after every comment the run is sent), so it
        says the run picked the thread up instead."""
        for t in threads:
            for c in t["comments"]:
                if c["kind"] == "queued" and c["id"] != reused.get(t["id"]) and c["body"] == QUEUED_NOTE:
                    try:
                        self.review.edit_note(c["id"], "queued", PICKED_UP_NOTE)
                    except StoreError:
                        pass

    @staticmethod
    def _has_queued_note(thread):
        """A queued note was posted since the thread's last run."""
        kinds = [c["kind"] for c in thread["comments"]]
        since = len(kinds) - kinds[::-1].index("progress") if "progress" in kinds else 0
        return "queued" in kinds[since:]

    def note_no_reply(self, thread, secs, why="", note_id=None):
        """The run's progress note on <thread> (<note_id>; a new one when it has
        none) ends as failed, with "no reply" (and <why>). <secs> is None when
        the run's length isn't known."""
        note = next((c for c in thread["comments"] if c["id"] == note_id), None) if note_id else None
        failed = f"❌ **Failed**{'' if secs is None else f' after {secs}s'} — no reply{why}"
        try:
            if note is None:
                note = self.review.add_comment(thread["id"], "progress", failed)
                body = failed
            elif note["body"].startswith("❌"):
                # The run already failed: keep why, and add that this thread got no reply
                body = f"{note['body']}\n\nNo reply{why}."
            else:
                body = failed
        except StoreError:
            return
        self._final(thread["id"], note["id"], body)
