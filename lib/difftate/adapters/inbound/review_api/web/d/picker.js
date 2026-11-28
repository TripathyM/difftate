// A list to pick from by typing, which the Vim keys open: threads, files, views, agents. DOM-free:
// draw_vim.js draws it. state.own.vim.picker: {title, items: [{text, hint, value}], query, at,
// and what vim.js needs to know once one is picked}.

import { withVim } from "./state.js";

export const openPicker = (state, picker) => withVim(state, { picker: { query: "", at: 0, ...picker }, pending: [] });
export const closePicker = (state) => withVim(state, { picker: null });

const found = ({ items, query }) => items.filter((i) => `${i.text} ${i.hint ?? ""}`.toLowerCase().includes(query.toLowerCase()));

/** The picker's model: {title, query, items: those the query finds, {text, hint, value,
 *  current}, the one Enter picks marked}, or null while it is closed. */
export function pickerModel({ own }) {
  const { picker } = own.vim;
  if (!picker) return null;
  return {
    title: picker.title, query: picker.query,
    items: found(picker).map((item, i) => ({ ...item, current: i === picker.at })),
  };
}

export const filterPicker = (state, query) => withVim(state, { picker: { ...state.own.vim.picker, query, at: 0 } });

/** <by> items down the list, round its ends. */
export function movePicker(state, by) {
  const { picker } = state.own.vim;
  const n = found(picker).length || 1;
  return withVim(state, { picker: { ...picker, at: (picker.at + by + n) % n } });
}

/** What the keydown event <press> does in the picker: {move: 1 or -1}, "pick", "close", or null
 *  for a press the query box takes. */
export function pickerPress({ key, ctrlKey }) {
  if (key === "ArrowDown" || (ctrlKey && (key === "j" || key === "n"))) return { move: 1 };
  if (key === "ArrowUp" || (ctrlKey && (key === "k" || key === "p"))) return { move: -1 };
  if (key === "Enter") return "pick";
  return key === "Escape" ? "close" : null;
}
