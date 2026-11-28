"""Layout D's line cursor and Vim jumps (#264, web/d/cursor.js): where each goes, as a computed
target (file and row of the Files changed tab's model). Node runs it."""
import json
import shutil
import unittest

from browser_d import answers, changed, run_js

# Unified rows of a.py: 0 hunk, 1 line 1, 2 old 2, 3 new 2, 4 line 3, 5 line 4, 6 hunk,
# 7 line 10, 8 new 11, 9 old 11 / new 12
A = changed("a.py", "@@ -1,4 +1,4 @@", " one", "-two", "+TWO", " three", " four",
            "@@ -10,2 +10,3 @@", " ten", "+ten and a half", " eleven")
B = changed("b.py", "@@ -1 +1 @@", "-old", "+new")


def spot(file, side, line):
    return {"file": file, "side": side, "line": line}


def target(file, row):
    return {"file": file, "row": row}


@unittest.skipUnless(shutil.which("node"), "needs node")
class Cursor(unittest.TestCase):
    layout = "unified"

    def run_cursor(self, expression, diff=A + B, viewed=(), threads=()):
        """<expression> over <files>, the Files changed tab's files, and <state>."""
        poll = answers(changeset={"view": "", "diff": diff, "versions": {}}, viewed=list(viewed), threads=list(threads))
        return run_js("cursor", f"""
const {{ initialState, polled, setLayout }} = await import("{{STATE}}");
const {{ filesChanged }} = await import("{{FILES}}");
const state = setLayout(polled(initialState("files"), {json.dumps(poll)}), {json.dumps(self.layout)});
const files = filesChanged(state).files;
console.log(JSON.stringify({expression}));""")


class MovingTheCursor(Cursor):
    def test_the_first_press_puts_it_on_the_first_line_on_screen(self):
        got = self.run_cursor(f'm.move(files, {json.dumps(target("a.py", 4))}, 1)')

        self.assertEqual(got, {"spot": spot("a.py", "new", 3), "target": target("a.py", 4)})

    def test_down_and_up_go_line_by_line_over_hunk_heads_and_into_the_next_file(self):
        got = self.run_cursor(f"""[1, 2, 3, -1].map((by) => m.move(files, {json.dumps(spot("a.py", "new", 3))}, by))
  .concat(m.move(files, {json.dumps(spot("a.py", "new", 12))}, 1))""")

        self.assertEqual([g["spot"] for g in got],
                         [spot("a.py", "new", 4), spot("a.py", "new", 10), spot("a.py", "new", 11),
                          spot("a.py", "new", 2), spot("b.py", "old", 1)])
        self.assertEqual(got[1]["target"], target("a.py", 7))

    def test_it_stops_at_the_first_and_last_line_and_skips_a_folded_file(self):
        got = self.run_cursor(f"""[m.move(files, {json.dumps(spot("a.py", "new", 1))}, -9),
  m.move(files, {json.dumps(spot("a.py", "new", 12))}, 9)]""", viewed=["b.py"])

        self.assertEqual([g["spot"] for g in got], [spot("a.py", "new", 1), spot("a.py", "new", 12)])

    def test_gg_and_G_are_the_first_and_last_line(self):
        got = self.run_cursor("[m.toEnd(files, null, false), m.toEnd(files, null, true)]")

        self.assertEqual(got, [{"spot": spot("a.py", "new", 1), "target": target("a.py", 1)},
                               {"spot": spot("b.py", "new", 1), "target": target("b.py", 2)}])

    def test_while_selecting_it_stays_in_the_file_on_the_side_it_started_on(self):
        anchor = json.dumps(spot("a.py", "new", 3))
        got = self.run_cursor(f"""[m.move(files, {anchor}, -2, {anchor}), m.move(files, {anchor}, 99, {anchor}),
  m.toEnd(files, {anchor}, false, {anchor})]""")

        self.assertEqual([g["spot"] for g in got],
                         [spot("a.py", "new", 1), spot("a.py", "new", 12), spot("a.py", "new", 1)])

    def test_with_no_line_on_screen_there_is_nowhere_to_go(self):
        self.assertIsNone(self.run_cursor("m.move(files, null, 1)", viewed=["a.py", "b.py"]))


class MovingInSplitView(Cursor):
    layout = "split"

    def test_h_and_l_pick_the_side_and_moving_keeps_it(self):
        # Split rows of a.py: 0 hunk, 1 line 1, 2 old 2 | new 2, 3 line 3
        got = self.run_cursor(f"""(() => {{
  const old = m.pickSide(files, {json.dumps(spot("a.py", "new", 2))}, "old");
  const down = m.move(files, old.spot, 1);
  const back = m.pickSide(files, m.move(files, down.spot, -1).spot, "new");
  return [old, down, back];
}})()""")

        self.assertEqual(got[0], {"spot": dict(spot("a.py", "old", 2), want="old"), "target": target("a.py", 2)})
        self.assertEqual(got[1]["spot"], dict(spot("a.py", "old", 3), want="old"))
        self.assertEqual(got[2]["spot"], dict(spot("a.py", "new", 2), want="new"))

    def test_a_row_with_nothing_on_the_side_wanted_gives_its_other_one(self):
        got = self.run_cursor(f'm.move(files, {json.dumps(dict(spot("a.py", "old", 10), want="old"))}, 1)')

        self.assertEqual(got["spot"], dict(spot("a.py", "new", 11), want="old"))


