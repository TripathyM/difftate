// Draws the review's header: its state, the review mode, Submit review with its panel, Done and the
// overflow menu; the tabs, why a tab opened and the banners (page.js). And how tall what of it is
// pinned stands, for what must not go under it.

import { drawBox } from "./draw_threads.js";
import { el, keptWhileSame, place, setText, showDialog } from "./dom.js";

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
  modes.map((m) => el("button", { type: "button", "aria-pressed": String(m.current), title: m.title, "data-text": m.text, "data-focus": `mode:${m.mode}`, text: m.text, onclick: () => on.setMode(m.mode) })));

// open: whether its panel is
const submitButton = ({ text, count, off }, open, on) => el("button", { type: "button", class: "btn primary submit-review", disabled: Boolean(off), title: off || false, "aria-expanded": String(open), "data-focus": "submit-review", onclick: () => on.openSubmit(!open) },
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

// What the page asks before a change to live sends what is held
function drawConfirm(confirm) {
  for (const [id, text] of [["live-confirm-text", confirm?.text], ["live-yes", confirm?.yes], ["live-no", confirm?.no]]) {
    if (confirm) setText(document.getElementById(id), text);
  }
  showDialog(document.getElementById("live-confirm"), Boolean(confirm));
}

const warningFlash = (w, on) => el("div", { class: "flash warning" }, el("span", { text: w.text }),
  el("button", { type: "button", class: "link", "data-focus": `dismiss:${w.id}`, text: "Dismiss", onclick: () => on.dismissWarning(w.id) }));

/** The header of the page's model, its tabs, why a tab opened, the notice, the banners and what
 *  is asked before going live. on:
 *  draw_threads.js's, and {tab(id), setMode(mode), openSubmit(open), setDone(done),
 *  dismissWarning(id)} */
export function drawHeader({ header, tabs, why, notice, waiting, warnings, confirm }, on) {
  drawConfirm(confirm);
  document.getElementById("open-more").hidden = !header;
  place(document.getElementById("warnings"), warnings.map((w) => drawn(`warning:${w.id}`, w, () => warningFlash(w, on))));
  document.getElementById("review").replaceChildren(...(header ? [
    el("h1", {}, el("span", { text: header.branch }), el("span", { class: "muted", text: ` → ${header.base}` })),
    el("span", { class: `state${header.done ? " done" : ""}`, text: header.state }),
  ] : []));
  const submit = header?.submit;
  const open = Boolean(submit?.panel);
  // What is still open grows as a change to live starts a run, and must move nothing: it comes
  // first, takes only the room left (style.css), and holds it while it says nothing
  place(document.getElementById("actions"), header ? [
    drawn("still-open", header.stillOpen, (text) => el("span", { class: "muted still-open", text })),
    drawn("modes", header.modes, () => modeSwitch(header.modes, on)),
    drawn("submit", [submit.text, submit.count, submit.off, open], () => submitButton(submit, open, on)),
    drawn("done", header.doneButton, () => doneButton(header.doneButton, on)),
  ] : []);
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
