// Draws every file's header, diff (unified or split) and comments (files_changed.js). What is the
// same keeps its nodes.

import { drawBox, drawThread } from "./draw_threads.js";
import { el, icon, keptByKey, keptWhileSame, place } from "./dom.js";
import { foldTarget } from "./scroll.js";

const cards = new Map(); // path -> the node shown for it

const comments = ({ threads, drafts }, on) => [...threads.map((t) => drawThread(t, on)), ...drafts.map((d) => drawBox(d, on))];

// A line's number on <side>: pressing it starts a pick, which dragging over others, or Shift-click,
// makes longer
function number(path, side, line, on) {
  if (line === null) return el("td", { class: "number" });
  const spot = { path, side, line };
  return el("td", { class: `number ${side}` }, el("button", {
    type: "button", text: line, "data-focus": `line:${side}:${line}:${path}`,
    title: "Comment on this line. Drag, or Shift-click, to cover more lines",
    "aria-label": `Comment on ${side === "old" ? "old " : ""}line ${line} of ${path}`,
    onmousedown: (e) => { if (e.button === 0) { e.preventDefault(); on.dragStart(spot, e.shiftKey); } },
    // A click without a pointer: the keyboard's
    onclick: (e) => { if (e.detail === 0) { on.dragStart(spot, e.shiftKey); on.dragEnd(); } },
  }),
  );
}

// A line's text, the words changed from its pair's (diff_rows.js) marked
function code(cls, { text, words = [] }) {
  const parts = [];
  let at = 0;
  for (const [start, end] of words) {
    parts.push(text.slice(at, start), el("span", { class: "word", text: text.slice(start, end) }));
    at = end;
  }
  return el("td", { class: cls }, parts, text.slice(at));
}

// A line's row, unified or split. The pointer over a line number takes a drag there
function lineRow(path, r, layout, on) {
  const pickable = (side) => {
    const cell = number(path, side, r[side], on);
    cell.addEventListener("mouseover", () => { if (r[side] !== null) on.dragOver({ path, side, line: r[side] }); });
    return cell;
  };
  if (layout === "unified") return el("tr", {}, pickable("old"), pickable("new"), code("code", r));
  // One half of a split row: its side's number and text, or two empty cells
  const half = (side, line) => {
    if (!line) return [el("td", { class: `number empty ${side}` }), el("td", { class: `code empty ${side}` })];
    const cell = pickable(side);
    cell.className += ` ${line.type}`;
    return [cell, code(`code ${side} ${line.type}`, line)];
  };
  return el("tr", {}, half("old", r.left), half("new", r.right));
}

const SIDES = ["old", "new"];
// How wide a table is, in cells, and which of them hold line numbers
const CELLS = { unified: ["number", "number", ""], split: ["number", "", "number", ""] };

// What sits under a line: unified in one place, split under each side
function belowRow(layout) {
  const places = (layout === "split" ? SIDES : [null]).map((side) => ({ side, node: el("div", { class: "comments" }) }));
  const colspan = CELLS[layout].length / places.length;
  return { node: el("tr", { class: "below" }, places.map((p) => el("td", { colspan }, p.node))), places };
}

// The rows under lines, kept for what is in them, not for their line numbers, which change when
// lines are added above: a row stays, so a box in it isn't taken off the page. (items, on, taken:
// the rows used in this draw)
function keptBelow(layout) {
  const held = new Map(); // a thread's id or a draft's key -> the row it was in
  return (r, on, taken) => {
    const ids = [...r.threads.map((t) => t.id), ...r.drafts.map((d) => d.key)];
    const had = ids.map((id) => held.get(id)).filter((row) => row && !taken.has(row));
    // Of two rows that became one, keep the one the reviewer is in
    const row = had.find((h) => h.node.contains(document.activeElement)) ?? had[0] ?? belowRow(layout);
    taken.add(row);
    ids.forEach((id) => held.set(id, row));
    for (const { side, node } of row.places) {
      const here = (all) => (side ? all.filter((x) => x.side === side) : all);
      place(node, comments({ threads: here(r.threads), drafts: here(r.drafts) }, on));
    }
    return row.node;
  };
}

// A node stopBlock() built, as data ({tag, kids, ...props}, files_changed.js)
const fromData = ({ tag, kids, ...props }) => el(tag, props, kids.map(fromData));

// What ends a file in Reading order
const nextBar = (path, { text, label }, on) => el("div", { class: "viewed-next" },
  el("span", { class: "muted next-label", text: label }),
  el("button", { type: "button", class: "btn primary", "data-focus": `next:${path}`, onclick: () => on.viewedNext(path) }, text));

