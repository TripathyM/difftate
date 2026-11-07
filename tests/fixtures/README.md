# Test fixtures

Recorded from difftate before the review API ran on the new core (#66), so
the tests can still compare with what it did once the old code was deleted.
Only regenerate one when the published language or the stored format
changes on purpose.

- `review_api_script.json`: every review API answer (status and JSON) to the
  scripted review in `tests/test_review_api.py`, with ids, times and hashes
  named by where they first appear. `DT_RECORD=1` rewrites it.
- `todays-review/`: a review written by the old `LocalStore` (`local.py` at
  1baede2), with every kind of line it wrote (the script that was
  `write_a_review` in `tests/test_core_replay.py`):
  - `events.jsonl`: its events file.
  - `history.jsonl`: the review history lines it wrote, with the `ABOUT` of
    `tests/test_history_files.py`.
  - `read-today.json`: what the old `LocalStore` read back from it (threads,
    runs, viewed marks) and, after the old Review recovered its runs, which
    threads failed and every thread's state.
