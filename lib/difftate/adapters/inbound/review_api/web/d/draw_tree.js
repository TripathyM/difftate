// Draws the file tree (the rows of file_tree.js).

import { el, icon, keptWhileSame } from "./dom.js";

const drawn = keptWhileSame();

function row(r, onPick) {
  const style = `--depth: ${r.depth}`;
  if (r.kind === "folder") return el("div", { class: "tree-row folder", style }, icon("folder"), el("span", { class: "name", text: r.name }));
  return el("button", {
    type: "button", class: `tree-row${r.viewed ? " viewed" : ""}`, style, title: `${r.path} (${r.status})`,
    "aria-current": r.selected ? "true" : false, "data-focus": `tree:${r.path}`, onclick: () => onPick(r.path),
  },
  icon("file"),
  el("span", { class: "name", text: r.name }),
  r.openThreads ? el("span", { class: "open-threads", title: `${r.openThreads} open thread${r.openThreads === 1 ? "" : "s"}` }, icon("comment"), String(r.openThreads)) : null,
  r.viewed ? el("span", { class: "viewed-mark", title: "Viewed" }, icon("check")) : null);
}

/** The tree of the Files changed tab's model, and what it says when the filter leaves no file. */
export function drawTree({ tree: rows, filtered }, onPick) {
  document.getElementById("filtered").textContent = filtered;
  document.getElementById("filtered").hidden = !filtered;
  const tree = document.getElementById("tree");
  const node = drawn("tree", rows, () => el("div", {}, rows.map((r) => row(r, onPick))));
  if (tree.firstElementChild !== node) tree.replaceChildren(node);
}
