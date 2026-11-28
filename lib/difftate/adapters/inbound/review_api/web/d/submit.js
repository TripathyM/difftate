// Layout D's review mode (GLOSSARY.md: live or batched) and what Submit review shows.
// DOM-free: draw_header.js draws it.

import { summaryKey } from "./drafts.js";
import { boxModel, whereText } from "./threads.js";

/** "1 held thread", "3 held threads" */
export const heldThreads = (n) => `${n} held thread${n === 1 ? "" : "s"}`;

/** The two review modes, the review's current one marked: [{mode, text, current, title}]. */
export function reviewModes(state) {
  const { mode: current, held } = state.server.mode;
  const submits = held.length ? ` Switching submits the ${held.length === 1 ? "held thread" : heldThreads(held.length)}.` : "";
  return [
    { mode: "live", text: "Live", title: `Each comment goes to the coding agent as you write it.${current === "live" ? "" : submits}` },
    { mode: "batched", text: "Batched", title: "Comments are held until you submit the review." },
  ].map((m) => ({ ...m, current: m.mode === current }));
}

// What of a held thread waits for the submit: the reviewer's comments that no run has been sent,
// which are those after the last reply or progress note
function pendingComments({ comments }) {
  const sent = comments.findLastIndex((c) => c.kind === "reply" || c.kind === "progress");
  return comments.slice(sent + 1).filter((c) => c.author === "reviewer").map((c) => c.body);
}

// The panel: the held threads, in GET /api/mode's order (the oldest first), and the summary
function panel(state) {
  const { mode, threads, review } = state.server;
  const pending = mode.held.map((id) => threads.find((t) => t.id === id)).filter(Boolean)
    .map((t) => ({ id: t.id, where: whereText(t.anchor), comments: pendingComments(t) }));
  return {
    pending, none: mode.held.length ? "" : "No comment is held.",
    box: {
      ...boxModel(state, summaryKey(review.id), "summary"),
      title: "Summary (optional)", hint: "A summary is posted as a general comment, then all that is held is submitted.",
    },
  };
}

/** The Submit review button, or null in a live review, which holds nothing: {text, count (of held
 *  threads), panel: null while it is closed, else {pending: [{id, where, comments: [text]}], none
 *  (what to say with nothing held), box: the summary's (boxModel plus {title, hint})}}. */
export function submitReviewControl(state) {
  const { mode, held } = state.server.mode;
  if (mode !== "batched") return null;
  return { text: "Submit review", count: held.length, panel: state.own.submitOpen ? panel(state) : null };
}
