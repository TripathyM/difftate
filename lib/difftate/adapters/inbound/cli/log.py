"""The watcher's log: its standard output once it runs in the background. One
process serves every folder, and its folders' loops and requests print on
threads of their own, so each line says when it was written and which folder
and review it is about: the thread that prints says it (about). A line no folder
is about (the watcher's own) is "(watcher)"."""
import threading
import time

WATCHER = "(watcher)"


def stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class FolderLog:
    """A text stream over <out>: each line starts with "[<time>] <label>: ", the
    label the thread that prints it said (about(label), a function, as the review
    a folder shows changes with its branch), else WATCHER."""

    def __init__(self, out):
        self._out = out
        self._lock = threading.Lock()
        self._thread = threading.local()

    def about(self, label):
        """From now on, lines this thread prints are about <label>()."""
        self._thread.label = label

    def write(self, text):
        lines = (getattr(self._thread, "partial", "") + text).split("\n")
        self._thread.partial = lines.pop()  # up to the next newline
        label = getattr(self._thread, "label", None)
        who = label() if label else WATCHER
        with self._lock:
            for line in lines:
                self._out.write(f"[{stamp()}] {who}: {line}\n")
            self._out.flush()
        return len(text)

    def flush(self):
        pass

    def reconfigure(self, **kwargs):
        pass
