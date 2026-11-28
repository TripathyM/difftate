// Layout D's Vim key map: the Neovim viewer's action names and default keys
// (lua/difftate/init.lua), with keys of the browser's own for what Neovim does itself, such as
// moving the cursor. DOM-free.

import { isPageKey } from "./keys.js";

// [group, [action, default key, what it does]]. A key is written as in Neovim: <leader> is
// Space, <C-d> is Ctrl+d
const GROUPS = [
  ["Move", [
    ["down", "j", "Line down"],
    ["up", "k", "Line up"],
    ["old_side", "h", "Old side (split view)"],
    ["new_side", "l", "New side (split view)"],
    ["first", "gg", "First line"],
    ["last", "G", "Last line"],
    ["half_down", "<C-d>", "Half a screen down"],
    ["half_up", "<C-u>", "Half a screen up"],
    ["visual_line", "V", "Select lines"],
    ["visual", "v", "Select lines"],
  ]],
  ["Jump", [
    ["next_hunk", "]h", "Next change"],
    ["previous_hunk", "[h", "Previous change"],
    ["next", "]r", "Next open thread"],
    ["previous", "[r", "Previous open thread"],
    ["next_file", "]f", "Next file"],
    ["previous_file", "[f", "Previous file"],
  ]],
  ["Review", [
    ["comment", "<leader>rc", "Comment on this line or selection"],
    ["thread", "<leader>rt", "Read the thread on this line"],
    ["add_comment", "<leader>ra", "Comment on the thread"],
    ["resolve", "<leader>rR", "Resolve the thread on this line"],
    ["reopen", "<leader>rO", "Reopen the thread on this line"],
    ["expand", "<leader>re", "Expand or collapse all threads"],
    ["general", "<leader>rG", "Write a general thread"],
    ["threads", "<leader>rs", "Pick a thread"],
    ["files", "<leader>rf", "Pick a changed file"],
    ["files_sidebar", "<leader>rF", "Show or hide the file tree"],
    ["viewed", "<leader>rv", "Mark this file viewed, or not"],
    ["views", "<leader>rV", "Choose the view"],
    ["mode", "<leader>rM", "Switch between live and batched"],
    ["submit", "<leader>rS", "Submit the held threads"],
    ["agent", "<leader>rA", "Choose the coding agent that replies"],
    ["done", "<leader>rD", "Mark Done, or undo it"],
    ["export", "<leader>rE", "Copy the export"],
    ["side_by_side", "<leader>rd", "Split or unified"],
  ]],
  ["Help", [["help", "?", "All keys, and change them"]]],
];

const ACTIONS = GROUPS.flatMap(([group, actions]) => actions.map(([name, key, text]) => ({ name, key, text, group })));

/** Whether <name> is an action. */
export const isAction = (name) => ACTIONS.some((a) => a.name === name);
/** <name>'s default key. */
export const defaultKey = (name) => ACTIONS.find((a) => a.name === name).key;

// The presses that a key is, in order: "<leader>rc" is Space, r, c; "<C-d>" is "C-d"
const tokens = (keys) => [...keys.matchAll(/<(?:leader|space)>|<c-(.)>|./gi)]
  .map(([all, ctrl]) => (ctrl ? `C-${ctrl.toLowerCase()}` : all.length > 1 ? " " : all));

// A <…> name other than those, or a space, which Neovim doesn't write either: such a key would
// be read as its letters, which nobody types
const unreadable = (keys) => /\s|<(?!(?:leader|space|c-.)>)[^<>]+>/i.test(keys);
const UNREAD = "off: write keys as Neovim does; of the <…> names only <leader> and <C-d>'s kind work";

const shown = (token) => (token === " " ? "Space" : token.startsWith("C-") ? `Ctrl+${token.slice(2)}` : token);

const keyOf = (changes, a) => (Object.hasOwn(changes, a.name) ? changes[a.name] : a.key);
const startsWith = (long, short) => short.every((t, i) => long[i] === t);

// Every action with the presses of its key, with the reviewer's <changes>
const keyed = (changes) => ACTIONS.map((a) => {
  const key = keyOf(changes, a);
  const unread = unreadable(key);
  return { ...a, key, unread, seq: unread ? [] : tokens(key) };
});

// A key that starts with one of the page's own (keys.js) would take it away
const takesPageKey = ({ seq }) => seq.length > 0 && isPageKey(seq[0]);

/** The keys that work, with the reviewer's <changes> ({action: key, "" to turn it off}):
 *  [{name, text, group, seq (its presses)}]. */
export const bindingsOf = (changes) => keyed(changes).filter((b) => b.seq.length && !takesPageKey(b));

/** The keydown event <press> as the key map reads it: its key, "Esc", "C-d" with Ctrl, or null
 *  for a press that is no key of a sequence (Shift alone) or is the browser's or system's. */
export function tokenOf({ key, ctrlKey, metaKey, altKey }) {
  // Many layouts type a bracket with Option, or with AltGr, which says Ctrl and Alt
  const bracket = altKey && (key === "[" || key === "]");
  if (metaKey || (altKey && !bracket)) return null;
  if (key === "Escape") return "Esc";
  if (key.length !== 1) return null;
  return ctrlKey && !bracket ? `C-${key.toLowerCase()}` : key;
}

/** What the press <token> does after the presses <pending>: {took (it is the key map's), action
 *  (the one it ends, or null), pending (the presses of a longer key under way)}. A press that
 *  goes on with no key ends the one under way and does nothing else. */
export function step(bindings, pending, token) {
  const typed = [...pending, token];
  const going = bindings.filter((b) => startsWith(b.seq, typed));
  const exact = going.find((b) => b.seq.length === typed.length);
  if (exact) return { took: true, action: exact.name, pending: [] };
  return { took: going.length > 0 || pending.length > 0, action: null, pending: going.length ? typed : [] };
}

/** The which-key list after the presses <pending>: {title, keys: [{key, text}]}, or null with
 *  nothing under way. A press that several keys go on from is their group. */
export function whichKey(bindings, pending) {
  if (!pending.length) return null;
  const next = new Map();
  for (const b of bindings) {
    if (b.seq.length <= pending.length || !startsWith(b.seq, pending)) continue;
    const token = b.seq[pending.length];
    const more = b.seq.length > pending.length + 1;
    next.set(token, next.has(token) ? { token, text: `+${b.group.toLowerCase()}`, group: true }
      : { token, text: b.text, group: more && b.group });
  }
  return {
    title: `${pending.map(shown).join(" ")} …`,
    keys: [...next.values()].map(({ token, text }) => ({ key: shown(token), text })),
  };
}

// Why <action>'s key doesn't do what it says, or ""
function note(action, all) {
  if (action.unread) return UNREAD;
  if (!action.seq.length) return "off";
  if (takesPageKey(action)) return `off: ${shown(action.seq[0])} is one of the page's own keys`;
  const other = all.find((b) => b.name !== action.name && b.seq.length && !takesPageKey(b)
    && (startsWith(b.seq, action.seq) || startsWith(action.seq, b.seq)));
  return other ? `clashes with ${other.name}` : "";
}

/** All keys, with the reviewer's <changes>: [{title, rows: [{name, text, key (as written),
 *  changed, note (why it doesn't work, or "")}]}]. */
export function allKeys(changes) {
  const all = keyed(changes);
  return GROUPS.map(([title]) => ({
    title,
    rows: all.filter((a) => a.group === title).map((a) => ({
      name: a.name, text: a.text, key: a.key, changed: Object.hasOwn(changes, a.name), note: note(a, all),
    })),
  }));
}
