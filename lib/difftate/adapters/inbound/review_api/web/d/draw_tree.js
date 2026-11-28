// Draws the file tree (the rows of file_tree.js).

import { el, icon, kept } from "./dom.js";

const drawn = kept();

function row(r, onPick) {
  const style = `--depth: ${r.depth}`;
  if (r.kind === "folder") return el("div", { class: "tree-row folder", style }, icon("folder"), el("span", { class: "name", text: r.name }));
  return el("button", {
    type: "button", class: `tree-row${r.viewed ? " viewed" : ""}`, style, title: `${r.path} (${r.status})`,
    "aria-current": r.selected ? "true" : false, onclick: () => onPick(r.path),
  },
  icon("file"),
  el("span", { class: "name", text: r.name }),
  r.comments ? el("span", { class: "comments", title: `${r.comments} open thread${r.comments === 1 ? "" : "s"}` }, icon("comment"), String(r.comments)) : null,
  r.viewed ? el("span", { class: "viewed-mark", title: "Viewed" }, icon("check")) : null);
}

export function drawTree(rows, onPick) {
  const tree = document.getElementById("tree");
  const node = drawn("tree", rows, () => el("div", {}, rows.map((r) => row(r, onPick))));
  if (tree.firstElementChild !== node) tree.replaceChildren(node);
}
