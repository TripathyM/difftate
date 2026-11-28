// Layout D's file tree: the rows beside the diff. DOM-free: draw_tree.js draws them.

// Folders first at each level, then by name
function byFolder(a, b) {
  const x = a.path.split("/"), y = b.path.split("/");
  let i = 0;
  while (i < x.length - 1 && i < y.length - 1 && x[i] === y[i]) i++;
  return (i === x.length - 1) - (i === y.length - 1) || x[i].localeCompare(y[i]);
}

/** The <files> ({path}) as the tree lists them. */
export const inTreeOrder = (files) => [...files].sort(byFolder);

// How many open threads each file has: outdated ones too, as they are the file's
function openThreadCounts(threads) {
  const count = new Map();
  for (const t of threads) {
    if (t.status === "open" && t.anchor) count.set(t.anchor.file, (count.get(t.anchor.file) ?? 0) + 1);
  }
  return count;
}

/** The tree's rows for the changeset's <files> ({path, status}, diff.js) whose path has <filter>:
 *  {kind: "folder", name, path, depth} and, below its folders, {kind: "file", name, path, depth,
 *  status, openThreads (how many), viewed}. */
export function treeRows({ files, threads = [], viewed = [], filter = "" }) {
  const open = openThreadCounts(threads);
  const wanted = filter.toLowerCase();
  const rows = [];
  let folders = [];
  for (const file of inTreeOrder(files.filter((f) => f.path.toLowerCase().includes(wanted)))) {
    const parts = file.path.split("/");
    const name = parts.pop();
    let same = 0;
    while (same < parts.length && parts[same] === folders[same]) same++;
    for (let depth = same; depth < parts.length; depth++) {
      rows.push({ kind: "folder", name: parts[depth], path: parts.slice(0, depth + 1).join("/"), depth });
    }
    folders = parts;
    rows.push({
      kind: "file", name, path: file.path, depth: parts.length, status: file.status,
      openThreads: open.get(file.path) ?? 0, viewed: viewed.includes(file.path),
    });
  }
  return rows;
}
