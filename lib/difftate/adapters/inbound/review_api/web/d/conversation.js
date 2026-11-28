// Layout D's Conversation tab: the timeline of threads. DOM-free: draw_conversation.js draws it.

import { generalKey } from "./drafts.js";
import { threadTarget } from "./scroll.js";
import { boxModel, heldHint, linesText, threadCard } from "./threads.js";

const opened = (t) => t.comments[0]?.time ?? "";

// What a card on the timeline says of where its thread is, and where its link goes
function where(thread, files) {
  const a = thread.anchor;
  if (!a) return { text: "On the whole changeset", target: null };
  return { text: `${a.file}, ${linesText(a.side, a.startLine, a.endLine)}`, target: threadTarget(files, thread) };
}

// A thread whose lines the diff shows needs no copy of their code: its link goes to them
function card(thread, state, files) {
  const at = where(thread, files);
  const linesInDiff = at.target !== null && at.target.row !== null;
  return threadCard(thread, state, { placed: linesInDiff, where: at });
}

/** The tab's model from the page <state>, which has a poll's answers, and the <files> of the
 *  Files changed tab (files_changed.js): {kind: "conversation", threads (every thread's card,
 *  threads.js, the one opened first at the top; where: {text, target (scroll.js) | null}), empty
 *  (what to say without a thread), general (the box for a general thread: boxModel plus {title,
 *  hint})}. */
export function conversation(state, files) {
  const threads = [...state.server.threads].sort((a, b) => opened(a).localeCompare(opened(b)))
    .map((t) => card(t, state, files));
  const general = {
    ...boxModel(state, generalKey(state.server.review.id), "general"),
    title: "Comment on the whole changeset", hint: heldHint(state),
  };
  return { kind: "conversation", threads, empty: threads.length ? "" : "No threads yet.", general };
}
