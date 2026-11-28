// What the reviewer does in layout D that the review API keeps. DOM-free: it is given {api
// (api.js), state (the page state now), update (changes it with a function of it), refresh (polls
// now), scrollTo (scrolls to a target of scroll.js), copy (puts a text on the clipboard)}.

import { ApiError, problemText } from "./api.js";
import { boxFailed, boxOf, boxSending, dropBox, generalReview, repliesTo, summaryKey, isSummary, typeIn } from "./drafts.js";
import { filesChanged } from "./files_changed.js";
import { threadTarget, viewedNextTarget } from "./scroll.js";
import { overrideOf } from "./settings.js";
import { agentAnswered, askLive, closeAskLive, doneAnswered, foldFile, modeAnswered, noted, onReview, openSubmit, refused, threadRefused, threadTaken, viewedAnswered, withVim } from "./state.js";
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

/** Viewed, next under <path>: fold it, put the top of the next file at the top of the window
 *  (use.scrollTo, with scroll.js's target), and mark it viewed. It is folded first, here: the
 *  viewed mark may arrive with a later poll, and a fold after the scroll would move the next
 *  file. True when the API took the mark; else the file opens again and is brought back. */
export async function viewedNext(use, path) {
  const { state, update, scrollTo } = use;
  const target = viewedNextTarget(filesChanged(state()).files, path);
  update((s) => foldFile(s, path, true));
  if (target) scrollTo(target);
  if (await markViewed(use, path, true)) return true;
  update((s) => foldFile(s, path, false));
  scrollTo({ file: path, row: null });
  return false;
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

// What a switch to <mode> that submitted nothing says
const FROM_NOW = {
  batched: "Batched: comments are held until you submit the review.",
  live: "Live: comments go to the coding agent as you write them.",
};

/** Change the review mode to <mode> ("live" or "batched"), and say what it did: changing to live
 *  submits the held threads, so with any held it only asks (page.js's confirm). True when the
 *  review is in <mode>. <byKey>: a Vim key asked. */
export async function setMode(use, mode, { byKey = false } = {}) {
  const { state, update } = use;
  if (mode === state().server.mode.mode) return true;
  if (mode === "live" && state().server.mode.held.length) {
    update((s) => askLive(s, byKey));
    return false;
  }
  return switchMode(use, mode);
}

/** The reviewer said yes to what a change to live asks (setMode). True when the review is live. */
export async function confirmLive(use) {
  const asked = use.state().own.askLive;
  if (!asked) return false;
  use.update(closeAskLive); // first, so that a second press sends nothing
  const taken = await switchMode(use, "live");
  if (taken && asked.byKey) use.update((s) => withVim(s, { said: s.own.notice }));
  return taken;
}

async function switchMode(use, mode) {
  const { state, update, refresh } = use;
  const { id } = state().server.review;
  const answer = await onShownReview(use, () => use.api("PUT", "/api/mode", { mode }));
  if (!answer) return false;
  const n = answer.submitted.length;
  const notice = n ? `Live: ${heldThreads(n)} ${n === 1 ? "was" : "were"} submitted to the coding agent.` : FROM_NOW[mode];
  update((s) => onReview(s, id, (on) => noted(modeAnswered(refused(on, ""), answer), notice)));
  await refresh();
  return true;
}

/** Mark the review Done at the commit its branch is at, or undo it (<done> false). True when the
 *  API took it. */
export async function setDone(use, done) {
  const { id } = use.state().server.review;
  const answer = await onShownReview(use, () => use.api("PUT", "/api/done", { done }));
  if (!answer) return false;
  use.update((s) => onReview(s, id, (on) => doneAnswered(refused(on, ""), answer)));
  await use.refresh();
  return true;
}

/** Show <view> in this review's viewers, and read it: its changeset, threads and review path.
 *  True when the API took it; else the state says why not. It is put even when the page shows
 *  it: another view, picked just before, may be on its way. */
export async function setView({ api, update, refresh }, view) {
  update((s) => noted(s, ""));
  try {
    await api("PUT", "/api/view", { view });
  } catch (e) {
    update((s) => refused(s, problemText(e)));
    return false;
  }
  update((s) => refused(s, ""));
  await refresh();
  return true;
}

/** Show it in <view>, on a thread's card: switch there. Where the thread <id>'s lines are in it
 *  (a target of scroll.js), or null. */
export async function showThreadIn(use, id, view) {
  if (!await setView(use, view)) return null;
  const thread = use.state().server.threads.find((t) => t.id === id);
  return thread?.anchor ? threadTarget(filesChanged(use.state()).files, thread) : null;
}

/** Choose <agent>, a name on the agent list, to reply in this review, or "" to clear the
 *  review's own choice. True when the API took it. */
export async function setAgent(use, agent) {
  const { agent: now, review } = use.state().server;
  if (agent === overrideOf(now)) return true;
  const answer = await onShownReview(use, () => use.api("PUT", "/api/agent", { agent: agent || null }));
  if (!answer) return false;
  const notice = agent ? `${agent} replies in this review, from the next run.`
    : `This review's agent override is cleared: ${answer.agent} (${answer.source}) replies, from the next run.`;
  use.update((s) => onReview(s, review.id, (on) => noted(agentAnswered(refused(on, ""), answer), notice)));
  await use.refresh();
  return true;
}

/** Copy the review's export, for an agent session the reviewer starts, to the clipboard
 *  (use.copy). Its reply command names the review's folder, so that the session can reply from
 *  anywhere. It changes no thread. True when it was copied. */
export async function exportReview({ api, state, update, copy }) {
  const { id, folder } = state().server.review;
  update((s) => noted(s, ""));
  try {
    // The export is of the review the folder is on, which a checkout changes
    if ((await api("GET", "/api/review")).id !== id) throw new Error("another branch is checked out now.");
    const text = await api("GET", `/api/export${folder ? `?reply_folder=${encodeURIComponent(folder)}` : ""}`);
    if (!text?.trim()) throw new Error("The watcher gave no export (is it up to date?)");
    await copy(text);
  } catch (e) {
    // A failed call is said in the page's words; the rest say themselves
    update((s) => refused(s, `Could not export: ${e instanceof ApiError ? problemText(e) : e.message}`));
    return false;
  }
  update((s) => noted(refused(s, ""), "Export copied: paste it into an agent session."));
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

// Whether the box <key>, for <review>, has to wait: the watcher may have followed a checkout
// since the last poll, and what it holds would go to the other branch's review. <start>: it waits
// for a run too, as the API would take the switch to batched and then refuse the comment. Then
// the box and the page say so: the page too, as the poll may have taken the box away, with its
// branch
async function mustWait({ api, update, refresh }, key, review, start = false) {
  const now = await api("GET", "/api/review");
  if (now.id === review && !(start && now.waitingForRun)) return false;
  update((s) => boxFailed(s, key, WAITS));
  await refresh();
  update((s) => refused(s, WAITS));
  return true;
}

/** Send what the box <key> holds (drafts.js). <start> (Start a review): the review is switched to
 *  batched first, so the comment is held. True when the API took it; else the box keeps its text
 *  and says why not. */
export async function send(use, key, { start = false } = {}) {
  if (isSummary(key)) return submitReview(use); // the summary's send is the submit
  const { api, state, update, refresh } = use;
  const box = boxOf(state(), key);
  const body = box.text.trim();
  if (!body || box.sending) return false;
  const [path, payload] = sendCall(key, box, body, state().server.changeset.view ?? "");
  // The review a new thread is for; a reply goes to its thread, whatever is checked out. The mode
  // is the review's the folder is on, so a switch is for the review shown
  const review = box.anchor?.review ?? generalReview(key) ?? (start ? state().server.review.id : null);
  update((s) => noted(boxSending(s, key), ""));
  try {
    if (review !== null && await mustWait(use, key, review, start)) return false;
    if (start) {
      const mode = await api("PUT", "/api/mode", { mode: "batched" });
      update((s) => onReview(s, review, (on) => modeAnswered(on, mode)));
    }
    await api("POST", path, payload);
  } catch (e) {
    update((s) => boxFailed(s, key, problemText(e)));
    return false;
  }
  // Polled first, so the thread is there as its draft goes
  await refresh();
  update((s) => refused(dropBox(s, key), ""));
  return true;
}

const NOTHING = "There is nothing to submit: no comment is held and the summary is empty.";

/** Submit the batched review: the summary written in the panel, if any, is posted as a general
 *  thread, then the held threads, it among them, are submitted. True when both were taken; else
 *  the panel says why not. */
export async function submitReview(use) {
  const { api, state, update, refresh } = use;
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
    if (await mustWait(use, key, review.id)) return false;
    if (summary) {
      await api("POST", "/api/threads", { anchor: null, body: summary, view: changeset.view ?? "" });
      posted = true;
      // Its text goes now: pressing again after a failed submit mustn't post it twice
      update((s) => boxSending(typeIn(s, key, ""), key));
    }
    answer = await api("POST", "/api/submit", {});
  } catch (e) {
    const why = posted ? `Your summary is posted, but the review isn't submitted: ${problemText(e)}` : problemText(e);
    update((s) => boxFailed(s, key, why));
    if (posted) await refresh();
    // The panel says why. When it was closed meanwhile, the page does
    if (!state().own.submitOpen) update((s) => refused(s, why));
    return false;
  }
  const n = answer.submitted.length;
  const notice = n ? `Submitted ${heldThreads(n)} to the coding agent.` : "Nothing was held: nothing to submit.";
  update((s) => onReview(dropBox(s, key), review.id, (on) => noted(openSubmit(modeAnswered(refused(on, ""), answer), false), notice)));
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
