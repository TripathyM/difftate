// Draws the toasts (toasts.js), pinned in the window, each with a button that closes it.

import { el, icon, keptWhileSame, place } from "./dom.js";

const drawn = keptWhileSame(); // a toast stays while it says the same, so no poll eats a click

const toastNode = ({ id, kind, text }, on) => el("div", { class: `flash toast ${kind}`, role: kind === "error" ? "alert" : false },
  el("span", { text }),
  el("button", { type: "button", class: "tool", title: "Close", "aria-label": "Close", "data-focus": `close-toast:${id}`, onclick: () => on.closeToast(id) }, icon("close")));

/** The toasts of the page's model, drawn. on: {closeToast(id)} */
export function drawToasts(toasts, on) {
  place(document.getElementById("toasts"), toasts.map((t) => drawn(t.id, t, () => toastNode(t, on))));
}
