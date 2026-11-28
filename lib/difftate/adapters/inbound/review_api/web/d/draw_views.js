// Draws the view picker (views.js): its button, and the views in its menu. index.html has the
// menu and its commit box, which stay, so that what is typed there does too.

import { el, icon, keptWhileSame, place } from "./dom.js";

const drawn = keptWhileSame();

/** The picker of the Files changed tab's model, drawn. onPick(view) */
export function drawPicker({ text, choices }, onPick) {
  place(document.getElementById("view-button"), [drawn("button", text, () => el("span", { class: "view-shown" }, el("span", { text }), icon("open")))]);
  place(document.getElementById("view-choices"), choices.map((c) => drawn(`view:${c.view}`, c, () =>
    el("button", { type: "button", class: "menu-item", "aria-current": c.current ? "true" : false, "data-focus": `view:${c.view}`, text: c.text, onclick: () => onPick(c.view) }))));
}
