// Draws the review's header: its state, the review mode, Submit review with its panel, and Done; the
// tabs and why a tab opened (page.js).

import { drawBox } from "./draw_threads.js";
import { el, keptWhileSame, place, setText } from "./dom.js";

const drawn = keptWhileSame(); // a button stays while it says the same, so no poll eats a click

const modeSwitch = (modes, on) => el("div", { class: "modes", role: "group", "aria-label": "Review mode" },
  modes.map((m) => el("button", { type: "button", "aria-pressed": String(m.current), title: m.title, "data-focus": `mode:${m.mode}`, text: m.text, onclick: () => on.setMode(m.mode) })));

// open: the panel is
const submitButton = ({ text, count }, open, on) => el("button", { type: "button", class: "btn primary", "aria-expanded": String(open), "data-focus": "submit-review", onclick: () => on.openSubmit(!open) },
  text, el("span", { class: "counter", title: `${count} held`, text: count }));

const doneButton = ({ text, mark, title }, on) => el("button", { type: "button", class: "btn", title, "data-focus": "done", text, onclick: () => on.setDone(mark) });

function pendingList({ pending, none }) {
  return el("div", {}, none ? el("p", { class: "muted", text: none })
    : el("ul", {}, pending.map((t) => el("li", {}, el("span", { class: "pending-where", text: t.where }),
      t.comments.map((text) => el("p", { text }))))));
}

// The panel stays on the page, so that what is typed in its summary does too
function drawPanel(panel, on) {
  document.getElementById("submit-panel").hidden = !panel;
  if (!panel) return;
  place(document.getElementById("pending"), [drawn("pending", [panel.pending, panel.none], () => pendingList(panel))]);
  place(document.getElementById("summary"), [drawBox(panel.box, on)]);
}

/** The header of the page's model, its tabs, why a tab opened and the notice. on:
 *  draw_threads.js's, and {tab(id), setMode(mode), openSubmit(open), setDone(done)} */
export function drawHeader({ header, tabs, why, notice }, on) {
  document.getElementById("review").replaceChildren(...(header ? [
    el("h1", {}, el("span", { text: header.branch }), el("span", { class: "muted", text: ` → ${header.base}` })),
    el("span", { class: `state${header.done ? " done" : ""}`, text: header.state }),
  ] : []));
  const submit = header?.submit;
  const open = Boolean(submit?.panel);
  place(document.getElementById("actions"), header ? [
    drawn("modes", header.modes, () => modeSwitch(header.modes, on)),
    submit ? drawn("submit", [submit.text, submit.count, open], () => submitButton(submit, open, on)) : null,
    drawn("done", header.doneButton, () => doneButton(header.doneButton, on)),
  ].filter(Boolean) : []);
  drawPanel(submit?.panel, on);
  place(document.getElementById("tabs"), tabs.map((t) => drawn(`tab:${t.id}`, t, () =>
    el("button", { type: "button", class: "tab", "aria-current": t.current ? "page" : false, "data-focus": `page-tab:${t.id}`, onclick: () => on.tab(t.id) },
      t.text, el("span", { class: "counter", text: t.count }),
      t.needs ? el("span", { class: "label needs-you", title: "A reply or a failed run waits for you", text: t.needs }) : null))));
  for (const [id, text] of [["why", why], ["notice", notice]]) {
    setText(document.getElementById(id), text);
    document.getElementById(id).hidden = !text;
  }
}
