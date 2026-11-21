#!/usr/bin/env python3
"""Run the tests side by side (standard library only).

    python3 tests/run.py            the full suite
    python3 tests/run.py fast       what a Lua-only change needs: the Neovim viewer's tests
    python3 tests/run.py test_watcher test_review_api.TheReviewApi   these modules, classes or tests

Worker processes import the test modules once each, then run one test at a time:
most of a test's time is waiting on the watcher, Neovim or git, so tests run side
by side. Each test makes its own temporary folders, HOME and ports, so no two
tests share state. The tests that start a watcher go first: they are the slowest.

-j sets the number of workers (default: the CPU count, at most 8). The exit code
is 0 when every test passed (skips count as passed, as with unittest).
"""
import argparse
import concurrent.futures
import multiprocessing
import os
import sys
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
FAST = ["test_neovim_viewer"]

_tests = {}  # in a worker: test id -> test


def _each(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _each(item)
        else:
            yield item


def _load(names):
    """The tests <names> names (modules, classes or tests; every test when there are none), by id,
    those that start a watcher first."""
    if TESTS not in sys.path:
        sys.path.insert(0, TESTS)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(names) if names else loader.discover(TESTS, top_level_dir=TESTS)
    tests = list(_each(suite))
    try:
        from test_watcher import Harness
        tests.sort(key=lambda t: not isinstance(t, Harness))
    except ImportError:
        pass
    return {t.id(): t for t in tests}


def _start_worker(names):
    _tests.update(_load(names))


def _run_one(test_id):
    """Run the test <test_id>: (its id, its outcome, its report, its seconds)."""
    result = unittest.TestResult()
    started = time.time()
    unittest.TestSuite([_tests[test_id]]).run(result)
    seconds = time.time() - started
    problems = [("ERROR", t, err) for t, err in result.errors] + [("FAIL", t, err) for t, err in result.failures]
    problems += [("FAIL", t, "unexpected success\n") for t in result.unexpectedSuccesses]
    if problems:
        report = "\n".join(f"{kind}: {t.id() if hasattr(t, 'id') else t}\n{err}" for kind, t, err in problems)
        return test_id, problems[0][0], report, seconds
    if result.skipped:
        return test_id, "skip", result.skipped[0][1], seconds
    return test_id, "ok", "", seconds


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("names", nargs="*", help='"fast", or test modules, classes or tests (default: every test)')
    parser.add_argument("-j", "--jobs", type=int, default=min(os.cpu_count() or 2, 8), help="worker processes")
    parser.add_argument("-v", "--verbose", action="store_true", help="name each test as it ends")
    parser.add_argument("--slowest", type=int, default=10, metavar="N", help="list the N slowest tests (0: none)")
    args = parser.parse_args(argv)
    names = [n for name in args.names for n in (FAST if name == "fast" else [name])]

    test_ids = list(_load(names))
    jobs = max(1, min(args.jobs, len(test_ids)))
    started = time.time()
    counts, failed, timings = {}, [], []
    with concurrent.futures.ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("spawn"),
                                                initializer=_start_worker, initargs=(names,)) as pool:
        running = [pool.submit(_run_one, test_id) for test_id in test_ids]
        try:
            for done in concurrent.futures.as_completed(running):
                test_id, outcome, report, seconds = done.result()
                counts[outcome] = counts.get(outcome, 0) + 1
                timings.append((seconds, test_id))
                if outcome in ("FAIL", "ERROR"):
                    failed.append(report)
                if args.verbose or outcome in ("FAIL", "ERROR"):
                    print(f"{outcome} {test_id} ({seconds:.1f}s)", flush=True)
                else:
                    print("." if outcome == "ok" else "s", end="", flush=True)
        except KeyboardInterrupt:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    print()
    for report in failed:
        print("=" * 70)
        print(report)
    if args.slowest:
        print(f"Slowest {min(args.slowest, len(timings))}:")
        for seconds, test_id in sorted(timings, reverse=True)[:args.slowest]:
            print(f"  {seconds:6.1f}s {test_id}")
    print("-" * 70)
    summary = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
    print(f"Ran {len(test_ids)} tests in {time.time() - started:.1f}s with {jobs} workers: {summary}")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