// A file's card. Its header is drawn anew when what it says changes; its rows and comments change
// in place. on: draw_threads.js's, and {fold(path, folded), viewed(path, viewed): a promise of
// whether it was taken, viewedNext(path), dragStart(spot, extend), dragOver(spot), dragEnd()}
function makeCard(path, on) {
  const top = el("div", { class: "comments file-top" });
  const tbody = el("tbody");
  const columns = Object.fromEntries(Object.entries(CELLS).map(([layout, cells]) =>
    [layout, el("colgroup", {}, cells.map((c) => el("col", { class: c || false })))]));
  const table = el("table", {}, tbody);
  const stopSlot = el("div");
  const endSlot = el("div");
  const body = el("div", {}, stopSlot, top, table, endSlot);
  const node = el("section", {}, body);
  const heads = keptWhileSame();
  const stops = keptWhileSame();
  const ends = keptWhileSame();
  const lines = keptWhileSame();
  const below = { unified: keptBelow("unified"), split: keptBelow("split") };

  function row(r, i, layout, taken) {
    if (r.kind === "below") return below[layout](r, on, taken);
    if (r.kind !== "line") return lines(`${layout}:${r.kind}:${i}`, r, () => el("tr", { class: r.kind }, el("td", { colspan: CELLS[layout].length, text: r.text })));
    const { picked, ...line } = r;
    const tr = lines(`${layout}:${r.type}:${r.old}:${r.new}`, line, () => lineRow(path, line, layout, on));
    // A class, so a drag redraws no row
    tr.className = [r.type, ...picked.map((side) => `picked-${side}`)].filter(Boolean).join(" ");
    return tr;
  }

  function header(f) {
    const box = el("input", {
      type: "checkbox", checked: f.viewed, "data-focus": `viewed:${path}`,
      onchange: async () => { if (!(await on.viewed(path, box.checked))) box.checked = f.viewed; },
    });
    return el("div", { class: "file-head" },
      el("button", { type: "button", class: "fold", "data-focus": `fold:${path}`, "aria-expanded": String(!f.folded), "aria-label": `${f.folded ? "Open" : "Fold"} ${path}`, onclick: () => on.fold(path, !f.folded) },
        icon(f.folded ? "folded" : "open")),
      el("span", { class: "path", text: path }),
      el("span", { class: "muted note", text: f.note }),
      el("span", { class: "counts" }, el("span", { class: "additions", text: `+${f.additions}` }), " ", el("span", { class: "deletions", text: `−${f.deletions}` })),
      el("label", { class: "viewed-box", title: "Stays checked until the file's diff changes" }, box, "Viewed"));
  }

  return {
    node,
    update({ layout, ...f }) {
      node.className = `file${f.folded ? " folded" : ""}`;
      // The header is the card's own child: sticky, it stays while any of the file is on screen
      place(node, [heads("head", [f.note, f.additions, f.deletions, f.viewed, f.folded], () => header(f)), body]);
      body.hidden = f.folded;
      if (f.folded) return; // its rows are drawn when it is open
      place(stopSlot, f.stop ? [stops("stop", f.stop, () => fromData(f.stop))] : []);
      place(endSlot, f.next ? [ends("next", f.next, () => nextBar(path, f.next, on))] : []);
      place(top, comments(f.top, on));
      top.hidden = !f.top.threads.length && !f.top.drafts.length;
      table.className = `diff ${layout}`;
      place(table, [columns[layout], tbody]);
      const taken = new Set();
      place(tbody, f.rows.map((r, i) => row(r, i, layout, taken)));
    },
  };
}

const card = keptByKey(makeCard);

// How <card> is on screen (scroll.js)
function onScreen(card) {
  if (!card) return null;
  const { top, bottom } = card.getBoundingClientRect();
  return { folded: card.classList.contains("folded"), top, bottom };
}

/** The progress, every file, and the drafts without one, of the Files changed tab's model. */
export function drawFiles({ layout, files, loose, progress, empty }, on) {
  document.getElementById("progress").replaceChildren(progress.text, el("progress", { max: progress.total || 1, value: progress.viewed }));
  document.getElementById("empty").textContent = empty;
  document.getElementById("empty").hidden = !empty;
  const was = new Map(files.map((f) => [f.path, onScreen(cards.get(f.path))])); // before the nodes change
  const nodes = files.map((f) => card(f.path, { ...f, layout }, on));
  cards.clear();
  files.forEach((f, i) => cards.set(f.path, nodes[i]));
  place(document.getElementById("files"), nodes);
  const away = document.getElementById("loose");
  place(away, loose.map((d) => drawBox(d, on)));
  away.hidden = !loose.length;
  const target = foldTarget(files, (path) => was.get(path));
  if (target !== null) scrollToFile(target);
}

/** Put the top of <path>'s diff at the top of the window. */
export const scrollToFile = (path) => cards.get(path)?.scrollIntoView({ block: "start" });

/** Bring a thread link's <target> (scroll.js) to the top of the window, for the thread <id>. */
export function scrollToTarget({ file, row }, id) {
  const line = row === null ? null : cards.get(file)?.querySelector("tbody").children[row];
  (line ?? document.getElementById(`thread-${id}`))?.scrollIntoView({ block: "start" });
}
