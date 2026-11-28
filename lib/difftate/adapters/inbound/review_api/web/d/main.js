// Layout D starts here: the page state, a poll of the review API every 1.5 s, and the page drawn
// from its model whenever the state changes.

import { markViewed, send, setDone, setMode, setStatus, viewedNext } from "./actions.js";
import { problemText, reviewApi } from "./api.js";
import { drawConversation } from "./draw_conversation.js";
import { drawFiles, scrollToFile, scrollToTarget } from "./draw_files.js";
import { drawHeader } from "./draw_header.js";
import { drawSettings } from "./draw_settings.js";
import { drawTree } from "./draw_tree.js";
import { icon } from "./dom.js";
import { pageModel } from "./page.js";
import { newestOnly, readReview } from "./poll.js";
import { boxOf, cancelDraft, dragEnd, dragOver, dragStart, escapeBox, isSummary, showBoxTab, summaryKey, typeIn } from "./drafts.js";
import { followSystem, keepSettings, readSettings, switchTheme } from "./settings.js";
import { filterFiles, followThread, foldFile, initialState, openSubmit, pollFailed, polled, selectFile, setLayout, setOpen, showTab, sortTree, systemTheme } from "./state.js";
import { addressWithTab, tabIn } from "./tabs.js";

const POLL_MS = 1500;
// The checked-out folder this page is about: its address names it (?folder=)
const api = reviewApi((...args) => fetch(...args), new URLSearchParams(location.search).get("folder") ?? "");
const $ = (id) => document.getElementById(id);

// A browser set to keep nothing throws on the name itself
const storage = (() => { try { return localStorage; } catch { return null; } })();
const darkSystem = matchMedia("(prefers-color-scheme: dark)");

let state = systemTheme(initialState(tabIn(location.search), readSettings(storage)), darkSystem.matches);
function update(change) {
  const next = change(state);
  if (next === state) return;
  keepSettings(storage, state.own.settings, next.own.settings);
  state = next;
  draw();
}

const refresh = newestOnly(
  () => readReview(api, state.server),
  (answers) => update((s) => polled(s, answers)),
  (e) => update((s) => pollFailed(s, problemText(e))),
);

const use = { api, state: () => state, update, refresh, scrollTo: ({ file }) => scrollToFile(file) };

// Put the caret in the comment box <key>, and bring it into sight
function focusBox(key) {
  const area = document.querySelector(`[data-focus="${CSS.escape(`box:${key}`)}"]`);
  area?.focus({ preventScroll: true });
  area?.scrollIntoView({ block: "nearest" });
}

const on = {
  fold: (path, folded) => update((s) => foldFile(s, path, folded)),
  viewed: (path, viewed) => markViewed(use, path, viewed),
  viewedNext: (path) => viewedNext(use, path),
  dragStart: (spot, extend) => update((s) => dragStart(s, spot, { extend })),
  dragOver: (spot) => update((s) => dragOver(s, spot)),
  dragEnd() {
    if (!state.own.drag) return;
    update(dragEnd);
    if (state.own.active) focusBox(state.own.active);
  },
  // The textarea shows what is typed already: nothing is drawn, unless an error is to go
  type(key, text) {
    if (boxOf(state, key).error) update((s) => typeIn(s, key, text));
    else state = typeIn(state, key, text);
  },
  boxTab(key, tab) {
    update((s) => showBoxTab(s, key, tab));
    if (tab === "write") focusBox(key);
  },
  send: (key) => send(use, key),
  startReview: (key) => send(use, key, { start: true }),
  tab: (tab) => openTab(tab),
  setLayout: (layout) => update((s) => setLayout(s, layout)),
  setMode: (mode) => setMode(use, mode),
  setDone: (done) => setDone(use, done),
  openSubmit(open) {
    if (open === state.own.submitOpen) return;
    const inside = $("controls").contains(document.activeElement);
    update((s) => openSubmit(s, open));
    if (open) focusBox(summaryKey(state.server.review.id));
    else if (inside || document.activeElement === document.body) document.querySelector('[data-focus="submit-review"]')?.focus({ preventScroll: true });
  },
  cancel: (key) => update((s) => cancelDraft(s, key)),
  escape: (key) => (isSummary(key) ? on.openSubmit(false) : update((s) => escapeBox(s, key))),
  setStatus: (id, status) => setStatus(use, id, status),
  setOpen: (id, open) => update((s) => setOpen(s, id, open)),
  follow(id, target) {
    update((s) => followThread(s, id, target.file));
    scrollToTarget(target, id);
  },
};
// The pick ends wherever the pointer is let go
document.addEventListener("mouseup", () => on.dragEnd());

// The reviewer changed tab: the other one starts at its top
function openTab(tab) {
  if (tab === state.own.tab) return;
  update((s) => showTab(s, tab));
  window.scrollTo(0, 0);
}

function pick(path) {
  update((s) => selectFile(s, path));
  scrollToFile(path);
}

// The files are in another order now: read them from the top
function sort(by) {
  if (by === state.own.sort) return;
  update((s) => sortTree(s, by));
  window.scrollTo(0, 0);
}

function drawPage() {
  const page = pageModel(state);
  document.title = page.title;
  drawSettings(page.settings, on);
  drawHeader(page, on);
  // The address keeps the tab, so that a reload shows it
  if (page.tab && tabIn(location.search) !== page.tab) history.replaceState(history.state, "", addressWithTab(location.href, page.tab));
  $("problem").textContent = page.problem;
  $("problem").hidden = !page.problem;
  const { body } = page;
  $("loading").textContent = body.text ?? "";
  $("loading").hidden = body.kind !== "loading";
  $("files-tab").hidden = body.kind !== "files";
  $("conversation-tab").hidden = body.kind !== "conversation";
  if (body.kind === "conversation") drawConversation(body, on);
  if (body.kind !== "files") return;
  drawTree(body, pick, sort);
  drawFiles(body, on);
}

function draw() {
  // A node drawn anew takes the keyboard's focus with it: give it to the one in its place
  const focused = document.activeElement?.dataset.focus;
  try {
    drawPage();
  } catch (e) {
    // Say so: a page left half drawn would look like the review
    $("problem").textContent = `difftate couldn't draw the review: ${e.message}`;
    $("problem").hidden = false;
    throw e;
  }
  if (focused) document.querySelector(`[data-focus="${CSS.escape(focused)}"]`)?.focus({ preventScroll: true });
}

async function poll() {
  try {
    await refresh();
  } finally {
    setTimeout(poll, POLL_MS);
  }
}

darkSystem.addEventListener("change", (e) => update((s) => systemTheme(s, e.matches)));
$("open-settings").append(icon("settings"));
$("flip-theme").addEventListener("click", () => update(switchTheme));
$("follow-system").addEventListener("change", (e) => update((s) => followSystem(s, e.target.checked)));
$("submit-close").addEventListener("click", () => on.openSubmit(false));
$("controls").addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.isComposing) on.openSubmit(false); });
$("filter").addEventListener("input", (e) => update((s) => filterFiles(s, e.target.value)));
draw();
poll();
