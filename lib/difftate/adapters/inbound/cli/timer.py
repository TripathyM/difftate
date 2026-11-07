"""The timer: it runs the loop every --interval (the driving port for running
the loop)."""
import time


def every(interval, poll):
    """<poll>() every <interval> seconds, until something stops it (Ctrl+C)."""
    while True:
        poll()
        time.sleep(interval)
