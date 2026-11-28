// Draws the review's header: its state, the review mode, Submit review with its panel, Done and the
// overflow menu; the tabs, why a tab opened and the banners (page.js). And how tall what of it is
// pinned stands, for what must not go under it.

import { drawBox } from "./draw_threads.js";
import { el, keptWhileSame, place, setText } from "./dom.js";

const drawn = keptWhileSame(); // a button stays while it says the same, so no poll eats a click

/** How much of the window's top the pinned header (index.html: the header and the waiting
 *  banner) covers once the reviewer has scrolled. */
export const pinnedHeight = () => document.getElementById("pinned").offsetHeight;

/** Keep style.css's --pinned-height at pinnedHeight(), which changes as the header wraps and as
 *  the waiting banner comes and goes: what sticks or is scrolled to stays below it. */
export function keepPinnedHeight() {
  new ResizeObserver(() => document.documentElement.style.setProperty("--pinned-height", `${pinnedHeight()}px`))
    .observe(document.getElementById("pinned"));
}

const modeSwitch = (modes, on) => el("div", { class: "modes", role: "group", "aria-label": "Review mode" },
  modes.map((m) => el("button", { type: "button", "aria-pressed": String(m.current), title: m.title, "data-focus": `mode:${m.mode}`, text: m.text, onclick: () => on.setMode(m.mode) })));

// open: whether its panel is
const submitButton = ({ text, count }, open, on) => el("button", { type: "button", class: "btn primary", "aria-expanded": String(open), "data-focus": "submit-review", onclick: () => on.openSubmit(!open) },
  text, el("span", { class: "counter", text: count }));

const doneButton = ({ text, mark, title }, on) => el("button", { type: "button", class: "btn", title, "data-focus": "done", text, onclick: () => on.setDone(mark) });

function heldList({ held, none }) {
  return el("div", {}, none ? el("p", { class: "muted", text: none })
    : el("ul", {}, held.map((t) => el("li", {}, el("span", { class: "held-where", text: t.where }),
      t.comments.map((text) => el("p", { text }))))));
}

// The panel stays on the page, so that what is typed in its summary does too
function drawPanel(panel, on) {
  document.getElementById("submit-panel").hidden = !panel;
  if (!panel) return;
  place(document.getElementById("held"), [drawn("held", [panel.held, panel.none], () => heldList(panel))]);
  place(document.getElementById("summary"), [drawBox(panel.box, on)]);
}

const warningFlash = (w, on) => el("div", { class: "flash warning" }, el("span", { text: w.text }),
  el("button", { type: "button", class: "link", "data-focus": `dismiss:${w.id}`, text: "Dismiss", onclick: () => on.dismissWarning(w.id) }));

/** The header of the page's model, its tabs, why a tab opened, the notice and the banners. on:
 *  draw_threads.js's, and {tab(id), setMode(mode), openSubmit(open), setDone(done),
 *  dismissWarning(id)} */
export function drawHeader({ header, tabs, why, notice, waiting, warnings }, on) {
  document.getElementById("open-more").hidden = !header;
  place(document.getElementById("warnings"), warnings.map((w) => drawn(`warning:${w.id}`, w, () => warningFlash(w, on))));
  document.getElementById("review").replaceChildren(...(header ? [
    el("h1", {}, el("span", { text: header.branch }), el("span", { class: "muted", text: ` → ${header.base}` })),
    el("span", { class: `state${header.done ? " done" : ""}`, text: header.state }),
  ] : []));
  const submit = header?.submit;
  const open = Boolean(submit?.panel);
  place(document.getElementById("actions"), header ? [
    drawn("modes", header.modes, () => modeSwitch(header.modes, on)),
    submit ? drawn("submit", [submit.text, submit.count, open], () => submitButton(submit, open, on)) : null,
    header.stillOpen ? drawn("still-open", header.stillOpen, (text) => el("span", { class: "muted still-open", text })) : null,
    drawn("done", header.doneButton, () => doneButton(header.doneButton, on)),
  ].filter(Boolean) : []);
  drawPanel(submit?.panel, on);
  place(document.getElementById("tabs"), tabs.map((t) => drawn(`tab:${t.id}`, t, () =>
    el("button", { type: "button", class: "tab", "aria-current": t.current ? "page" : false, "data-focus": `page-tab:${t.id}`, onclick: () => on.tab(t.id) },
      t.text, el("span", { class: "counter", text: t.count }),
      t.needs ? el("span", { class: "label needs-you", title: "A reply or a failed run waits for you", text: t.needs }) : null))));
  for (const [id, text] of [["why", why], ["notice", notice], ["waiting", waiting]]) {
    setText(document.getElementById(id), text);
    document.getElementById(id).hidden = !text;
  }
}
