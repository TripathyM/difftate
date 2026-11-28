// Layout D's diff: the rows of one file, unified. DOM-free: draw_files.js draws them.

/** The rows of <file> (diff.js, parseDiff): for each hunk {kind: "hunk", text}, then its lines
 *  {kind: "line", type: "context"|"add"|"delete", old, new (the line's number on each side, or
 *  null), text}. A binary file, or one with no changed lines, has one {kind: "note", text}. */
export function diffRows(file) {
  if (file.isBinary || !file.hunks.length) return [{ kind: "note", text: file.isBinary ? "Binary file" : "No changes to its lines" }];
  return file.hunks.flatMap((hunk) => [
    { kind: "hunk", text: hunk.header },
    ...hunk.lines.map((l) => ({ kind: "line", type: l.type, old: l.oldLineNumber, new: l.newLineNumber, text: l.content })),
  ]);
}

/** The text of each line of <side> that <rows> show, by its number. */
export const linesShown = (rows, side) => new Map(rows.filter((r) => r.kind === "line" && r[side] !== null).map((r) => [r[side], r.text]));

/** The code of the lines <start> to <end> of <side> as <rows> show it, joined with newlines as an
 *  anchor's code is, or null when they don't show every one. */
export function codeOn(rows, side, start, end) {
  const text = linesShown(rows, side);
  const lines = [];
  for (let n = start; n <= end; n++) {
    if (!text.has(n)) return null;
    lines.push(text.get(n));
  }
  return lines.join("\n");
}

/** <rows> (diffRows) of the file at <path>, with its threads and drafts (drafts.js) placed:
 *  {top: {threads, drafts}, rows}. After a line that something sits under comes {kind: "below",
 *  old, new (the line's numbers), threads, drafts}, the old side's first: a thread under the last
 *  of its lines shown. At the top: an outdated
 *  thread, whose lines now hold other code, and a draft whose lines no longer hold the code it
 *  was started on. A thread with no line here is on neither: the Conversation tab lists it. */
export function withThreads(rows, { path, threads = [], drafts = [] }) {
  const mine = threads.filter((t) => t.anchor?.file === path);
  const placeable = mine.filter((t) => !t.outdated && t.inView !== false);
  const myDrafts = drafts.filter((d) => d.anchor.path === path);
  const whole = myDrafts.filter(({ anchor: a }) => codeOn(rows, a.side, a.start, a.end) === a.code);
  const placed = new Set();
  // A hunk may leave out a range's last lines: the thread then sits under the last one shown
  const lastShown = ({ side, startLine, endLine }) => Math.max(...[...linesShown(rows, side).keys()].filter((n) => n >= startLine && n <= endLine));
  const under = new Map(placeable.map((t) => [t, lastShown(t.anchor)]));
  // Those of <all> that end on this row, the old side's first. at(x): {side, line} it ends on
  const endingOn = (row, all, at) => ["old", "new"].flatMap((side) => all.filter((x) =>
    row.kind === "line" && at(x).side === side && at(x).line === row[side]));
  const withBelow = rows.flatMap((row) => {
    const here = {
      threads: endingOn(row, placeable, (t) => ({ side: t.anchor.side, line: under.get(t) })),
      drafts: endingOn(row, whole, ({ anchor: a }) => ({ side: a.side, line: a.end })),
    };
    const all = [...here.threads, ...here.drafts];
    all.forEach((x) => placed.add(x));
    return all.length ? [row, { kind: "below", old: row.old, new: row.new, ...here }] : [row];
  });
  return { top: { threads: mine.filter((t) => t.outdated), drafts: myDrafts.filter((d) => !placed.has(d)) }, rows: withBelow };
}