class JumpingBetweenChanges(Cursor):
    def jumps(self, start, *bys, **more):
        return self.run_cursor(f"""(() => {{
  let from = {json.dumps(start)};
  return {json.dumps(list(bys))}.map((by) => {{
    const got = m.nextChange(files, from, by);
    from = got.spot;
    return [got.target, got.wrapped];
  }});
}})()""", **more)

    def test_next_and_previous_change_go_to_the_first_line_of_each_and_wrap_round(self):
        got = self.jumps(spot("a.py", "new", 1), 1, 1, 1, 1, -1)

        self.assertEqual(got, [[target("a.py", 2), False], [target("a.py", 8), False], [target("b.py", 1), False],
                               [target("a.py", 2), True], [target("b.py", 1), True]])

    def test_from_the_first_line_on_screen_a_change_there_is_the_next_one(self):
        got = self.jumps(target("a.py", 2), 1)

        self.assertEqual(got, [[target("a.py", 2), False]])

    def test_changes_in_two_hunks_are_two(self):
        two = changed("c.py", "@@ -1 +1 @@", "-a", "+b", "@@ -9 +9 @@", "-c", "+d")

        got = self.jumps(spot("c.py", "old", 1), 1, diff=two)

        self.assertEqual(got, [[target("c.py", 4), False]])


class JumpingBetweenFiles(Cursor):
    def test_next_and_previous_file_wrap_round(self):
        got = self.run_cursor("""[["a.py", 1], ["b.py", 1], ["a.py", -1], [null, 1], [null, -1]]
  .map(([path, by]) => m.nextFile(files, path, by))""")

        self.assertEqual(got, ["b.py", "a.py", "b.py", "a.py", "b.py"])

    def test_a_files_first_line_is_where_the_cursor_lands(self):
        got = self.run_cursor('m.firstIn(files, "b.py")')

        self.assertEqual(got, {"spot": spot("b.py", "old", 1), "target": target("b.py", 1)})


def thread(tid, file=None, line=1, side="new", **more):
    anchor = None if file is None else {"file": file, "side": side, "startLine": line, "endLine": line, "code": "x"}
    return dict({"id": tid, "anchor": anchor, "status": "open", "state": "replied", "outdated": False,
                 "comments": [{"id": f"c-{tid}", "author": "reviewer", "body": tid, "time": "2026-01-01T00:00:00Z"}]}, **more)


class JumpingBetweenThreads(Cursor):
    THREADS = [thread("in-b", "b.py", 1), thread("later", "a.py", 11), thread("general"),
               thread("closed", "a.py", 3, status="resolved"), thread("old-code", "a.py", 4, outdated=True),
               thread("earlier", "a.py", 3), thread("gone", "z.py", 1), thread("elsewhere", "a.py", 1, inView=False)]

    def steps(self, here, *bys):
        return self.run_cursor(f"""(() => {{
  let here = {json.dumps(here)};
  return {json.dumps(list(bys))}.map((by) => {{
    const got = m.nextThread(files, state.server.threads, here, by);
    here = {{ thread: got.thread.id }};
    return [got.thread.id, got.target, got.wrapped];
  }});
}})()""", threads=self.THREADS)

    def test_open_threads_in_review_order_general_ones_first_then_by_file_and_line(self):
        got = self.steps(None, 1, 1, 1, 1, 1, 1)

        self.assertEqual([[tid, wrapped] for tid, _, wrapped in got],
                         [["general", False], ["old-code", False], ["earlier", False], ["later", False],
                          ["in-b", False], ["general", True]])

    def test_each_goes_to_its_place_in_files_changed_a_general_one_has_none(self):
        got = dict((tid, at) for tid, at, _ in self.steps(None, 1, 1, 1, 1))

        self.assertEqual(got["general"], None)
        self.assertEqual(got["old-code"], target("a.py", None))  # outdated: the file's top
        self.assertEqual(got["earlier"], target("a.py", 4))

    def test_from_the_cursor_the_next_one_after_its_line_or_before_it(self):
        here = spot("a.py", "new", 10)

        self.assertEqual(self.steps(here, 1)[0][0], "later")
        self.assertEqual(self.steps(here, -1)[0][0], "earlier")

    def test_a_focused_thread_that_closed_leaves_the_place_the_cursor_is(self):
        got = self.steps(dict(spot("a.py", "new", 10), thread="closed"), 1)

        self.assertEqual(got[0][0], "later")

    def test_with_no_open_thread_there_is_none(self):
        self.assertIsNone(self.run_cursor("m.nextThread(files, [], null, 1)"))

    def test_the_threads_on_the_cursors_line(self):
        got = self.run_cursor(f"""[{json.dumps(spot("a.py", "new", 3))}, {json.dumps(spot("a.py", "old", 3))},
  {json.dumps(spot("a.py", "new", 4))}, null].map((s) => m.threadsAt(state.server.threads, s).map((t) => t.id))""",
                              threads=self.THREADS)

        self.assertEqual(got, [["closed", "earlier"], [], [], []])


if __name__ == "__main__":
    unittest.main()
