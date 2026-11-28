// Layout D's settings, which are the reviewer's own and kept in the browser: the diff's layout,
// the theme, which follows the system until the reviewer picks one, and the Vim keys: on or off,
// those the reviewer changed, and whether they saw what a Vim browser extension does to them.
// DOM-free: it is given the browser's storage, and draw_settings.js shows what the model says.

import { defaultKey, isAction } from "./keymap.js";
import { NO_VIM, setSetting, withVim } from "./state.js";

const LAYOUTS = [{ layout: "unified", text: "Unified" }, { layout: "split", text: "Split" }];

// A setting whose text in the storage is one of <values>, the ones this page knows
const oneOf = (key, ...values) => ({ key, read: (text) => (values.includes(text) ? text : undefined), write: (value) => value });

// The keys the reviewer changed ({action: key, "" for off}), as text; those this page knows
function readKeys(text) {
  const changes = Object.entries(JSON.parse(text) ?? {}).filter(([name, key]) => isAction(name) && typeof key === "string");
  return changes.length ? Object.fromEntries(changes) : undefined;
}

// Each setting's key in the storage, how its text is read (undefined: not one this page knows)
// and what is written for a value (nothing: the key goes)
const KEPT = {
  layout: oneOf("difftate.layout", ...LAYOUTS.map((l) => l.layout)),
  theme: oneOf("difftate.theme", "light", "dark"),
  vim: oneOf("difftate.vim", "on", "off"),
  vimNotice: oneOf("difftate.vim-notice", "seen"),
  keys: { key: "difftate.keys", read: readKeys, write: (keys) => (Object.keys(keys).length ? JSON.stringify(keys) : null) },
};

/** The settings kept in <storage> (initialState's), those it has none of left out. A browser may
 *  refuse its storage: the page then has its defaults. */
export function readSettings(storage) {
  const kept = {};
  for (const [name, { key, read }] of Object.entries(KEPT)) {
    try {
      const text = storage.getItem(key);
      const value = text === null ? undefined : read(text);
      if (value !== undefined) kept[name] = value;
    } catch { /* the default */ }
  }
  return kept;
}

/** Keep in <storage> what changed from the settings <before> to <settings>: only that, so a tab
 *  doesn't undo a choice made in another. Where it is refused, they last as long as the page. */
export function keepSettings(storage, before, settings) {
  for (const [name, { key, write }] of Object.entries(KEPT)) {
    if (settings[name] === before[name]) continue;
    try {
      const text = settings[name] ? write(settings[name]) : null;
      if (text) storage.setItem(key, text);
      else storage.removeItem(key);
    } catch { /* not kept */ }
  }
}

export const vimOn = ({ own }) => own.settings.vim === "on";
/** Turn the Vim keys on or off. What they had under way goes. */
export const setVim = (state, on) => withVim(setSetting(state, "vim", on ? "on" : "off"), NO_VIM);
/** The reviewer saw what a Vim browser extension does to the keys. */
export const seeVimNotice = (state) => setSetting(state, "vimNotice", "seen");
/** The reviewer typed <text> as <action>'s key: "" turns it off. */
export function setKey(state, action, text) {
  const { [action]: _, ...others } = state.own.settings.keys;
  const key = text.trim();
  return setSetting(state, "keys", key === defaultKey(action) ? others : { ...others, [action]: key });
}
export const resetKeys = (state) => setSetting(state, "keys", {});
/** All keys close. */
export const closeKeys = (state) => withVim(state, { help: false });

const onScreen = ({ own }) => own.settings.theme ?? (own.systemDark ? "dark" : "light");
const other = (theme) => (theme === "dark" ? "light" : "dark");

/** The reviewer pressed the sun or moon: the other theme, whatever the system says. */
export const switchTheme = (state) => setSetting(state, "theme", other(onScreen(state)));

/** Follow the system's theme, or (turned off) keep the one on screen. */
export const followSystem = (state, follows) => setSetting(state, "theme", follows ? null : onScreen(state));

/** The review's agent override among GET /api/agent's <agent>, or "" without one. */
export const overrideOf = (agent) => (agent?.source === "review" ? agent.agent : "");

// The coding agent that replies in this review (GLOSSARY.md, Agent override), chosen from the
// agent list. The first entry is the review without a choice of its own: it clears one
function agentChoice({ agent }) {
  if (!agent) return { choices: [{ value: "", text: "agent list not readable" }], value: "", disabled: true };
  const own = overrideOf(agent);
  const names = own && !agent.names.includes(own) ? [...agent.names, own] : agent.names;
  return {
    choices: [{ value: "", text: own ? "Default" : `Default (${agent.agent}, ${agent.source})` }, ...names.map((n) => ({ value: n, text: n }))],
    value: own, disabled: false,
  };
}

/** The model of the settings: {vim (the Vim keys are on), layouts: [{layout, text, current}], theme ("light" or "dark" when
 *  the page forces one, null while it follows the system), follows, flip: the switch's
 *  {to (a theme), icon: "sun"|"moon", text}, agent (the coding agent choice, null before the
 *  first answers): {choices: [{value (a name, "" for none of the review's own), text}], value,
 *  disabled}}. */
export function settingsModel(state) {
  const { layout, theme } = state.own.settings;
  const to = other(onScreen(state));
  return {
    vim: vimOn(state),
    layouts: LAYOUTS.map((l) => ({ ...l, current: l.layout === layout })),
    theme, follows: !theme,
    flip: { to, icon: to === "light" ? "sun" : "moon", text: `Switch to the ${to} theme` },
    agent: state.server ? agentChoice(state.server) : null,
  };
}
