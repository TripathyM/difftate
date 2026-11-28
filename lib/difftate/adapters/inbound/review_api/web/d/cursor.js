// Layout D's line cursor and Vim jumps: where each goes in the files of the Files changed tab
// (files_changed.js), so that a test can check it. DOM-free.
//
// A spot is a line the cursor can be on, {file, side, line}, with want ("old" or "new") once
// the reviewer picked a side in split view. A target is scroll.js's {file, row}. Where a move
// starts from is a spot, or a target of a line row (the first one on screen, when the cursor
// isn't), or null.

import { threadTarget } from "./scroll.js";

// The lines a file shows, top to bottom. A folded file shows none. starts: a change begins here
function linesOf(files) {
  const lines = [];
  for (const f of files) {
    if (f.folded) continue;
    let unchanged = true; // a hunk's head or a file's top ends a change
    f.rows.forEach((r, row) => {
      if (r.kind !== "line") {
        unchanged ||= r.kind !== "below"; // what sits under a line doesn't
        return;
      }
      const split = !("type" in r);
      const changed = split ? [r.left, r.right].some((half) => half && half.type !== "context") : r.type !== "context";
      lines.push({ file: f.path, row, old: r.old, new: r.new, split, starts: changed && unchanged });
      unchanged = !changed;
    });
  }
  return lines;
}

const indexOf = (lines, from) => (!from ? -1 : lines.findIndex((l) => l.file === from.file
  && (from.side ? l[from.side] === from.line : l.row === from.row)));

// The side of <line> the cursor takes: the one wanted in split view, else the new one
function sideOf(line, want) {
  const side = (line.split && want) || "new";
  return line[side] !== null ? side : side === "new" ? "old" : "new";
}

// The cursor on <line>, on <side>, still wanting the side of <from>
const on = (line, from, side = sideOf(line, from?.want)) => ({
  spot: { file: line.file, side, line: line[side], ...(from?.want && { want: from.want }) },
  target: { file: line.file, row: line.row },
});

// While lines are being selected from <anchor>, only those of its file and side
const within = (lines, anchor) => (anchor ? lines.filter((l) => l.file === anchor.file && l[anchor.side] !== null) : lines);

/** Where the line of <from> is shown, as a target, or null. */
export function targetOf(files, from) {
  const lines = linesOf(files);
  const line = lines[indexOf(lines, from)];
  return line ? { file: line.file, row: line.row } : null;
}

/** <by> lines down (up when negative) from <from>: {spot, target}, or null when no line shows.
 *  From a target, that line is taken as it is. */
export function move(files, from, by, anchor = null) {
  const lines = within(linesOf(files), anchor);
  const at = indexOf(lines, from);
  const to = at < 0 || !from.side ? Math.max(at, 0) : Math.max(0, Math.min(lines.length - 1, at + by));
  return lines[to] ? on(lines[to], from, anchor?.side) : null;
}

/** The first line, or the <last>. */
export function toEnd(files, from, last, anchor = null) {
  const lines = within(linesOf(files), anchor);
  return lines.length ? on(lines[last ? lines.length - 1 : 0], from, anchor?.side) : null;
}

/** The <side> ("old" or "new") of the cursor's row, which the cursor then keeps to, or null
 *  when the row isn't split, or has nothing on that side. */
export function pickSide(files, from, side) {
  const lines = linesOf(files);
  const line = lines[indexOf(lines, from)];
  if (!line?.split) return null;
  const wanting = { ...from, want: side };
  return line[side] === null ? { spot: wanting, target: { file: line.file, row: line.row } } : on(line, wanting, side);
}

/** The first line of the next change (<by> 1) or the previous one (-1) from <from>: {spot,
 *  target, wrapped}, or null with no change on screen. From a target, its line counts. */
export function nextChange(files, from, by) {
  const lines = linesOf(files);
  const found = indexOf(lines, from);
  // From the first line on screen, a change that starts on it is still ahead
  const here = found < 0 || from.side ? found : found - 0.5 * by;
  const starts = lines.flatMap((l, i) => (l.starts ? [i] : []));
  if (!starts.length) return null;
  const ahead = by > 0 ? starts.find((i) => i > here) : starts.findLast((i) => i < here);
  const to = ahead ?? starts.at(by > 0 ? 0 : -1);
  return { ...on(lines[to], from), wrapped: ahead === undefined };
}

/** The path of the file after <path> (<by> 1) or before it (-1), round the ends, or of the
 *  first or last one from nowhere; null without a file. */
export function nextFile(files, path, by) {
  const at = files.findIndex((f) => f.path === path);
  const to = at < 0 ? (by > 0 ? 0 : files.length - 1) : (at + by + files.length) % files.length;
  return files[to]?.path ?? null;
}

/** <path>'s first line: {spot, target}, or null when it shows none. */
export function firstIn(files, path) {
  const line = linesOf(files).find((l) => l.file === path);
  return line ? on(line, null) : null;
}

// The open threads in review order, as the Neovim viewer visits them: the general ones first,
// then those with a place in Files changed, by file and row. at: [file's index, row]
function sequence(files, threads) {
  const open = threads.filter((t) => t.status === "open");
  const general = open.filter((t) => !t.anchor).map((thread, i) => ({ thread, target: null, at: [-1, i] }));
  const placed = open.filter((t) => t.anchor).flatMap((thread) => {
    const target = threadTarget(files, thread);
    // An outdated thread has no row: it is at the top of its file
    return target ? [{ thread, target, at: [files.findIndex((f) => f.path === target.file), target.row ?? -1] }] : [];
  });
  return [...general, ...placed.sort((a, b) => a.at[0] - b.at[0] || a.at[1] - b.at[1])];
}

const after = ([file, row], [otherFile, otherRow]) => (file - otherFile || row - otherRow) > 0;

/** The open thread after (<by> 1) or before (-1) <here>: {thread, target (null for a general
 *  one), wrapped}, or null with none. <here>: null, or the cursor and the thread it was last
 *  taken to ({file, side, line, thread}). <files>: with the threads in them. */
export function nextThread(files, threads, here, by) {
  const all = sequence(files, threads);
  if (!all.length) return null;
  let to = all.findIndex((e) => e.thread.id === here?.thread);
  if (to >= 0) to += by;
  else if (!here?.file) to = by > 0 ? 0 : all.length - 1;
  else {
    const lines = linesOf(files);
    const at = [files.findIndex((f) => f.path === here.file), lines[indexOf(lines, here)]?.row ?? -1];
    to = by > 0 ? all.findIndex((e) => after(e.at, at)) : all.findLastIndex((e) => after(at, e.at));
    if (to < 0) to = by > 0 ? all.length : -1;
  }
  const wrapped = to < 0 || to >= all.length;
  const { thread, target } = all[wrapped ? (by > 0 ? 0 : all.length - 1) : to];
  return { thread, target, wrapped };
}

/** The threads whose lines the cursor at <spot> is on. */
export const threadsAt = (threads, spot) => threads.filter(({ anchor: a, outdated, inView }) => spot && a && !outdated
  && inView !== false && a.file === spot.file && a.side === spot.side && a.startLine <= spot.line && spot.line <= a.endLine);
