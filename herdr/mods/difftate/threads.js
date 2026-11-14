// The Review tab's thread lists: the threads picker and ]d / [d. Plain JavaScript, no Herdr,
// so tests/test_review_tab_threads.py runs it in node.
// Threads are as api.js flattens them: a general thread (not on a file) has filePath null.

export const isGeneral = (t) => !t.filePath;

// Where a thread is, as the tab names it: "general", or path:line(s)
export const threadPlace = (t) =>
  isGeneral(t) ? "general" : `${t.filePath}:${t.startLine === t.endLine ? t.startLine : `${t.startLine}-${t.endLine}`}`;

// File threads in review order: changed files first (in the changeset's order), then the rest, by line.
function fileOrder(threads, files) {
  const order = new Map(files.map((f, i) => [f.path, i]));
  return threads.filter((t) => !isGeneral(t))
    .sort((a, b) => (order.get(a.filePath) ?? 1e6) - (order.get(b.filePath) ?? 1e6) || a.filePath.localeCompare(b.filePath) || a.endLine - b.endLine);
}

// The open threads in review order: general ones first (as the API lists them), then the files'.
export function openThreads(threads, files) {
  const open = threads.filter((t) => t.status === "open");
  return [...open.filter(isGeneral), ...fileOrder(open, files)];
}

// The threads picker's two groups, [general, on files]: each has its open threads first, then the closed ones.
export function pickerThreads(threads, files) {
  const openFirst = (list) => [...list.filter((t) => t.status === "open"), ...list.filter((t) => t.status !== "open")];
  return [openFirst(threads.filter(isGeneral)), openFirst(fileOrder(threads, files))];
}

// The open thread after (d > 0) or before (d < 0) <here>, wrapping round, from <list> (openThreads).
// <here> is {path, line} in a file, or {general: id of the thread picked, or null} in the general threads.
export function stepThread(list, files, here, d) {
  if (!list.length) return null;
  const order = new Map(files.map((f, i) => [f.path, i]));
  // General threads sit before every file, in list order
  const pos = (t, i) => (isGeneral(t) ? [-1, "", i] : [order.get(t.filePath) ?? 1e6, t.filePath, t.endLine]);
  const cmp = (a, b) => a[0] - b[0] || a[1].localeCompare(b[1]) || a[2] - b[2];
  let me;
  if ("general" in here) {
    const i = list.findIndex((t) => t.id === here.general);
    me = [-1, "", i < 0 ? -0.5 : i];
  } else me = [order.get(here.path ?? "") ?? 1e6, here.path ?? "", here.line ?? 0];
  const at = list.map((t, i) => ({ t, p: pos(t, i) }));
  const pick = d > 0 ? at.find((x) => cmp(x.p, me) > 0) ?? at[0] : [...at].reverse().find((x) => cmp(x.p, me) < 0) ?? at.at(-1);
  return pick.t;
}
