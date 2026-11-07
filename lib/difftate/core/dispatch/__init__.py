"""The Dispatch context: waiting threads, queued notes, one run at a time,
steps, progress notes and the prompt (GLOSSARY.md, Dispatch).

Its driven ports are for asking the coding agent (start a run, read its news,
stop it) and for reporting (the lines the watcher prints). Its use cases are
for running the loop: dispatch waiting threads, move threads with their code,
post replies, edit the progress note, end a run and recover runs.
"""
