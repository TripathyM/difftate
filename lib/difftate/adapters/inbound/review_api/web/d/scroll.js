// Where layout D scrolls to, as a computed target, so that a test can check it. DOM-free.

/** After a redraw: the file to bring to the top of the window, or null to leave the window where
 *  it is. That is a file folded while the reviewer was inside it: its header would be gone, with
 *  whatever moved up in its place. <files>: the files now ({path, folded}); was(path): how it
 *  was on screen before ({folded, top, bottom}, from the window's top), if it was. */
export function foldTarget(files, was) {
  const inside = (before) => before && !before.folded && before.top < 0 && before.bottom > 0;
  return files.find((f) => f.folded && inside(was(f.path)))?.path ?? null;
}
