// What the reviewer does in layout D that the review API keeps. DOM-free: it is given {api
// (api.js), update (changes the page state with a function of it), refresh (polls now)}.

import { problemText } from "./api.js";
import { refused, viewedAnswered } from "./state.js";

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
