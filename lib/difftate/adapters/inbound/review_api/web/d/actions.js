// What the reviewer does in layout D that the review API keeps. DOM-free: it is given {api
// (api.js), state (the page state now), update (changes it with a function of it), refresh (polls
// now)}.

import { problemText } from "./api.js";
import { boxFailed, boxOf, boxSending, dropBox, generalReview, repliesTo, summaryKey, summaryReview, typeIn } from "./drafts.js";
import { doneAnswered, modeAnswered, noted, openSubmit, refused, threadRefused, threadTaken, viewedAnswered } from "./state.js";
import { heldThreads } from "./submit.js";

/** Mark <path> viewed, or not. True when the API took it; else the state says why not. */
export async function markViewed({ api, update, refresh }, path, viewed) {
  let files;
  try {
    ({ files } = await api("PUT", "/api/viewed", { file: path, viewed }));
  } catch (e) {
    update((s) => refused(s, problemText(e)));
    return false;
  }
  update((s) => viewedAnswered(refused(s, ""), files));
  // At once, so that a poll already under way, which may have the old marks, is dropped
  await refresh();
  return true;
}

const ELSEWHERE = "Another branch is checked out now: nothing was changed.";

// Make a change to the review shown, with call(): its answer, or null when it didn't happen, and
// then the page says why. The calls that change a review go to the one the folder is on, and the
// watcher may have followed a checkout since the last poll: so ask which that is first
async function onShownReview({ api, state, update, refresh }, call) {
  const { id } = state().server.review;
  update((s) => noted(s, ""));
  try {
    if ((await api("GET", "/api/review")).id !== id) {
      await refresh();
      update((s) => refused(s, ELSEWHERE));
      return null;
    }
    return await call();
  } catch (e) {
    update((s) => refused(s, problemText(e)));
    return null;
  }
}

/** Change the review mode to <mode> ("live" or "batched"). Changing to live submits the held
 *  threads, and the page says so. True when the review is in <mode>. */
export async function setMode(use, mode) {
  const { state, update, refresh } = use;
  if (mode === state().server.mode.mode) return true;
  const answer = await onShownReview(use, () => use.api("PUT", "/api/mode", { mode }));
  if (!answer) return false;
  const n = answer.submitted.length;
  const notice = n ? `Live: ${heldThreads(n)} ${n === 1 ? "was" : "were"} submitted to the coding agent.` : "";
  update((s) => noted(modeAnswered(refused(s, ""), answer), notice));
  await refresh();
  return true;
}

/** Mark the review Done at the commit its branch is at, or undo it (<done> false). True when the
 *  API took it. */
export async function setDone(use, done) {
  const answer = await onShownReview(use, () => use.api("PUT", "/api/done", { done }));
  if (!answer) return false;
  use.update((s) => doneAnswered(refused(s, ""), answer));
  await use.refresh();
  return true;
}

const threadPath = (id) => `/api/threads/${encodeURIComponent(id)}`;

// The call that sends the box <key>: a draft opens a thread on its own lines, the general box one
// on no line, written in the <view> shown, and a reply box adds a comment to its thread
function sendCall(key, { anchor: a }, body, view) {
  if (generalReview(key) !== null) return ["/api/threads", { anchor: null, body, view }];
  if (!a) return [`${threadPath(repliesTo(key))}/comments`, { body }];
  const anchor = { file: a.path, side: a.side, startLine: a.start, endLine: a.end, code: a.code, ...(a.version ? { version: a.version } : {}) };
  return ["/api/threads", { anchor, body, view: a.view }];
}

const WAITS = "Another branch is checked out now: the draft waits for its own branch.";

/** Send what the box <key> holds (drafts.js). <start> (Start a review): the review is switched to
 *  batched first, so the comment is held. True when the API took it; else the box keeps its text
 *  and says why not. */
export async function send(use, key, { start = false } = {}) {
  if (summaryReview(key) !== null) return submitReview(use); // the summary's send is the submit
  const { api, state, update, refresh } = use;
  const box = boxOf(state(), key);
  const body = box.text.trim();
  if (!body || box.sending) return false;
  const [path, payload] = sendCall(key, box, body, state().server.changeset.view ?? "");
  // The review a new thread is for; a reply goes to its thread, whatever is checked out. The mode
  // is the review's the folder is on, so a switch is for the review shown
  const review = box.anchor?.review ?? generalReview(key) ?? (start ? state().server.review.id : null);
  update((s) => boxSending(s, key));
  try {
    // The watcher may have followed a checkout since the last poll, and a new thread goes to the
    // review the folder is on: ask which, so none is opened on another branch's
    if (review !== null && (await api("GET", "/api/review")).id !== review) {
      update((s) => boxFailed(s, key, WAITS));
      await refresh();
      // Said on the page too: the poll may have taken the box away, with its branch
      update((s) => refused(s, WAITS));
      return false;
    }
    if (start) {
      const mode = await api("PUT", "/api/mode", { mode: "batched" });
      update((s) => modeAnswered(s, mode));
    }
    await api("POST", path, payload);
  } catch (e) {
    update((s) => boxFailed(s, key, problemText(e)));
    return false;
  }
  // Polled first, so the thread is there as its draft goes (unless a newer poll overtakes this one)
  await refresh();
  update((s) => refused(dropBox(s, key), ""));
  return true;
}

const NOTHING = "There is nothing to submit: no comment is held and the summary is empty.";

/** Submit the batched review: the summary written in the panel, if any, is posted as a general
 *  thread, then the held threads, it among them, are submitted. True when both were taken; else
 *  the panel says why not. */
export async function submitReview({ api, state, update, refresh }) {
  const { review, changeset, mode } = state().server;
  const key = summaryKey(review.id);
  const { text, sending } = boxOf(state(), key);
  const summary = text.trim();
  if (sending) return false;
  if (!summary && !mode.held.length) {
    update((s) => boxFailed(s, key, NOTHING));
    return false;
  }
  update((s) => noted(boxSending(s, key), ""));
  let posted = false;
  let answer;
  try {
    // Both calls go to the review the folder is on: ask which, as for a new thread
    if ((await api("GET", "/api/review")).id !== review.id) {
      update((s) => boxFailed(s, key, WAITS));
      await refresh();
      update((s) => refused(s, WAITS));
      return false;
    }
    if (summary) {
      await api("POST", "/api/threads", { anchor: null, body: summary, view: changeset.view ?? "" });
      posted = true;
      // Its text goes now: pressing again after a failed submit mustn't post it twice
      update((s) => boxSending(typeIn(s, key, ""), key));
    }
    answer = await api("POST", "/api/submit", {});
  } catch (e) {
    const why = problemText(e);
    update((s) => boxFailed(s, key, posted ? `Your summary is posted, but the review isn't submitted: ${why}` : why));
    if (posted) await refresh();
    return false;
  }
  const n = answer.submitted.length;
  const notice = n ? `Submitted ${heldThreads(n)} to the coding agent.` : "Nothing was held: nothing to submit.";
  update((s) => noted(openSubmit(modeAnswered(refused(dropBox(s, key), ""), answer), false), notice));
  await refresh();
  return true;
}

/** Resolve, dismiss or reopen ("open") the thread <id>. True when the API took it; else the
 *  state says why not, on that thread. */
export async function setStatus({ api, update, refresh }, id, status) {
  try {
    await api("PATCH", `${threadPath(id)}/status`, { status });
  } catch (e) {
    update((s) => threadRefused(s, id, problemText(e)));
    return false;
  }
  update((s) => threadTaken(s, id));
  await refresh();
  return true;
}
