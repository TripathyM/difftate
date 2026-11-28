// Draws the review's header and the tabs (page.js).

import { el } from "./dom.js";

export function drawHeader({ header, tabs }) {
  document.getElementById("review").replaceChildren(...(header ? [
    el("h1", {}, el("span", { text: header.branch }), el("span", { class: "muted", text: ` → ${header.base}` })),
    el("span", { class: `state${header.done ? " done" : ""}`, text: header.state }),
  ] : []));
  document.getElementById("tabs").replaceChildren(...tabs.map((t) =>
    el("span", { class: "tab", "aria-current": t.current ? "page" : false }, t.text, el("span", { class: "counter", text: t.count }))));
}
