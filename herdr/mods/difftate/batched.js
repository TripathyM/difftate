// The Review tab's batched mode: what it shows for the review mode and the held threads, and what it
// says after a change of mode, a Submit or a comment. Plain JavaScript, no Herdr, so
// tests/test_review_tab_batched.py runs it in node. Wording matches the browser viewer's.
// <mode> is what GET /api/mode answers: {mode: "live"|"batched", held: [thread ids]}.

const heldCount = (n) => `${n} held thread${n === 1 ? "" : "s"}`;

export const isBatched = (mode) => mode?.mode === "batched";

// The mode the toggle action changes to
export const otherMode = (mode) => (isBatched(mode) ? "live" : "batched");

// The header's text for a batched review: "Batched · 2 held"; null for a live one (it holds nothing),
// and for a watcher that has no /api/mode
export const modeLabel = (mode) => (isBatched(mode) ? `Batched · ${mode.held?.length ?? 0} held` : null);

// What a thread's state is called: the API's thread state while open (held, waiting, ...), else its status
export const STATE_LABEL = {
  held: "held until you submit", waiting: "waiting for agent", queued: "queued", working: "agent working",
  replied: "agent replied", failed: "failed: no reply", resolved: "resolved", dismissed: "dismissed",
};

// Said after changing the review to <mode>; <submitted> is the ids a change to live submitted
export function modeChangedMessage(mode, submitted) {
  if (mode === "batched") return "Batched: comments are held until you submit";
  return submitted?.length ? `Live: ${heldCount(submitted.length)} submitted to the coding agent` : "Live: comments go to the coding agent as you write them";
}

// Submit does something only in a batched review that holds threads; else says why not
export function submitProblem(mode) {
  if (!isBatched(mode)) return "Not a batched review: nothing to submit (Space M makes it one)";
  if (!mode.held?.length) return "Nothing is held: nothing to submit";
  return null;
}

// Said after a Submit; <submitted> is the ids it sent
export const submittedMessage = (submitted) => (submitted?.length ? `Submitted ${heldCount(submitted.length)}` : "Nothing is held: nothing to submit");

// Said after a new thread or a reply is written
export function commentMessage(mode, kind) {
  if (isBatched(mode)) return "Comment held until you submit";
  return kind === "thread" ? "Comment sent. The agent picks it up within a few seconds." : "Comment sent";
}
