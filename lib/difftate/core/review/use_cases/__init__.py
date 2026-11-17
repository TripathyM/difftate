"""The Review's use cases: one plain function per file.

For reviewing: open_thread, add_comment, edit_note, set_status, mark_viewed,
list_threads, list_viewed, set_done and read_done. For running the loop, what
Dispatch does to the review: move_with_code, clear_done, start_run, end_run
and recover_runs.

Each function takes the driven ports it needs first, then what the caller
asks for. The function is the driving port: an inbound adapter (the review
API) or Dispatch calls it, with the ports bound once by the composition root
(functools.partial, in main.bind_review).
"""
