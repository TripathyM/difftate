"""The reply channel: the run's folder, where the coding agent leaves its
replies, and dt-reply, which writes them. Claude Code and OpenCode share it.

The coding agent answers a thread with `dt-reply <thread> "<answer>"` (bin/dt-reply).
That writes the answer into the run's folder ($DT_RUN_DIR); the coding agent's run
gives it to Dispatch as news, and Dispatch posts it as a reply. So the coding agent needs no token, no write access to the store, and
no marker: difftate knows the answer is a reply because of where it came from.

The folder (a temporary one per run, outside the repository):
  threads    the ids of the open threads the coding agent may reply to, one per line
  replies/   one JSON file per answer, {"thread", "body"}, named so they sort
             in the order they were written
"""
import json
import os
import shlex
import shutil
import tempfile
import time

THREADS = "threads"
REPLIES = "replies"
# The command the coding agent answers with
ROOT = os.path.abspath(__file__)
for _ in range(7):  # lib/difftate/adapters/outbound/coding_agents/reply_channel/__init__.py
    ROOT = os.path.dirname(ROOT)
DT_REPLY = os.path.join(ROOT, "bin", "dt-reply")
# As the prompt names it: ready for the coding agent's shell
REPLY_COMMAND = shlex.quote(DT_REPLY)


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

    def replies(self):
        """The replies not yet posted, oldest first: [(name, thread id, body)].
        A file that isn't a reply is removed."""
        replies_dir = os.path.join(self.path, REPLIES)
        try:
            names = sorted(n for n in os.listdir(replies_dir) if n.endswith(".json"))
        except OSError:
            return []
        found = []
        for name in names:
            try:
                with open(os.path.join(replies_dir, name)) as f:
                    reply = json.load(f)
            except OSError:
                continue
            except ValueError:
                reply = None
            if isinstance(reply, dict) and isinstance(reply.get("thread"), str) \
                    and isinstance(reply.get("body"), str):
                found.append((name, reply["thread"], reply["body"]))
            else:
                self.posted(name)
        return found

    def posted(self, name):
        """The reply <name> is done with: remove it."""
        try:
            os.remove(os.path.join(self.path, REPLIES, name))
        except OSError:
            pass

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
