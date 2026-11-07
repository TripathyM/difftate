"""The Dispatch context: waiting threads, queued notes, one run at a time,
steps, progress notes and the prompt (GLOSSARY.md, Dispatch).

model.py holds the news a run gives, the notes' texts and what Dispatch keeps
between polls. Its driven ports (ports.py) are for asking the coding agent
(start a run, read its news, stop it) and for reporting (the lines the
watcher prints). Its use cases are for running the loop: poll (what the
timer calls) runs dispatch_waiting, move_with_code, read_news, post_replies,
edit_progress_note and end_run; recover_runs ends a run whose watcher was
killed. Dispatch changes the review only through the Review's use cases.
"""
