// Layout D's Files changed tab: the file tree and every file's diff. DOM-free: draw_tree.js and
// draw_files.js draw it.

import { parseDiff } from "../diff.js";
import { diffRows, withThreads } from "./diff_rows.js";
import { draftsOf } from "./drafts.js";
import { inTreeOrder, treeRows } from "./file_tree.js";
import { isFolded } from "./state.js";
import { boxModel, heldHint, linesText, threadCard } from "./threads.js";

// How the viewer names a view of the review
const viewLabel = (v) => (!v ? "all changes" : v === "HEAD" ? "uncommitted changes"
  : v === "staged" || v === "unstaged" ? `${v} changes` : `the commits after ${v}`);

// The diff's files, one per path: git gives two for a file that changed its type (a file that
// became a link is deleted, then added), and the viewed mark, threads and fold are the path's
function byPath(parsed) {
  const files = new Map();
  for (const part of parsed) {
    const had = files.get(part.path);
    if (!had) {
      files.set(part.path, { ...part, parts: [part] });
      continue;
    }
    had.parts.push(part);
    Object.assign(had, { status: "type changed", additions: had.additions + part.additions, deletions: had.deletions + part.deletions });
  }
  return [...files.values()];
}

// What a file's header says of it besides its path
function note(file) {
  if (file.status === "renamed" || file.status === "copied") return `${file.status} from ${file.oldPath}`;
  return file.status === "modified" ? "" : file.status;
}

// The box of a draft. <away>: it isn't under its lines, so it shows the code it posts to. <path>:
// it is away from its file too, so its title names the file
function draftBox(state, { key, anchor: a }, { away = false, path = false } = {}) {
  return {
    ...boxModel(state, key, "draft"),
    title: `Comment on ${path ? `${a.path}, ` : ""}${linesText(a.side, a.start, a.end)}`,
    was: away ? { text: "The diff doesn't show these lines as you picked them. The comment goes with this code:", code: a.code } : null,
    hint: heldHint(state),
  };
}

// The sides of <row> to mark as picked: those that one of <ranges> ({side, start, end}) covers
const pickedSides = (row, ranges) => ["old", "new"].filter((side) =>
  ranges.some((r) => r.side === side && row[side] >= r.start && row[side] <= r.end));

// The file's rows with its comments, as cards and boxes: {top: {threads, drafts}, rows}. A line
// row says which of its sides are picked: by the drag under way, and by the drafts under their lines
function commented(state, path, rows, drafts) {
  const placed = withThreads(rows, { path, threads: state.server.threads, drafts });
  const { drag } = state.own;
  const ranges = placed.rows.flatMap((r) => (r.kind === "below" ? r.drafts.map((d) => d.anchor) : []));
  if (drag?.path === path) ranges.push({ side: drag.side, start: Math.min(drag.from, drag.to), end: Math.max(drag.from, drag.to) });
  const cards = (threads, isPlaced) => threads.map((t) => threadCard(t, state, { placed: isPlaced }));
  return {
    top: { threads: cards(placed.top.threads, false), drafts: placed.top.drafts.map((d) => draftBox(state, d, { away: true })) },
    rows: placed.rows.map((r) => {
      if (r.kind === "below") return { ...r, threads: cards(r.threads, true), drafts: r.drafts.map((d) => draftBox(state, d)) };
      return r.kind === "line" ? { ...r, picked: pickedSides(r, ranges) } : r;
    }),
  };
}

/** The tab's model from the page <state>, which has a poll's answers: {kind: "files", tree (rows,
 *  file_tree.js, the filtered ones, the selected file marked), filtered (what to say when the
 *  filter leaves none), files (in the tree's order, all of them: {path, note, additions,
 *  deletions, viewed, folded, top, rows (diff_rows.js, with its threads as cards, threads.js, and
 *  its drafts as boxes: boxModel plus {title, was: {text, code} | null, hint}; a line row has
 *  picked, its sides to mark)}), loose ({drafts} of files that aren't in the diff),
 *  progress: {viewed, total, text}, empty (what to say without a file)}. */
export function filesChanged(state) {
  const { changeset, threads, viewed } = state.server;
  const changed = byPath(parseDiff(changeset.diff));
  const drafts = draftsOf(state);
  const files = inTreeOrder(changed).map((file) => ({
    path: file.path, note: note(file), additions: file.additions, deletions: file.deletions,
    viewed: viewed.includes(file.path), folded: isFolded(state, file.path),
    ...commented(state, file.path, file.parts.flatMap(diffRows), drafts),
  }));
  // The drafts of a file that isn't in the diff: shown above the files, so that what was typed in
  // them doesn't go out of sight. Its threads are on the Conversation tab
  const gone = (path) => !changed.some((f) => f.path === path);
  const loose = { drafts: drafts.filter((d) => gone(d.anchor.path)).map((d) => draftBox(state, d, { away: true, path: true })) };
  const tree = treeRows({ files: changed, threads, viewed, filter: state.own.filter })
    .map((r) => (r.kind === "file" ? { ...r, selected: r.path === state.own.selected } : r));
  const marked = files.filter((f) => f.viewed).length;
  return {
    kind: "files", tree, files, loose,
    filtered: files.length && !tree.length ? `No file's path has “${state.own.filter}”.` : "",
    progress: { viewed: marked, total: files.length, text: `${marked} of ${files.length} files viewed` },
    empty: files.length ? "" : `No changes in ${viewLabel(changeset.view)}.`,
  };
}
