// Draws every file's header, unified diff and comments (files_changed.js). What is the same keeps
// its nodes.

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

// A line's row. The pointer over either number takes a drag there
function lineRow(path, r, on) {
  const over = (side) => () => { if (r[side] !== null) on.dragOver({ path, side, line: r[side] }); };
  const cells = ["old", "new"].map((side) => number(path, side, r[side], on));
  cells[0].addEventListener("mouseover", over("old"));
  cells[1].addEventListener("mouseover", over("new"));
  return el("tr", {}, cells, el("td", { class: "code", text: r.text }));
}

// What sits under a line
function belowRow() {
  const inside = el("div", { class: "comments" });
  return { node: el("tr", { class: "below" }, el("td", { colspan: 3 }, inside)), inside };
}

// The rows under lines, kept for what is in them, not for their line numbers, which change when
// lines are added above: a row stays, so a box in it isn't taken off the page. (items, on, taken:
// the rows used in this draw)
function keptBelow() {
  const held = new Map(); // a thread's id or a draft's key -> the row it was in
  return (r, on, taken) => {
    const ids = [...r.threads.map((t) => t.id), ...r.drafts.map((d) => d.key)];
    const had = ids.map((id) => held.get(id)).filter((row) => row && !taken.has(row));
    // Of two rows that became one, keep the one the reviewer is in
    const row = had.find((h) => h.node.contains(document.activeElement)) ?? had[0] ?? belowRow();
    taken.add(row);
    ids.forEach((id) => held.set(id, row));
    place(row.inside, comments(r, on));
    return row.node;
  };
}

// A file's card. Its header is drawn anew when what it says changes; its rows and comments change
// in place. on: draw_threads.js's, and {fold(path, folded), viewed(path, viewed): a promise of
// whether it was taken, dragStart(spot, extend), dragOver(spot), dragEnd()}
function makeCard(path, on) {
  const head = el("div");
  const top = el("div", { class: "comments file-top" });
  const tbody = el("tbody");
  const body = el("div", {}, top,
    el("table", { class: "diff" }, el("colgroup", {}, el("col", { class: "number" }), el("col", { class: "number" }), el("col")), tbody));
  const node = el("section", {}, head, body);
  const heads = keptWhileSame();
  const lines = keptWhileSame();
  const below = keptBelow();

  function row(r, i, taken) {
    if (r.kind === "below") return below(r, on, taken);
    if (r.kind !== "line") return lines(`${r.kind}:${i}`, r, () => el("tr", { class: r.kind }, el("td", { colspan: 3, text: r.text })));
    const { picked, ...line } = r;
    const tr = lines(`${r.type}:${r.old}:${r.new}`, line, () => lineRow(path, line, on));
    tr.className = [r.type, ...picked.map((side) => `picked-${side}`)].join(" "); // a class, so a drag redraws no row
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
    update(f) {
      node.className = `file${f.folded ? " folded" : ""}`;
      place(head, [heads("head", [f.note, f.additions, f.deletions, f.viewed, f.folded], () => header(f))]);
      body.hidden = f.folded;
      if (f.folded) return; // its rows are drawn when it is open
      place(top, comments(f.top, on));
      top.hidden = !f.top.threads.length && !f.top.drafts.length;
      const taken = new Set();
      place(tbody, f.rows.map((r, i) => row(r, i, taken)));
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

/** The progress, every file, and the comments without one, of the Files changed tab's model. */
export function drawFiles({ files, loose, progress, empty }, on) {
  document.getElementById("progress").replaceChildren(progress.text, el("progress", { max: progress.total || 1, value: progress.viewed }));
  document.getElementById("empty").textContent = empty;
  document.getElementById("empty").hidden = !empty;
  const was = new Map(files.map((f) => [f.path, onScreen(cards.get(f.path))])); // before the nodes change
  const nodes = files.map((f) => card(f.path, f, on));
  cards.clear();
  files.forEach((f, i) => cards.set(f.path, nodes[i]));
  place(document.getElementById("files"), nodes);
  const away = document.getElementById("loose");
  place(away, comments(loose, on));
  away.hidden = !loose.threads.length && !loose.drafts.length;
  const target = foldTarget(files, (path) => was.get(path));
  if (target !== null) scrollToFile(target);
}

/** Put the top of <path>'s diff at the top of the window. */
export const scrollToFile = (path) => cards.get(path)?.scrollIntoView({ block: "start" });
