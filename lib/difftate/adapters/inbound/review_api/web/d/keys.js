// Layout D's keys, GitHub's: what a key press does. DOM-free: main.js does it.

const KEYS = { t: "filterFiles", c: "pickView", i: "toggleComments", 1: "conversation", 2: "files" };

// The inputs that take no text
const NOT_TYPED_IN = new Set(["button", "checkbox", "radio"]);

// Whether a press at <target> is the reviewer typing, or picking from a list by its letters
const typing = ({ tagName, type, isContentEditable }) => Boolean(isContentEditable)
  || tagName === "TEXTAREA" || tagName === "SELECT" || (tagName === "INPUT" && !NOT_TYPED_IN.has(type));

/** What the keydown event <press> does: "filterFiles", "pickView", "toggleComments",
 *  "conversation" or "files" (those two tabs), or null: no key of the page's, typed text, a
 *  shortcut of the browser's, or a key held down. */
export function keyAction(press) {
  if (press.ctrlKey || press.metaKey || press.altKey || press.isComposing || press.defaultPrevented || press.repeat) return null;
  if (typing(press.target)) return null;
  return Object.hasOwn(KEYS, press.key) ? KEYS[press.key] : null;
}
