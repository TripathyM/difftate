"""The watcher's log: its standard output once it runs in the background. One
process serves every folder, and its folders' loops and requests print on
threads of their own, so each line says which folder and review it is about:
the thread that prints says it (about)."""
import threading


class FolderLog:
    """A text stream over <out>: a line printed on a thread that said what it is
    about (about(label)) starts with "<label>: "."""

    def __init__(self, out):
        self._out = out
        self._lock = threading.Lock()
        self._thread = threading.local()

    def about(self, label):
        """From now on, lines this thread prints are about <label>() (a function,
        as the review a folder shows changes with its branch)."""
        self._thread.label = label

    def write(self, text):
        lines = (getattr(self._thread, "partial", "") + text).split("\n")
        self._thread.partial = lines.pop()  # up to the next newline
        label = getattr(self._thread, "label", None)
        prefix = f"{label()}: " if label else ""
        with self._lock:
            for line in lines:
                self._out.write(f"{prefix}{line}\n" if line else "\n")
            self._out.flush()
        return len(text)

    def flush(self):
        pass

    def reconfigure(self, **kwargs):
        pass
