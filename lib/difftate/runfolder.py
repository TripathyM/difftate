"""The run's folder: where the coding agent leaves its replies for Dispatch.

The coding agent answers a thread with `dt-reply <thread> "<answer>"` (bin/dt-reply).
That writes the answer into the run's folder ($DT_RUN_DIR), and Dispatch posts
it as a reply. So the coding agent needs no token, no write access to the store, and
no marker: difftate knows the answer is a reply because of where it came from.

The folder (a temporary one per run, outside the repository):
  threads    the ids of the open threads the coding agent may reply to, one per line
  replies/   one JSON file per answer, {"thread", "body"}, named so they sort
             in the order they were written
"""
import json
import os
import shutil
import tempfile
import time

THREADS = "threads"
REPLIES = "replies"
# The command the coding agent answers with
DT_REPLY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bin", "dt-reply")


class ReplyError(Exception):
    pass


class RunFolder:
    def __init__(self, path):
        self.path = path

    @classmethod
    def create(cls, thread_ids):
        """A new run's folder, for replies to <thread_ids>."""
        folder = cls(os.path.realpath(tempfile.mkdtemp(prefix="difftate-run-")))
        os.makedirs(os.path.join(folder.path, REPLIES))
        with open(os.path.join(folder.path, THREADS), "w") as f:
            f.write("".join(f"{tid}\n" for tid in thread_ids))
        return folder

    def take_replies(self):
        """The replies written since the last call, oldest first: [(thread id, body)]."""
        replies_dir = os.path.join(self.path, REPLIES)
        try:
            names = sorted(n for n in os.listdir(replies_dir) if n.endswith(".json"))
        except OSError:
            return []
        taken = []
        for name in names:
            path = os.path.join(replies_dir, name)
            try:
                with open(path) as f:
                    reply = json.load(f)
                os.remove(path)
            except (OSError, ValueError):
                continue
            if isinstance(reply, dict) and isinstance(reply.get("thread"), str) \
                    and isinstance(reply.get("body"), str):
                taken.append((reply["thread"], reply["body"]))
        return taken

    def write_reply(self, thread_id, body):
        """Leave the coding agent's answer to the thread <thread_id> (or the start of
        its id) for Dispatch (dt-reply). Returns the thread's full id."""
        try:
            with open(os.path.join(self.path, THREADS)) as f:
                ids = [line.strip() for line in f if line.strip()]
        except OSError:
            raise ReplyError(f"no run's folder at {self.path}")
        matches = [tid for tid in ids if tid.startswith(thread_id)] if thread_id else []
        if len(matches) != 1:
            raise ReplyError(f"no open thread {thread_id!r}" if not matches
                             else f"{thread_id!r} matches several threads")
        if not body.strip():
            raise ReplyError("the answer is empty")
        replies_dir = os.path.join(self.path, REPLIES)
        name = f"{time.time_ns():020d}-{os.getpid()}"
        tmp = os.path.join(replies_dir, name + ".tmp")
        with open(tmp, "w") as f:
            json.dump({"thread": matches[0], "body": body}, f)
        os.replace(tmp, os.path.join(replies_dir, name + ".json"))
        return matches[0]

    def remove(self):
        shutil.rmtree(self.path, ignore_errors=True)
