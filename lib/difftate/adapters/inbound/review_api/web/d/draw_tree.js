// Draws the file tree (the rows of file_tree.js), with how it is sorted and what it says of the
// review path.

import { el, icon, keptWhileSame } from "./dom.js";

const drawn = keptWhileSame();

function row(r, onPick) {
  const style = `--depth: ${r.depth}`;
  if (r.kind === "heading") return el("div", { class: "tree-heading", text: r.name });
  if (r.kind === "folder") return el("div", { class: "tree-row folder", style }, icon("folder"), el("span", { class: "name", text: r.name }));
  const more = (cls, text) => (text ? el("span", { class: cls, text }) : null);
  const parts = [
    r.number ? el("span", { class: "stop-number", text: r.number }) : icon("file"),
    el("span", { class: "name" }, r.name, r.key ? el("span", { class: "key-stop", title: "Key stop: slow down here", text: " ★" }) : null,
      more("muted", r.folder && `  ${r.folder}`), more("muted", r.reason && ` — ${r.reason}`)),
    more("tree-mark", r.mark),
  ];
  // A file with no diff here has nowhere to go
  if (r.mark) return el("div", { class: "tree-row gone", style, title: `${r.path}: ${r.mark}` }, parts);
  return el("button", {
    type: "button", class: `tree-row${r.viewed ? " viewed" : ""}`, style,
    title: `${r.path} (${r.status})${r.reason ? `. Skipped: ${r.reason}` : ""}`,
    "aria-current": r.selected ? "true" : false, "data-focus": `tree:${r.path}`, onclick: () => onPick(r.path),
  },
  parts,
  r.openThreads ? el("span", { class: "open-threads", title: `${r.openThreads} open thread${r.openThreads === 1 ? "" : "s"}` }, icon("comment"), String(r.openThreads)) : null,
  r.viewed ? el("span", { class: "viewed-mark", title: "Viewed" }, icon("check")) : null);
}

/** The sort control and the tree of the Files changed tab's model, that the review path is out of
 *  date, and what it says when the filter leaves no file. */
export function drawTree({ sorts, outOfDate, tree: rows, filtered }, onPick, onSort) {
  const control = document.getElementById("sort");
  const choices = drawn("sort", sorts, () => el("div", { class: "modes" }, sorts.map((s) => el("button", {
    type: "button", text: s.text, title: s.title, disabled: s.disabled, "aria-pressed": String(s.current),
    "data-focus": `sort:${s.sort}`, onclick: () => onSort(s.sort),
  }))));
  if (control.firstElementChild !== choices) control.replaceChildren(choices);
  document.getElementById("outdated").textContent = outOfDate;
  document.getElementById("outdated").hidden = !outOfDate;
  document.getElementById("filtered").textContent = filtered;
  document.getElementById("filtered").hidden = !filtered;
  const tree = document.getElementById("tree");
  const node = drawn("tree", rows, () => el("div", {}, rows.map((r) => row(r, onPick))));
  if (tree.firstElementChild !== node) tree.replaceChildren(node);
}
