// Layout D's settings, which are the reviewer's own and kept in the browser: the diff's layout,
// and the theme, which follows the system until the reviewer picks one. DOM-free: it is given
// the browser's storage, and draw_settings.js shows what the model says.

import { setSetting } from "./state.js";

const LAYOUTS = [{ layout: "unified", text: "Unified" }, { layout: "split", text: "Split" }];

// Each setting's key in the storage, and the values this page knows
const KEPT = {
  layout: { key: "difftate.layout", values: LAYOUTS.map((l) => l.layout) },
  theme: { key: "difftate.theme", values: ["light", "dark"] },
};

/** The settings kept in <storage> (initialState's), those it has none of left out. A browser may
 *  refuse its storage: the page then has its defaults. */
export function readSettings(storage) {
  const kept = {};
  for (const [name, { key, values }] of Object.entries(KEPT)) {
    try {
      const value = storage.getItem(key);
      if (values.includes(value)) kept[name] = value;
    } catch { /* the default */ }
  }
  return kept;
}

/** Keep in <storage> what changed from the settings <before> to <settings>: only that, so a tab
 *  doesn't undo a choice made in another. Where it is refused, they last as long as the page. */
export function keepSettings(storage, before, settings) {
  for (const [name, { key }] of Object.entries(KEPT)) {
    if (settings[name] === before[name]) continue;
    try {
      if (settings[name]) storage.setItem(key, settings[name]);
      else storage.removeItem(key);
    } catch { /* not kept */ }
  }
}

const onScreen = ({ own }) => own.settings.theme ?? (own.systemDark ? "dark" : "light");
const other = (theme) => (theme === "dark" ? "light" : "dark");

/** The reviewer pressed the sun or moon: the other theme, whatever the system says. */
export const switchTheme = (state) => setSetting(state, "theme", other(onScreen(state)));

/** Follow the system's theme, or (turned off) keep the one on screen. */
export const followSystem = (state, follows) => setSetting(state, "theme", follows ? null : onScreen(state));

// The coding agent that replies in this review (GLOSSARY.md, Agent override), chosen from the
// agent list. The first entry is the review without a choice of its own: it clears one
function agentChoice({ agent }) {
  if (!agent) return { choices: [{ value: "", text: "agent list not readable" }], value: "", disabled: true };
  const own = agent.source === "review";
  const names = own && !agent.names.includes(agent.agent) ? [...agent.names, agent.agent] : agent.names;
  return {
    choices: [{ value: "", text: own ? "Default" : `Default (${agent.agent}, ${agent.source})` }, ...names.map((n) => ({ value: n, text: n }))],
    value: own ? agent.agent : "", disabled: false,
  };
}

/** The model of the settings: {layouts: [{layout, text, current}], theme ("light" or "dark" when
 *  the page forces one, null while it follows the system), follows, flip: the switch's
 *  {to (a theme), icon: "sun"|"moon", text}, agent (the coding agent choice, null before the
 *  first answers): {choices: [{value (a name, "" for none of the review's own), text}], value,
 *  disabled}}. */
export function settingsModel(state) {
  const { layout, theme } = state.own.settings;
  const to = other(onScreen(state));
  return {
    layouts: LAYOUTS.map((l) => ({ ...l, current: l.layout === layout })),
    theme, follows: !theme,
    flip: { to, icon: to === "light" ? "sun" : "moon", text: `Switch to the ${to} theme` },
    agent: state.server ? agentChoice(state.server) : null,
  };
}
