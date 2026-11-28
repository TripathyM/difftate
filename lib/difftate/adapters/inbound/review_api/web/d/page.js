// What layout D shows: the model of the whole page, from the page state. DOM-free: main.js has it
// drawn. It is never blank: until a poll answered, and for a tab it doesn't have, there is still
// something to show.

import { conversation } from "./conversation.js";
import { filesChanged } from "./files_changed.js";
import { needingYou } from "./tabs.js";

// Done is a state of the review, not an approval (GLOSSARY.md, Done)
function header({ review, done }) {
  return { branch: review.branch, base: review.base, state: done.done ? "Done" : "In review", done: done.done };
}

function tabs({ own, server }, files) {
  const waiting = needingYou(server.threads);
  return [
    { id: "conversation", text: "Conversation", count: server.threads.length, needs: waiting ? `${waiting} need${waiting === 1 ? "s" : ""} you` : "" },
    { id: "files", text: "Files changed", count: files.files.length, needs: "" },
  ].map((t) => ({ ...t, current: (own.tab === "conversation") === (t.id === "conversation") }));
}

/** {title, problem, header: null | {branch, base, state, done}, tab (the one shown, null before
 *  the first answers), note (why it opened), tabs: [{id, text, count, current, needs (that the
 *  tab needs the reviewer, or "")}], body: {kind: "loading", text} | the Conversation tab | the
 *  Files changed tab (files_changed.js)}. */
export function pageModel(state) {
  const { server } = state;
  const problem = state.problem || state.refused;
  if (!server) return { title: "difftate", problem, header: null, tab: null, note: "", tabs: [], body: { kind: "loading", text: "Loading the review…" } };
  const files = filesChanged(state);
  const body = state.own.tab === "conversation" ? conversation(state, files.files) : files;
  return {
    title: `difftate · ${server.review.branch}`, problem, header: header(server),
    tab: body.kind, note: state.own.why, tabs: tabs(state, files), body,
  };
}
