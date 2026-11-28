// What the reviewer does in layout D that the review API keeps. DOM-free: it is given {api
// (api.js), state (the page state now), update (changes it with a function of it), refresh (polls
// now)}.

import { problemText } from "./api.js";
import { boxFailed, boxOf, boxSending, dropBox, repliesTo } from "./drafts.js";
import { refused, threadRefused, threadTaken, viewedAnswered } from "./state.js";

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

const threadPath = (id) => `/api/threads/${encodeURIComponent(id)}`;

// The call that sends <box>: a draft opens a thread on its own lines, a reply box adds a comment
// to its thread
function sendCall(key, { anchor: a }, body) {
  if (!a) return [`${threadPath(repliesTo(key))}/comments`, { body }];
  const anchor = { file: a.path, side: a.side, startLine: a.start, endLine: a.end, code: a.code, ...(a.version ? { version: a.version } : {}) };
  return ["/api/threads", { anchor, body, view: a.view }];
}

/** Send what the box <key> holds (drafts.js). True when the API took it; else the box keeps its
 *  text and says why not. */
export async function send({ api, state, update, refresh }, key) {
  const box = boxOf(state(), key);
  const body = box.text.trim();
  if (!body || box.sending) return false;
  const [path, payload] = sendCall(key, box, body);
  update((s) => boxSending(s, key));
  try {
    await api("POST", path, payload);
  } catch (e) {
    update((s) => boxFailed(s, key, problemText(e)));
    return false;
  }
  // First, so that the thread is there when its draft goes
  await refresh();
  update((s) => dropBox(s, key));
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
