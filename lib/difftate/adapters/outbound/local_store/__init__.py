"""The local store: difftate's own, in the repository's git folder. It plugs
into the core's port for keeping the review.

store.py is the store (the review's folder, and the tamper check); lines.py
turns the core's events into today's events.jsonl lines and back.
"""
from .store import LocalStore, review_id

__all__ = ["LocalStore", "review_id"]
