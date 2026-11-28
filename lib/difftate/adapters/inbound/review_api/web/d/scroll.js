// Where layout D scrolls to, as a computed target, so that a test can check it. DOM-free.

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

/** After a redraw: the file to bring to the top of the window, or null to leave the window where
 *  it is. That is a file folded while the reviewer was inside it: its header would be gone, with
 *  whatever moved up in its place. <files>: the files now ({path, folded}); was(path): how it
 *  was on screen before ({folded, top, bottom}, from the window's top), if it was. */
export function foldTarget(files, was) {
  const inside = (before) => before && !before.folded && before.top < 0 && before.bottom > 0;
  return files.find((f) => f.folded && inside(was(f.path)))?.path ?? null;
}
