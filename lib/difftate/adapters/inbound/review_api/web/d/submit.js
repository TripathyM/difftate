// Layout D's review mode (GLOSSARY.md: live or batched) and Submit review.
// DOM-free: draw_header.js draws it.

import { summaryKey } from "./drafts.js";
import { boxModel, whereText } from "./threads.js";

/** "1 held thread", "3 held threads" */
export const heldThreads = (n) => `${n} held thread${n === 1 ? "" : "s"}`;

const MODES = [
  { mode: "live", text: "Live", title: "Each comment goes to the coding agent as you write it. Switching to Live sends held comments to the coding agent: it asks first." },
  { mode: "batched", text: "Batched", title: "Comments are held until you submit the review." },
];

/** The two review modes, the review's current one marked: [{mode, text, current, title}]. */
export const reviewModes = (state) => MODES.map((m) => ({ ...m, current: m.mode === state.server.mode.mode }));

// What of a held thread waits for the submit. The API marks no comment held, so this follows the
// core's rule as far as the comments show it. A run's progress note: what came before it was sent.
// The reply that follows is that run's, which doesn't answer a comment written while it worked.
// Any other reply answers what came before it. A held thread has such a comment, so when this
// finds none, its newest one is it
function heldComments({ comments }) {
  let waiting = [];
  let running = false;
  for (const c of comments) {
    if (c.kind === "progress") [waiting, running] = [[], true];
    else if (c.kind === "reply") {
      if (!running) waiting = [];
      running = false;
    } else if (c.author === "reviewer") waiting.push(c);
  }
  if (!waiting.length) waiting = comments.filter((c) => c.author === "reviewer").slice(-1);
  return waiting.map((c) => c.body);
}

// The panel: the held threads and the summary
function panel(state) {
  const { mode, review } = state.server;
  return {
    held: heldNow(state.server), none: mode.held.length ? "" : "No comment is held.",
    box: {
      ...boxModel(state, summaryKey(review.id), "summary"),
      title: "Summary (optional)", hint: "A summary is posted as a general thread, then all that is held is submitted.",
    },
  };
}

// The held threads, in GET /api/mode's order (the oldest first), each with what of it is held
const heldNow = ({ mode, threads }) => mode.held.map((id) => threads.find((t) => t.id === id)).filter(Boolean)
  .map((t) => ({ id: t.id, where: whereText(t.anchor), comments: heldComments(t) }));

/** What the page asks before a change to live sends what is held, or null: {text, yes, no}. */
export function liveConfirm(state) {
  if (!state.own.askLive) return null;
  const n = heldNow(state.server).reduce((sum, t) => sum + t.comments.length, 0);
  return { text: `Send ${n} held comment${n === 1 ? "" : "s"} to the agent now?`, yes: "Send and go live", no: "Cancel" };
}

const LIVE_OFF = "Live: comments go to the coding agent as you write them, so there is nothing to submit.";

/** The Submit review button, which stays in a live review, turned off, so that the header doesn't
 *  move: {text, count (of held threads), off (why it can't be pressed, or ""), panel: null while
 *  it is closed, else {held: [{id, where, comments: [text]}], none (what to say with nothing
 *  held), box: the summary's (boxModel plus {title, hint})}}. */
export function submitReviewControl(state) {
  const { mode, held } = state.server.mode;
  const off = mode === "batched" ? "" : LIVE_OFF;
  return { text: "Submit review", count: held.length, off, panel: !off && state.own.submitOpen ? panel(state) : null };
}
