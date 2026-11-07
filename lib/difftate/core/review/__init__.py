"""The Review context: threads, comments, anchors, thread status and state,
viewed files, and the review history (GLOSSARY.md, Review).

The Review is the aggregate root. ADR 0004 has it check the thread
rules and return domain events, so that applying an event is the only way its
state changes.
Its driven ports are for keeping the review (load, append) and for recording
review history (record). Its use cases are for reviewing: open a thread, add a
comment, set a status, mark a file viewed, list threads and viewed files.
"""
