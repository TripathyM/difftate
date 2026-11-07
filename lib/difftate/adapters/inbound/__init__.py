"""Driving adapters: they call the core's use cases (ADR 0003).

review_api/ is for reviewing: the review API that viewers and scripts use,
with web/. It owns the JSON thread format and maps core errors to HTTP status
codes (not allowed 403, not found 404, conflict 409, could not read 502).
cli/ is the command line, which starts the watcher that runs the loop.
"""
