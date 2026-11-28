// Draws the review's header, the tabs and the note saying why a tab opened (page.js).

import { el, keptWhileSame, place, setText } from "./dom.js";

const drawn = keptWhileSame(); // a tab's button stays while it says the same, so no poll eats a click

export function drawHeader({ header, tabs, note }, onTab) {
  document.getElementById("review").replaceChildren(...(header ? [
    el("h1", {}, el("span", { text: header.branch }), el("span", { class: "muted", text: ` → ${header.base}` })),
    el("span", { class: `state${header.done ? " done" : ""}`, text: header.state }),
  ] : []));
  place(document.getElementById("tabs"), tabs.map((t) => drawn(t.id, t, () =>
    el("button", { type: "button", class: "tab", "aria-current": t.current ? "page" : false, "data-focus": `page-tab:${t.id}`, onclick: () => onTab(t.id) },
      t.text, el("span", { class: "counter", text: t.count }),
      t.needs ? el("span", { class: "label needs-you", title: "A reply or a failed run waits for you", text: t.needs }) : null))));
  setText(document.getElementById("note"), note);
  document.getElementById("note").hidden = !note;
}
