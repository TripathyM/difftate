// Draws the settings (settings.js): the theme on the whole page, the sun or moon switch, and the
// settings panel, which index.html has and the browser opens and closes.

import { el, icon, keptWhileSame, place } from "./dom.js";

const drawn = keptWhileSame();

// The coding agent choice. Its value is set at every draw, so that a refused pick goes back
function drawAgent(agent) {
  document.getElementById("agent-setting").hidden = !agent;
  if (!agent) return;
  const select = document.getElementById("agent");
  place(select, agent.choices.map((c) => drawn(`agent:${c.value}`, c, () => el("option", { value: c.value, text: c.text }))));
  select.value = agent.value;
  select.disabled = agent.disabled;
}

/** The settings of the page's model, drawn. on: {setLayout(layout)} */
export function drawSettings({ layouts, theme, follows, flip, agent }, on) {
  drawAgent(agent);
  // With no theme forced, the stylesheet follows the system's
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const button = document.getElementById("flip-theme");
  button.title = flip.text;
  button.setAttribute("aria-label", flip.text);
  place(button, [drawn("flip", flip.icon, icon)]);
  place(document.getElementById("layouts"), layouts.map((l) => drawn(`layout:${l.layout}`, l, () =>
    el("button", { type: "button", "aria-pressed": String(l.current), "data-focus": `layout:${l.layout}`, text: l.text, onclick: () => on.setLayout(l.layout) }))));
  document.getElementById("follow-system").checked = follows;
}
