# Test fixtures

Recorded from difftate before the review API ran on the new core (#66), so
the tests can still compare with what it did once the old code was deleted.
Only regenerate one when the published language or the stored format
changes on purpose.

- `review_api_script.json`, the current transcript: every review API answer
  (status and JSON) to the scripted review in `tests/test_review_api.py`, with
  ids, times and hashes named by where they first appear. `DT_RECORD=1`
  rewrites it. A test fails when the script gets no 200 from a route the API
  has.
- `review_api_released.json`, the released transcript: what the review API has
  published. The API only grows (ADR 0010): a test fails when a route, status,
  field or value kind in it is gone from the current transcript, and names it.
  Extra ones pass, but nothing protects them until they are released.
  `DT_RECORD=1` never writes this file. To release an addition, in the same
  pull request, on purpose:

  ```sh
  cp tests/fixtures/review_api_script.json tests/fixtures/review_api_released.json
  ```

  Never copy it to get a removal or a rename past the test. That is a break,
  and needs a new version of the API beside the old one.
- `todays-review/`: a review written by the old `LocalStore` (`local.py` at
  1baede2), with every kind of line it wrote (the script that was
  `write_a_review` in `tests/test_core_replay.py`):
  - `events.jsonl`: its events file.
  - `history.jsonl`: the review history lines it wrote, with the `ABOUT` of
    `tests/test_history_files.py`.
  - `read-today.json`: what the old `LocalStore` read back from it (threads,
    runs, viewed marks) and, after the old Review recovered its runs, which
    threads failed and every thread's state.
