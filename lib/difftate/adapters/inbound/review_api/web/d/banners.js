// Layout D's banners under the header. DOM-free: draw_header.js draws them.

/** What the banner says while the review waits for a run, or "": another branch is checked out,
 *  and a run holds the watcher on this review. */
export function waitingText({ waitingForRun, checkedOut }) {
  if (!waitingForRun) return "";
  // A commit checked out with no branch of its own to review is named by its full id
  const name = checkedOut?.replace(/^([0-9a-f]{7})[0-9a-f]{33,}$/, "$1");
  return `${name ? `${name} is` : "Another branch is"} checked out: you can go on reading, but this review takes no new thread, viewed mark or Done. The watcher moves to that branch's review once the run in progress ends.`;
}

/** The review's warnings to show, [{id, text}]: each id once, but those the reviewer
 *  <dismissed>. */
export function warningsShown({ warnings = [] }, dismissed) {
  const byId = new Map(warnings.map(({ id, text }) => [id, { id, text }]));
  return [...byId.values()].filter((w) => !dismissed.includes(w.id));
}
