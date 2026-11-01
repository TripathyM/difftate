"""Dispatch: send the waiting threads to the agent, one run at a time.

While a run works, threads that become waiting get a queued note right away.
The run's progress notes are kept by lib/stream_fmt.py through the review API.
"""
import hashlib
import json
import os
import time

import threads as thread_rules  # lib/threads.py: which threads wait, and the threads part of the prompt

from .agent import Run
from .diffity import StoreError

QUEUED_NOTE = "🕒 **Queued** — agent is busy with another comment, will pick this up next."

PROMPT = """New diffity review comments. Everything you need is below — do NOT run 'diffity agent list'.

{threads}

Rules:
- Reply to EVERY thread under 'Reply to these threads', with: diffity agent reply <id> --body "{reply} <answer>"
  The body MUST start with '{reply} ' — that's how the watcher knows the thread is answered.
- 'Other open threads' are context only, to spot related comments. Reply there only if what you do in this run also addresses it.
- Change code ONLY when the user explicitly asks ('fix this', 'rename X to Y', 'add X'). Then reply with what you changed (file:line).
- Questions: answer. Suggestions, 'should we…?', nits: give your take and ask before changing anything. Unclear: ask for clarification. Never skip a thread silently.
- NEVER resolve or dismiss threads. Never edit or delete comments starting with '{status}' or '{queued}' (watcher status).
- Lines starting 'you:' are your earlier replies. Read files as needed for context.
- Write replies in ASD-STE100 Simplified Technical English.
Summarize briefly what you handled."""


def now():
    return time.strftime("%H:%M:%S")


def build_prompt(open_threads, ids):
    return PROMPT.format(threads=thread_rules.prompt(open_threads, ids), reply=thread_rules.REPLY,
                         status=thread_rules.STATUS, queued=thread_rules.QUEUED)


class Dispatch:
    def __init__(self, store, agent, cwd, interval, api_url, token_file, healthy):
        self.store = store
        self.agent = agent
        self.cwd = cwd
        self.interval = interval
        self.api_url = api_url
        self.token_file = token_file
        self.healthy = healthy  # () -> None, or an error message to exit with
        self.run = None
        self.last_hash = None

    def _open_threads(self):
        try:
            return self.store.threads("open")
        except StoreError:
            return []

    def forever(self):
        """Runs until the store goes away (returns its message) or Ctrl+C."""
        while True:
            problem = self.healthy()
            if problem:
                return problem
            self.once()
            time.sleep(self.interval)

    def once(self):
        open_threads = self._open_threads()
        waiting = thread_rules.pending(open_threads)
        if not waiting:
            return
        digest = hashlib.sha256(json.dumps(waiting, sort_keys=True).encode()).hexdigest()
        if digest == self.last_hash:
            return
        print(f"[{now()}] New/changed threads detected — dispatching to {self.agent.name}")
        self.last_hash = digest

        ids = [t["id"] for t in waiting if t.get("id")]
        argv, said = self.agent.command(build_prompt(open_threads, ids))
        for line in said:
            print(line)
        # The progress notes go through the review API. Only the formatter gets the
        # token file, never the agent.
        fmt_env = dict(os.environ, DT_API=self.api_url, DT_TOKEN_FILE=self.token_file,
                       DT_THREAD_IDS=",".join(ids), DT_THREADS_JSON=json.dumps(waiting))
        self.run = Run(self.agent.name, argv, self.cwd, fmt_env)
        # Threads that arrive meanwhile get a queued note right away. Runs stay one at a time.
        while self.run.running():
            for tid in self.post_queued_notes(set(ids)):
                print(f"[{now()}] Queued thread {tid[:8]} (agent busy)")
            time.sleep(self.interval)
        code = self.run.exit_code()
        if code:
            print(f"[{now()}] Warning: dispatch to {self.agent.name} failed (exit {code})")
        self.run = None

    def post_queued_notes(self, busy):
        posted = []
        for t in thread_rules.pending(self._open_threads()):
            comments = t.get("comments") or []
            if t["id"] in busy or (comments and (comments[-1].get("body") or "").startswith(thread_rules.QUEUED)):
                continue
            try:
                self.store.add_note(t["id"], "queued", QUEUED_NOTE)
                posted.append(t["id"])
            except StoreError:
                pass
        return posted
