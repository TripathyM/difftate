"""The local store: difftate's own, in the repository's git folder (see
difftate/local.py for the folder and its events.jsonl lines).

So far it holds only the line reader (lines.py), which turns today's
events.jsonl lines into the core's events. The store itself, behind the
core's port for keeping the review, comes next (#64).
"""
