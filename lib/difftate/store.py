"""What every store shares, whatever keeps the review."""

NOTE_KINDS = ("queued", "progress")
THREAD_STATUSES = ("open", "resolved", "dismissed")


class StoreError(Exception):
    """A request the store refused (status 4xx) or couldn't serve (502)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def need_text(value, name="body"):
    if not isinstance(value, str) or not value.strip():
        raise StoreError(400, f"need {name}")
    return value
