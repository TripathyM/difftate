// What layout D shows: the model of the whole page, from the page state. DOM-free: main.js has it
// drawn. It is never blank: until a poll answered, and for a tab it doesn't have, there is still
// something to show.

import { filesChanged } from "./files_changed.js";

// Done is a state of the review, not an approval (GLOSSARY.md, Done)
function header({ review, done }) {
  return { branch: review.branch, base: review.base, state: done.done ? "Done" : "In review", done: done.done };
}

/** {title, problem, header: null | {branch, base, state, done}, tabs: [{id, text, count,
 *  current}], body: {kind: "loading", text} | the Files changed tab (files_changed.js)}. */
export function pageModel(state) {
  const { server } = state;
  const problem = state.problem || state.refused;
  if (!server) return { title: "difftate", problem, header: null, tabs: [], body: { kind: "loading", text: "Loading the review…" } };
  const body = filesChanged(state);
  return {
    title: `difftate · ${server.review.branch}`, problem, header: header(server),
    tabs: [{ id: "files", text: "Files changed", count: body.files.length, current: true }], body,
  };
}
