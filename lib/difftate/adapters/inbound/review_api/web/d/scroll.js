// Where layout D scrolls to, as a computed target, and what of the window its sticky headers
// leave to be seen, so that a test can check both. DOM-free.

/** Where a link to <thread> (as the API gives it, with an anchor) goes in the <files> of the
 *  Files changed tab (files_changed.js): {file, row}, or null when the tab doesn't show it. row:
 *  the index in the file's rows of the first of the thread's lines shown; null for the file's top,
 *  where an outdated thread is, whose lines now hold other code. */
export function threadTarget(files, { id, anchor: a }) {
  const file = files.find((f) => f.path === a.file);
  if (!file) return null;
  if (file.top.threads.some((t) => t.id === id)) return { file: file.path, row: null };
  const under = file.rows.findIndex((r) => r.kind === "below" && r.threads.some((t) => t.id === id));
  if (under < 0) return null;
  const row = file.rows.findIndex((r) => r.kind === "line" && r[a.side] >= a.startLine && r[a.side] <= a.endLine);
  return { file: file.path, row };
}

/** Where Viewed, next under <path> goes in the <files> of the Files changed tab: {file, row:
 *  null}, the top of the file after it, or null after the last one. */
export function viewedNextTarget(files, path) {
  const at = files.findIndex((f) => f.path === path);
  const next = at < 0 ? undefined : files[at + 1];
  return next ? { file: next.path, row: null } : null;
}

/** After a redraw: the file to bring to the top, or null to leave the window where it is. That
 *  is a file folded while the reviewer was inside it: its header would be gone, with whatever
 *  moved up in its place. <files>: the files now ({path, folded}); was(path): how it was on
 *  screen before ({folded, top, bottom}, from the window's top), if it was; pinned: how much of
 *  the window's top the pinned header covers. */
export function foldTarget(files, was, pinned) {
  const inside = (before) => before && !before.folded && before.top < pinned && before.bottom > pinned;
  return files.find((f) => f.folded && inside(was(f.path)))?.path ?? null;
}

// What a file's sticky header covers, below the pinned one: style.css's .file-head, 40px high,
// and a little air
const FILE_HEAD = 44;

// How far down the window the headers cover it
const covered = ({ pinned, fileHead = true }) => pinned + (fileHead ? FILE_HEAD : 0);

/** Whether all of a line is on screen. <box>: where it is ({top, bottom, height}, from the
 *  window's top; no height: it isn't shown); <viewport>: {pinned (as foldTarget's), height (the
 *  window's), fileHead (false where no file's header is over the node; else one is)}. */
export const lineShown = (box, viewport) => box.height > 0 && box.top >= covered(viewport) && box.bottom <= viewport.height;

/** Whether any of a file or a thread is on screen. box, viewport: as lineShown's. */
export const anyShown = (box, viewport) => box.height > 0 && box.bottom > covered(viewport) && box.top < viewport.height;

/** How far to scroll the window (negative: up) to bring a node out from under the headers; 0
 *  when its top isn't under them, or is above the window, where the browser scrolls to itself.
 *  For the keyboard's focus: the browser takes a node under a header for shown. */
export const uncoverBy = (box, viewport) => (box.top >= 0 && box.top < covered(viewport) ? box.top - covered(viewport) : 0);

// The popover's room: its width, what it keeps from the window's edges and from its line, and
// the least height worth opening under a line
const POPOVER = { width: 560, edge: 16, gap: 6, least: 240 };

/** Where the review path's popover goes for the header line at <line> ({left, top, bottom}, from
 *  the window's top) in <window> ({width, height}): {left, width, top or bottom (from the window's
 *  top or its foot, the other null), maxHeight}. Under the line; above it where there is little
 *  room under it and more above. */
export function popoverPlace(line, { width: across, height }) {
  const { edge, gap, least } = POPOVER;
  const width = Math.min(POPOVER.width, across - 2 * edge);
  const left = Math.max(edge, Math.min(line.left, across - width - edge));
  const below = height - line.bottom - gap - edge;
  const above = line.top - gap - edge;
  if (below < least && above > below) return { left, width, top: null, bottom: height - line.top + gap, maxHeight: above };
  return { left, width, top: line.bottom + gap, bottom: null, maxHeight: below };
}
