// The Review tab's Done action: what it shows for a Done review, and what it warns about before
// marking one. Plain JavaScript, no Herdr, so tests/test_review_tab_done.py runs it in node.
// <status> is what GET /api/done answers: {done, commit, time, head, lastMark, openThreads, runsInFlight}.

export const shortCommit = (sha) => (sha ?? "").slice(0, 7);

// "Done at 0123456" for a Done review, else null
export const doneLabel = (status) => (status?.done ? `Done at ${shortCommit(status.commit)}` : null);

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// What is still going on in the review: every open thread, and a line of its own for the threads
// whose run is queued or working. Empty when nothing is.
export function doneWarnings(status) {
  const warnings = [];
  if (status?.openThreads > 0) warnings.push(`${plural(status.openThreads, "thread", "threads")} still open`);
  if (status?.runsInFlight > 0) warnings.push(`${plural(status.runsInFlight, "run", "runs")} still working`);
  return warnings;
}

// The question before marking Done, or null when nothing is open
export function doneQuestion(status) {
  const warnings = doneWarnings(status);
  return warnings.length ? `${warnings.join(" · ")}. Mark Done anyway?` : null;
}
