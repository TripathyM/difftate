---
status: proposed
---

# The review is event-sourced in the core

A change to a review is recorded as domain events: facts in the past tense, such as "thread opened" or "comment added". The Review, the aggregate root, checks the rules and returns the events, and applying an event is the only way its state changes. The store port keeps the events (`load` and `append`), and the review history records the same events. Before, the store port had a method for each kind of change, and the change logic existed twice: the local store turned each call into an event line and replayed the lines, while the memory store changed its dicts directly. Now the logic exists once, in the core, the rules sit with the state they guard, and a new store needs two methods.

Proposed, not yet accepted: we check it against the first slice (opening a thread, end to end) before the other use cases move.

## Considered options

- **Store methods, as before.** Less to change, but every store copies the change logic, the rules sit apart from the state (an anemic model), and each use case must remember to record the review history.

## Consequences

- The local store keeps today's line format in `events.jsonl`, so existing reviews and the review history still load.
- A progress note changes many times during a run, and the local store keeps only final notes (`local.py:28-31`). The events must keep that, so the log does not fill with step-by-step edits.
- Thread state stays derived, never stored.
