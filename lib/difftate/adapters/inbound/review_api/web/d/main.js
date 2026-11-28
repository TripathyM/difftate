// Layout D starts here: the page state, a poll of the review API every 1.5 s, and the page drawn
// from its model whenever the state changes.

import { markViewed } from "./actions.js";
import { problemText, reviewApi } from "./api.js";
import { drawFiles, scrollToFile } from "./draw_files.js";
import { drawHeader } from "./draw_header.js";
import { drawTree } from "./draw_tree.js";
import { pageModel } from "./page.js";
import { newestOnly, readReview } from "./poll.js";
import { filterFiles, foldFile, initialState, pollFailed, polled, selectFile } from "./state.js";

const POLL_MS = 1500;
// The checked-out folder this page is about: its address names it (?folder=)
const api = reviewApi((...args) => fetch(...args), new URLSearchParams(location.search).get("folder") ?? "");
const $ = (id) => document.getElementById(id);

let state = initialState();
function update(change) {
  const next = change(state);
  if (next === state) return;
  state = next;
  draw();
}

const refresh = newestOnly(
  () => readReview(api, state.server),
  (answers) => update((s) => polled(s, answers)),
  (e) => update((s) => pollFailed(s, problemText(e))),
);

const on = {
  fold: (path, folded) => update((s) => foldFile(s, path, folded)),
  viewed: (path, viewed) => markViewed({ api, update, refresh }, path, viewed),
};

function pick(path) {
  update((s) => selectFile(s, path));
  scrollToFile(path);
}

function draw() {
  const page = pageModel(state);
  document.title = page.title;
  drawHeader(page);
  $("problem").textContent = page.problem;
  $("problem").hidden = !page.problem;
  const { body } = page;
  $("loading").hidden = body.kind !== "loading";
  $("files-tab").hidden = body.kind !== "files";
  if (body.kind !== "files") return;
  $("progress").replaceChildren(body.progress.text, Object.assign(document.createElement("progress"), { max: body.progress.total || 1, value: body.progress.viewed }));
  $("filtered").textContent = body.filtered;
  $("filtered").hidden = !body.filtered;
  $("empty").textContent = body.empty;
  $("empty").hidden = !body.empty;
  drawTree(body.tree, pick);
  drawFiles(body.files, on);
}

async function poll() {
  try {
    await refresh();
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

$("filter").addEventListener("input", (e) => update((s) => filterFiles(s, e.target.value)));
draw();
poll();
