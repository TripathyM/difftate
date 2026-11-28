// Draws every file's header, diff (unified or split) and comments (files_changed.js), and the
// popover with what the review path says of a file. What is the same keeps its nodes.

import { pinnedHeight } from "./draw_header.js";
import { drawBox, drawThread } from "./draw_threads.js";
import { el, icon, keptByKey, keptWhileSame, lineCounts, place } from "./dom.js";
import { anyShown, foldTarget, lineShown, popoverPlace, uncoverBy } from "./scroll.js";

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

// What a file's header says of the review path: pressing it shows the whole of it
const pathLine = (path, { badge, key, text, more }, on) => el("button", {
  type: "button", class: "path-line", "data-focus": `path:${path}`, title: "All the review path says of this file",
  "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => on.togglePath(path),
},
el("span", { class: "path-badge", text: badge }),
key ? el("span", { class: "key-stop", text: "★" }) : null,
el("span", { class: "path-text", text }),
more ? el("span", { class: "muted", text: more }) : null);

// What ends a file in Reading order
const nextBar = (path, { text, label }, on) => el("div", { class: "viewed-next" },
  el("span", { class: "muted next-label", text: label }),
  el("button", { type: "button", class: "btn primary", "data-focus": `next:${path}`, onclick: () => on.viewedNext(path) }, text));

