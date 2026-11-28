// Layout D's file tree: the rows beside the diff, by folder or in Reading order. DOM-free:
// draw_tree.js draws them.

import { nameAndFolder, rows as pathRows } from "../review_path.js";

// Folders first at each level, then by name
function byFolder(a, b) {
  const x = a.path.split("/"), y = b.path.split("/");
  let i = 0;
  while (i < x.length - 1 && i < y.length - 1 && x[i] === y[i]) i++;
  return (i === x.length - 1) - (i === y.length - 1) || x[i].localeCompare(y[i]);
}

/** The <files> ({path}) as the tree lists them by folder. */
export const inTreeOrder = (files) => [...files].sort(byFolder);

// How many open threads each file has: outdated ones too, as they are the file's
function openThreadCounts(threads) {
  const count = new Map();
  for (const t of threads) {
    if (t.status === "open" && t.anchor) count.set(t.anchor.file, (count.get(t.anchor.file) ?? 0) + 1);
  }
  return count;
}

// By folder: each folder, then below it its files
function folderRows(files, fileRow) {
  const rows = [];
  let folders = [];
  for (const file of inTreeOrder(files)) {
    const parts = file.path.split("/");
    const name = parts.pop();
    let same = 0;
    while (same < parts.length && parts[same] === folders[same]) same++;
    for (let depth = same; depth < parts.length; depth++) {
      rows.push({ kind: "folder", name: parts[depth], path: parts.slice(0, depth + 1).join("/"), depth });
    }
    folders = parts;
    rows.push({ ...fileRow(file), name, depth: parts.length });
  }
  return rows;
}

const NO_CHANGES = "no changes"; // the file the path names: the path is out of date

/** The file list of the review path <written> (review_path.js's rows) for a changeset's <files>
 *  ({path}). One it doesn't name, as the path was read before the file changed, is not on the
 *  path either. */
export function readingOrder(written, files) {
  const named = new Set(pathRows(written).map((r) => r.file));
  const unnamed = files.map((f) => f.path).filter((path) => !named.has(path));
  return pathRows({ ...written, not_on_the_path: [...(written.not_on_the_path ?? []), ...unnamed] });
}

// In Reading order: the rows of that list whose file matches, each a file of <files> or why not
function pathTreeRows(listed, files, fileRow, matches) {
  const changed = new Map(files.map((f) => [f.path, f]));
  const all = listed.filter((r) => r.kind === "heading" || matches(r.file));
  // A heading with none of its files left says nothing
  return all.filter((r, i) => r.kind !== "heading" || (all[i + 1] && all[i + 1].kind !== "heading")).map((r) => {
    if (r.kind === "heading") return { kind: "heading", name: r.text, depth: 0 };
    const [name, folder] = nameAndFolder(r.file);
    const stop = r.kind === "stop" ? r.stop : null;
    const file = changed.get(r.file);
    return {
      ...fileRow(file ?? { path: r.file, status: "" }),
      noDiff: r.gone ? NO_CHANGES : file ? "" : "not in this view",
      name, folder, depth: r.depth ?? 0,
      number: stop?.number ?? "", key: Boolean(stop?.key), reason: (r.kind === "skipped" && r.reason) || "",
    };
  });
}

/** The tree's rows for the changeset's <files> ({path, status}, diff.js) whose path has <filter>:
 *  {kind: "file", name, path, depth, status, openThreads (how many), viewed, counts (its lines
 *  added and deleted: {additions, deletions}, or null when it has no diff here)}. By folder, a file
 *  is below rows {kind: "folder", name, path, depth}. With <listed> (readingOrder()), in Reading
 *  order: below rows {kind: "heading", name, depth}, and each file also has folder, number (a
 *  stop's, or ""), key, reason (why it was skipped, or "") and noDiff (why it has no diff here,
 *  "" when it has one; then its status is "" too). */
export function treeRows({ files, threads = [], viewed = [], filter = "", listed = null }) {
  const open = openThreadCounts(threads);
  const wanted = filter.toLowerCase();
  const matches = (path) => path.toLowerCase().includes(wanted);
  const shown = files.filter((f) => matches(f.path));
  const fileRow = (file) => ({
    kind: "file", path: file.path, status: file.status, openThreads: open.get(file.path) ?? 0, viewed: viewed.includes(file.path),
    counts: file.additions === undefined ? null : { additions: file.additions, deletions: file.deletions },
  });
  return listed ? pathTreeRows(listed, shown, fileRow, matches) : folderRows(shown, fileRow);
}

const SORTS = [{ sort: "order", text: "Reading order" }, { sort: "folder", text: "Folders" }];

/** That the review path <written> names files with no changes, so it is out of date, or "". */
export function outOfDate(written) {
  const gone = new Set(written ? pathRows(written).filter((r) => r.gone).map((r) => r.file) : []).size;
  if (!gone) return "";
  return `The review path is out of date: ${gone === 1 ? "1 file it names has" : `${gone} files it names have`} no changes.`;
}

/** How the files are sorted: <wanted> ("order" or "folder"), but by folder without a review path
 *  (<written>, GET /api/review-path's "path"): {sort, sorts: [{sort, text, title, current,
 *  disabled}]}. */
export function sorting(wanted, written) {
  const sort = written ? wanted : "folder";
  const title = (one) => (one !== "order" ? "By folder, then by name"
    : written ? "The coding agent's review path" : "There is no review path (review-path.md) to follow");
  return { sort, sorts: SORTS.map((s) => ({ ...s, title: title(s.sort), current: s.sort === sort, disabled: s.sort === "order" && !written })) };
}
