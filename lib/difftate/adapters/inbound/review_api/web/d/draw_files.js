// Draws every file's header and unified diff (files_changed.js). A file whose model is the same
// keeps its nodes.

import { el, icon, keptWhileSame, place } from "./dom.js";
import { foldTarget } from "./scroll.js";

const drawn = keptWhileSame();
const cards = new Map(); // path -> the node shown for it

function diffTable(rows) {
  return el("table", { class: "diff" },
    el("colgroup", {}, el("col", { class: "number" }), el("col", { class: "number" }), el("col")),
    el("tbody", {}, rows.map((r) => (r.kind === "line"
      ? el("tr", { class: r.type }, el("td", { class: "number", text: r.old ?? "" }), el("td", { class: "number", text: r.new ?? "" }), el("td", { class: "code", text: r.text }))
      : el("tr", { class: r.kind }, el("td", { colspan: 3, text: r.text }))))));
}

// on: {fold(path, folded), viewed(path, viewed): a promise of whether it was taken}
function card(f, on) {
  const box = el("input", {
    type: "checkbox", checked: f.viewed, "data-focus": `viewed:${f.path}`,
    onchange: async () => { if (!(await on.viewed(f.path, box.checked))) box.checked = f.viewed; },
  });
  return el("section", { class: `file${f.folded ? " folded" : ""}` },
    el("div", { class: "file-head" },
      el("button", { type: "button", class: "fold", "data-focus": `fold:${f.path}`, "aria-expanded": String(!f.folded), "aria-label": `${f.folded ? "Open" : "Fold"} ${f.path}`, onclick: () => on.fold(f.path, !f.folded) },
        icon(f.folded ? "folded" : "open")),
      el("span", { class: "path", text: f.path }),
      el("span", { class: "muted note", text: f.note }),
      el("span", { class: "counts" }, el("span", { class: "additions", text: `+${f.additions}` }), " ", el("span", { class: "deletions", text: `−${f.deletions}` })),
      el("label", { class: "viewed-box", title: "Stays checked until the file's diff changes" }, box, "Viewed")),
    f.folded ? null : diffTable(f.rows));
}

// How <card> is on screen (scroll.js)
function onScreen(card) {
  if (!card) return null;
  const { top, bottom } = card.getBoundingClientRect();
  return { folded: card.classList.contains("folded"), top, bottom };
}

/** The progress and every file of the Files changed tab's model. */
export function drawFiles({ files, progress, empty }, on) {
  document.getElementById("progress").replaceChildren(progress.text, el("progress", { max: progress.total || 1, value: progress.viewed }));
  document.getElementById("empty").textContent = empty;
  document.getElementById("empty").hidden = !empty;
  const was = new Map(files.map((f) => [f.path, onScreen(cards.get(f.path))])); // before the nodes change
  const nodes = files.map((f) => drawn(f.path, f, () => card(f, on)));
  cards.clear();
  files.forEach((f, i) => cards.set(f.path, nodes[i]));
  place(document.getElementById("files"), nodes);
  const target = foldTarget(files, (path) => was.get(path));
  if (target !== null) scrollToFile(target);
}

/** Put the top of <path>'s diff at the top of the window. */
export const scrollToFile = (path) => cards.get(path)?.scrollIntoView({ block: "start" });