// A file's card. Its header is drawn anew when what it says changes; its rows and comments change
// in place. on: draw_threads.js's, and {fold(path, folded), viewed(path, viewed): a promise of
// whether it was taken, viewedNext(path), togglePath(path), dragStart(spot, extend), dragOver(spot), dragEnd()}
function makeCard(path, on) {
  const top = el("div", { class: "comments file-top" });
  const tbody = el("tbody");
  const columns = Object.fromEntries(Object.entries(CELLS).map(([layout, cells]) =>
    [layout, el("colgroup", {}, cells.map((c) => el("col", { class: c || false })))]));
  const table = el("table", {}, tbody);
  const endSlot = el("div");
  const body = el("div", {}, top, table, endSlot);
  const node = el("section", {}, body);
  const heads = keptWhileSame();
  const ends = keptWhileSame();
  const lines = keptWhileSame();
  const below = { unified: keptBelow("unified"), split: keptBelow("split") };

  function row(r, i, layout, taken) {
    if (r.kind === "below") return below[layout](r, on, taken);
    if (r.kind !== "line") return lines(`${layout}:${r.kind}:${i}`, r, () => el("tr", { class: r.kind }, el("td", { colspan: CELLS[layout].length, text: r.text })));
    const { picked, cursor, ...line } = r;
    const tr = lines(`${layout}:${r.type}:${r.old}:${r.new}`, line, () => lineRow(path, line, layout, on));
    // A class, so a drag, or the line cursor's move, redraws no row
    tr.className = ["code-line", r.type, ...picked.map((side) => `picked-${side}`), cursor && `cursor-${cursor}`].filter(Boolean).join(" ");
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
      f.pathLine ? el("span", { class: "path-slot" }, pathLine(path, f.pathLine, on)) : null,
      lineCounts(f),
      el("label", { class: "viewed-box", title: "Stays checked until the file's diff changes" }, box, "Viewed"));
  }

  return {
    node,
    update({ layout, ...f }) {
      node.className = `file${f.folded ? " folded" : ""}`;
      // The header is the card's own child: sticky, it stays while any of the file is on screen
      place(node, [heads("head", [f.note, f.additions, f.deletions, f.viewed, f.folded, f.pathLine], () => header(f)), body]);
      body.hidden = f.folded;
      if (f.folded) return; // its rows are drawn when it is open
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

const descriptions = keptWhileSame();
let popped = null; // the file whose description the popover was last opened for

/** The popover with the open <description> (files_changed.js), or none. It is opened only for
 *  another file than the last: closed by the browser (Escape, a click elsewhere), it stays closed
 *  while the state catches up (main.js), even if that click draws the page. */
export function drawDescription(description) {
  const popover = document.getElementById("path-popover");
  const file = description?.file ?? null;
  for (const [path, node] of cards) node.querySelector(".path-line")?.setAttribute("aria-expanded", String(path === file));
  if (!description) {
    popped = null;
    if (popover.matches(":popover-open")) popover.hidePopover();
    return;
  }
  place(popover, [descriptions("description", [file, description.block], () => fromData(description.block))]);
  if (popped === file) return;
  popped = file;
  const line = cards.get(file).querySelector(".path-line").getBoundingClientRect();
  const { left, width, top, bottom, maxHeight } = popoverPlace(line, { width: document.documentElement.clientWidth, height: window.innerHeight });
  const px = (value) => (value === null ? "auto" : `${value}px`);
  Object.assign(popover.style, { left: px(left), width: px(width), top: px(top), bottom: px(bottom), maxHeight: px(maxHeight) });
  if (!popover.matches(":popover-open")) popover.showPopover();
  popover.scrollTop = 0;
}

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
  const target = foldTarget(files, (path) => was.get(path), pinnedHeight());
  if (target !== null) scrollToFile(target);
}

/** Put the top of <path>'s diff at the top of the window. */
export const scrollToFile = (path) => cards.get(path)?.scrollIntoView({ block: "start" });

/** Bring a thread link's <target> (scroll.js) to the top of the window, for the thread <id>.
 *  Without one, the thread's card is brought there (the Conversation tab's). */
export function scrollToTarget(target, id) {
  const line = !target || target.row === null ? null : rowNode(target);
  (line ?? document.getElementById(`thread-${id}`))?.scrollIntoView({ block: "start" });
}

// A target's row on the page
const rowNode = ({ file, row }) => cards.get(file)?.querySelector("tbody").children[row];

// The window, as scroll.js asks what is on screen in it
const viewport = () => ({ pinned: pinnedHeight(), height: window.innerHeight });
const anyOnScreen = (node) => Boolean(node) && anyShown(node.getBoundingClientRect(), viewport());
const lineOnScreen = (node) => lineShown(node.getBoundingClientRect(), viewport());

// What sticks or floats over the page, so that no scroll of the window moves it from under a
// header. A folded file's header is all of its card: it can't stick, and isn't one of these
const STAYS_PUT = "#pinned, .file:not(.folded) > .file-head, [popover], dialog, #problem";

/** Scroll <node>, where the keyboard went, out from under the headers, unless it stays put. */
export function uncover(node) {
  if (node.closest(STAYS_PUT) || (node.closest(".sidebar") && getComputedStyle(node.closest(".sidebar")).position === "sticky")) return;
  // Only in an open file, below its header, is there a file's header over a node
  const fileHead = Boolean(node.closest(".file:not(.folded) > :not(.file-head)"));
  const by = uncoverBy(node.getBoundingClientRect(), { ...viewport(), fileHead });
  if (by) window.scrollBy(0, by);
}

/** The first line of the diff on screen, as a target (scroll.js), or null. */
export function firstLineShown() {
  for (const [file, card] of cards) {
    const line = [...card.querySelectorAll("tbody > tr.code-line")].find(lineOnScreen);
    if (line) return { file, row: [...line.parentElement.children].indexOf(line) };
  }
  return null;
}

/** Whether <target> is on screen: its line, or with no row any of its file. */
export function isOnScreen({ file, row }) {
  if (row !== null) {
    const line = rowNode({ file, row });
    return Boolean(line) && lineOnScreen(line);
  }
  return anyOnScreen(cards.get(file));
}

/** Whether any of the thread <id>'s card is on screen: not on the other tab, nor hidden. */
export const isThreadOnScreen = (id) => anyOnScreen(document.getElementById(`thread-${id}`));

/** The path of the file at the top of the window, or null. */
export const fileAtTop = () => [...cards].find(([, card]) => anyOnScreen(card))?.[0] ?? null;

/** Bring <target>'s line into sight, scrolling no further than that; with no row, its file's top. */
export function reveal(target) {
  if (target.row === null) scrollToFile(target.file);
  else rowNode(target)?.scrollIntoView({ block: "nearest" });
}
