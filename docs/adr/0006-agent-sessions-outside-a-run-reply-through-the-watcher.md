---
status: accepted
---

# Agent sessions outside a run reply through the watcher, never to the store

A reviewer can export a review into an agent session they start themselves, and that session replies on the review's threads. Its replies go to the watcher of the review's folder, which posts them as it posts a run's replies; `dt-reply` never writes to the store. So the store keeps one writer, and a coding agent still needs no token or write access to it. The cost: an exported session can reply only while that folder's watcher runs, and `dt-reply` says so when none does.

## Considered options

- **`dt-reply` writes the reply to the store itself** when it runs outside a run. It works with no watcher, but every coding agent then gets write access to the store, and the store has two writers to keep consistent.

## Consequences

- An exported session may reply to any thread of the review, open, resolved or dismissed; its reply changes no thread status, since only a reviewer does. A thread id from another review is refused.
- Exporting claims no threads. In a live review a new comment still dispatches a run, even on a thread an exported session works on; a reviewer who doesn't want that switches the review to batched.
