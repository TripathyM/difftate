"""One run of a coding agent, as a process: its output is read into news on
a thread of its own, and its replies come through the reply channel."""
from __future__ import annotations

import io
import os
import queue
import subprocess
import threading
from typing import Dict, List, Sequence

from ....core.dispatch.model import ContextUsed, CouldNotStart, Exited, News, Reply
from .events import ReadsEvents, read_line
from .processes import STOP_GRACE_S, stop_tree
from .reply_channel import RunFolder


class ProcessRun:
    """The coding agent's process, started in its own process session, with
    <first> as its first news. <channel> is the run's folder, removed once
    the run is over."""

    def __init__(self, argv: Sequence[str], cwd: str, env: Dict[str, str], events: ReadsEvents,
                 channel: RunFolder, first: Sequence[News] = ()):
        self.channel = channel
        self._news: "queue.SimpleQueue[News]" = queue.SimpleQueue()
        for news in first:
            self._news.put(news)
        try:
            self.proc = subprocess.Popen(list(argv), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, start_new_session=True)
        except OSError as e:
            channel.remove()
            raise CouldNotStart(str(e))
        self.pid = self.proc.pid
        self._reader = threading.Thread(target=self._read, args=(events,), daemon=True)
        self._reader.start()
        self._over = False
        self._stopped = False

    def _read(self, events: ReadsEvents) -> None:
        assert self.proc.stdout is not None
        with io.TextIOWrapper(self.proc.stdout, encoding="utf-8", errors="replace") as lines:
            for line in lines:
                for news in read_line(line, events):
                    self._news.put(news)

    def news(self) -> List[News]:
        if self._over:
            return []
        # Read before taking the news: once the output is read to its end and
        # the process is gone, every news item is queued. A stopped run is
        # over once its process is, even if something it started still holds
        # its output open.
        over = self.proc.poll() is not None and (self._stopped or not self._reader.is_alive())
        found: List[News] = []
        while True:
            try:
                found.append(self._news.get_nowait())
            except queue.Empty:
                break
        for name, thread_id, body in self.channel.replies():
            found.append(Reply(thread_id, body))
            self.channel.posted(name)
        if over:
            self._over = True
            self.channel.remove()
            found.append(Exited(self.proc.returncode))
        return found

    def stop(self) -> None:
        self._stopped = True
        stop_tree(self.proc)
        self._reader.join(timeout=STOP_GRACE_S)


def context_window() -> List[News]:
    """The context window, for a coding agent that doesn't report it
    (DT_CONTEXT_WINDOW)."""
    try:
        window = int(os.environ.get("DT_CONTEXT_WINDOW") or 0)
    except ValueError:
        window = 0
    return [ContextUsed(window=window)] if window else []
