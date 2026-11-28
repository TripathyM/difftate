// Layout D's Files changed tab: the file tree and every file's diff. DOM-free: draw_tree.js and
// draw_files.js draw it.

import { parseDiff } from "../diff.js";
import { diffRows } from "./diff_rows.js";
import { treeRows } from "./file_tree.js";
import { isFolded } from "./state.js";

// How the viewer names a view of the review
const viewLabel = (v) => (!v ? "all changes" : v === "HEAD" ? "uncommitted changes"
  : v === "staged" || v === "unstaged" ? `${v} changes` : `the commits after ${v}`);

// What a file's header says of it besides its path
function note(file) {
  if (file.status === "renamed" || file.status === "copied") return `${file.status} from ${file.oldPath}`;
  return file.status === "modified" ? "" : file.status;
}

/** The tab's model from the page <state>, which has a poll's answers: {kind: "files", tree (rows,
 *  file_tree.js, the filtered ones, the selected file marked), filtered (what to say when the
 *  filter leaves none), files (in the tree's order, all of them: {path, note, additions,
 *  deletions, viewed, folded, rows (diff_rows.js)}), progress: {viewed, total, text}, empty (what
 *  to say without a file)}. */
export function filesChanged(state) {
  const { changeset, threads, viewed } = state.server;
  const parsed = parseDiff(changeset.diff);
  const files = treeRows({ files: parsed }).filter((r) => r.kind === "file").map(({ path }) => {
    const file = parsed.find((f) => f.path === path);
    return {
      path, note: note(file), additions: file.additions, deletions: file.deletions,
      viewed: viewed.includes(path), folded: isFolded(state, path), rows: diffRows(file),
    };
  });
  const tree = treeRows({ files: parsed, threads, viewed, filter: state.own.filter })
    .map((r) => (r.kind === "file" ? { ...r, selected: r.path === state.own.selected } : r));
  const seen = files.filter((f) => f.viewed).length;
  return {
    kind: "files", tree, files,
    filtered: files.length && !tree.length ? `No file's path has “${state.own.filter}”.` : "",
    progress: { viewed: seen, total: files.length, text: `${seen} of ${files.length} files viewed` },
    empty: files.length ? "" : `No changes in ${viewLabel(changeset.view)}.`,
  };
}
