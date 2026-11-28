// Layout D's Files changed tab: the file tree and every file's diff. DOM-free: draw_tree.js and
// draw_files.js draw it.

import { parseDiff } from "../diff.js";
import { orderFiles, rows as pathRows, stopBlock } from "../review_path.js";
import { diffRows, splitRows, withThreads } from "./diff_rows.js";
import { draftsOf } from "./drafts.js";
import { inTreeOrder, outOfDate, sorting, treeRows } from "./file_tree.js";
import { viewedNextTarget } from "./scroll.js";
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

// What stopBlock() builds with: a node as data, {tag, class, text, kids}, which draw_files.js draws
const asData = (tag, props = {}, ...kids) => ({ tag, ...props, kids: kids.flat().filter(Boolean) });

// What ends <path> in Reading order: {text (its button), label (where it goes)}
function viewedNext(files, path) {
  const target = viewedNextTarget(files, path);
  return target ? { text: "Viewed, next", label: `Next: ${target.file}` } : { text: "Viewed", label: "The last file" };
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

// The file's rows with its comments, as cards and boxes: {top: {threads, drafts}, rows}, unified
// or split as the reviewer chose. A line row says which of its sides are picked: by the drag under
// way, and by the drafts under their lines. What sits under a line says its side
function commented(state, path, rows, drafts) {
  const placed = withThreads(rows, { path, threads: state.server.threads, drafts });
  const { drag } = state.own;
  const ranges = placed.rows.flatMap((r) => (r.kind === "below" ? r.drafts.map((d) => d.anchor) : []));
  if (drag?.path === path) ranges.push({ side: drag.side, start: Math.min(drag.from, drag.to), end: Math.max(drag.from, drag.to) });
  const onSide = (model, { anchor }) => ({ ...model, side: anchor.side });
  const laidOut = state.own.settings.layout === "split" ? splitRows(placed.rows) : placed.rows;
  return {
    top: { threads: placed.top.threads.map((t) => threadCard(t, state, { placed: false })), drafts: placed.top.drafts.map((d) => draftBox(state, d, { away: true })) },
    rows: laidOut.map((r) => {
      if (r.kind === "below") {
        return {
          ...r,
          threads: r.threads.map((t) => onSide(threadCard(t, state, { placed: true }), t)),
          drafts: r.drafts.map((d) => onSide(draftBox(state, d), d)),
        };
      }
      return r.kind === "line" ? { ...r, picked: pickedSides(r, ranges) } : r;
    }),
  };
}

/** The tab's model from the page <state>, which has a poll's answers: {kind: "files", layout
 *  ("unified" or "split"), tree (rows,
 *  file_tree.js, the filtered ones, the selected file marked), filtered (what to say when the
 *  filter leaves none), files (in the tree's order, all of them: {path, note, additions,
 *  deletions, viewed, folded, top, rows (diff_rows.js, of that layout, with its threads as cards,
 *  threads.js, and its drafts as boxes: boxModel plus {title, was: {text, code} | null, hint};
 *  under a line each also has side; a line row has picked, its sides to mark)}), loose (the boxes of the drafts of files that aren't in the diff),
 *  progress: {viewed, total, text}, empty (what to say without a file)}. */
export function filesChanged(state) {
  const { changeset, threads, viewed, reviewPath } = state.server;
  const changed = byPath(parseDiff(changeset.diff));
  const drafts = draftsOf(state);
  const { sort, sorts } = sorting(state.own.sort, reviewPath);
  const order = sort === "order" ? pathRows(reviewPath) : null;
  const inOrder = order ? orderFiles(changed, order) : inTreeOrder(changed);
  const files = inOrder.map((file) => ({
    path: file.path, note: note(file), additions: file.additions, deletions: file.deletions,
    viewed: viewed.includes(file.path), folded: isFolded(state, file.path),
    stop: reviewPath ? stopBlock(reviewPath, file.path, asData) : null,
    next: order ? viewedNext(inOrder, file.path) : null,
    ...commented(state, file.path, file.parts.flatMap(diffRows), drafts),
  }));
  // The drafts of a file that isn't in the diff: shown above the files, so that what was typed in
  // them doesn't go out of sight. Its threads are on the Conversation tab
  const gone = (path) => !changed.some((f) => f.path === path);
  const loose = drafts.filter((d) => gone(d.anchor.path)).map((d) => draftBox(state, d, { away: true, path: true }));
  const tree = treeRows({ files: changed, threads, viewed, filter: state.own.filter, order })
    .map((r) => (r.kind === "file" ? { ...r, selected: r.path === state.own.selected } : r));
  const marked = files.filter((f) => f.viewed).length;
  return {
    kind: "files", layout: state.own.settings.layout, sorts, outOfDate: outOfDate(reviewPath), tree, files, loose,
    filtered: files.length && !tree.length ? `No file's path has “${state.own.filter}”.` : "",
    progress: { viewed: marked, total: files.length, text: `${marked} of ${files.length} files viewed` },
    empty: files.length ? "" : `No changes in ${viewLabel(changeset.view)}.`,
  };
}
