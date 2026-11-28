// Layout D starts here: the page state, a poll of the review API every 1.5 s, and the page drawn
// from its model whenever the state changes.

import { exportReview, markViewed, send, setAgent, setDone, setMode, setStatus, setView, showThreadIn, viewedNext } from "./actions.js";
import { problemText, reviewApi } from "./api.js";
import { drawConversation } from "./draw_conversation.js";
import { drawPathPopover, drawFiles, fileAtTop, firstLineShown, isLineInSight, isOnScreen, isThreadOnScreen, placePathPopover, reveal, scrollToFile, scrollToTarget, uncover } from "./draw_files.js";
import { drawHeader, keepPinnedHeight } from "./draw_header.js";
import { drawSettings } from "./draw_settings.js";
import { drawTree } from "./draw_tree.js";
import { drawPicker } from "./draw_views.js";
import { drawVim } from "./draw_vim.js";
import { el, icon } from "./dom.js";
import { keyAction } from "./keys.js";
import { pageModel } from "./page.js";
import { newestOnly, readReview } from "./poll.js";
import { boxOf, cancelDraft, dragEnd, dragOver, dragStart, isSummary, showBoxTab, summaryKey, typeIn } from "./drafts.js";
import { closeKeys, followSystem, keepSettings, readSettings, resetKeys, seeVimNotice, setKey, setVim, switchTheme, vimOn } from "./settings.js";
import { closePicker, filterPicker } from "./picker.js";
import { closePathPopover, dismissWarning, filterFiles, followThread, foldFile, initialState, openSubmit, pollFailed, polled, scrolledTo, selectFile, setLayout, setOpen, showTab, sortTree, systemTheme, toggleComments, togglePathPopover, withVim } from "./state.js";
import { addressWithTab, tabIn } from "./tabs.js";
import { escapedBox, keyPress, pick as pickItem, pickerKey } from "./vim.js";

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

// The text on the clipboard: the async API where the page may use it, else a selected textarea
async function copy(text) {
  try { await navigator.clipboard.writeText(text); return; } catch { /* fall through */ }
  const area = el("textarea", { class: "off-screen" });
  area.value = text;
  document.body.append(area);
  area.select();
  const took = document.execCommand("copy");
  area.remove();
  if (!took) throw new Error("the browser refused to copy");
}

const LINE_PX = 20; // a diff line's height (style.css)

// What the Vim keys ask of the window (vim.js)
const screen = {
  firstShown: firstLineShown,
  isShown: isOnScreen,
  isThreadShown: isThreadOnScreen,
  fileInView: fileAtTop,
  halfScreen: () => Math.max(4, Math.floor(window.innerHeight / (2 * LINE_PX))),
  reveal,
  scrollLines: (by) => window.scrollBy(0, by * 2 * LINE_PX), // two lines a press, so j gets on
  scrollEnd: (bottom) => window.scrollTo(0, bottom ? document.body.scrollHeight : 0),
  top: () => window.scrollTo(0, 0),
  showThread: scrollToTarget,
  focusBox: (key) => focusBox(key),
  leaveBox: (key) => { if (boxIn(document.activeElement) === key) document.activeElement.blur(); },
};

const use = { api, state: () => state, update, refresh, copy, scrollTo: ({ file }) => scrollToFile(file), screen };

// Put the caret in the comment box <key>, and bring it into sight
function focusBox(key) {
  const area = document.querySelector(`[data-focus="${CSS.escape(`box:${key}`)}"]`);
  area?.focus({ preventScroll: true });
  area?.scrollIntoView({ block: "nearest" });
}

const on = {
  fold: (path, folded) => update((s) => foldFile(s, path, folded)),
  togglePathPopover: (path) => update((s) => togglePathPopover(s, path, fileAtTop())),
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
  // With the Vim keys on, the box is remembered, for i to go back into, and no button is given
  // the focus, which would take Space
  escape: (key) => (isSummary(key) && !vimOn(state) ? on.openSubmit(false) : update((s) => escapedBox(s, key))),
  pick: (value) => pickItem(use, value),
  setKey: (action, key) => update((s) => setKey(s, action, key)),
  setStatus: (id, status) => setStatus(use, id, status),
  setOpen: (id, open) => update((s) => setOpen(s, id, open)),
  follow(id, target) {
    update((s) => followThread(s, id, target.file));
    scrollToTarget(target, id);
  },
  async showIn(id, view) {
    const target = await showThreadIn(use, id, view);
    if (target) on.follow(id, target);
  },
  dismissWarning: (id) => update((s) => dismissWarning(s, id)),
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
  const was = state;
  update((s) => sortTree(s, by));
  if (state !== was) window.scrollTo(0, 0);
}

// A menu opens under its button, its <side> edge on the button's, and in the window even when
// the button has scrolled out of it
function placeUnder(menu, button, side) {
  $(menu).addEventListener("beforetoggle", (e) => {
    if (e.newState !== "open") return;
    const at = $(button).getBoundingClientRect();
    $(menu).style.top = `${Math.max(8, at.bottom + 4)}px`;
    $(menu).style[side] = `${Math.max(8, side === "left" ? at.left : document.documentElement.clientWidth - at.right)}px`;
  });
}

// Another view has other files: read them from the top, where a refusal is said too. True when
// the watcher shows <view>
async function pickView(view) {
  $("view-menu").hidePopover();
  const took = await setView(use, view);
  window.scrollTo(0, 0);
  return took;
}

// What each of the page's keys does (keys.js)
const KEY_DOES = {
  filterFiles() {
    openTab("files");
    $("filter").focus();
    $("filter").select();
  },
  pickView() {
    openTab("files");
    if (!$("view-menu").matches(":popover-open")) $("view-menu").showPopover();
    $("view-choices").querySelector("[aria-current]")?.focus();
  },
  toggleComments: () => update(toggleComments),
  conversation: () => openTab("conversation"),
  files: () => openTab("files"),
};

function drawPage() {
  const page = pageModel(state);
  document.title = page.title;
  drawSettings(page.settings, on);
  drawHeader(page, on);
  drawVim(page.vim, on);
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
  if (body.kind !== "files") return drawPathPopover(null);
  drawPicker(body.picker, pickView);
  $("comments-hidden").hidden = !body.commentsHidden;
  document.querySelector(".columns").classList.toggle("no-tree", !body.sidebar);
  drawTree(body, pick, sort);
  drawFiles(body, on);
  drawPathPopover(body.popover);
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
const MENUS = ["view-menu", "more", "settings"];
const boxIn = (node) => (node.dataset?.focus?.startsWith("box:") ? node.dataset.focus.slice("box:".length) : null);

// The control the keyboard moved the focus to, which Space presses (vim.js). Read as the focus
// arrives: by the keydown, a clicked one shows the keyboard's ring too
let tabbedTo = null;
document.addEventListener("focusin", (e) => { tabbedTo = e.target.matches(":focus-visible") ? e.target : null; });
// Where Tab went may be under the headers. Read as the key comes up, when the browser has moved
// the focus: a click, a redraw or the window coming back must not move the page
document.addEventListener("keyup", (e) => { if (e.key === "Tab" && document.activeElement !== document.body) uncover(document.activeElement); });

// The Vim keys have a press first (vim.js). True when it was theirs
function vimTook(e) {
  const { key, ctrlKey, metaKey, altKey, isComposing, defaultPrevented, repeat, target } = e;
  const ringed = target === tabbedTo;
  if (!keyPress(use, { key, ctrlKey, metaKey, altKey, isComposing, defaultPrevented, repeat, target, ringed, box: boxIn(target) })) return false;
  e.preventDefault(); // else the key is typed into the box it just gave the caret to
  // A menu left open would be over what the key did
  for (const menu of MENUS) if ($(menu).matches(":popover-open")) $(menu).hidePopover();
  return true;
}

// A click leaves behind the box Escape left: i is the page's own key again
document.addEventListener("mousedown", () => update((s) => (s.own.vim.leftBox ? withVim(s, { leftBox: null }) : s)), true);
document.addEventListener("keydown", (e) => {
  // A dialog of the Vim keys' is over the page: no key of the page's acts behind it
  if (state.own.vim.picker || state.own.vim.help || vimTook(e)) return;
  const action = state.server && keyAction(e);
  if (!action) return;
  e.preventDefault(); // else the key is typed into the box it just gave the caret to
  // The view menu is Files changed's: another key's move would leave it open over the page
  if (action !== "pickView" && $("view-menu").matches(":popover-open")) $("view-menu").hidePopover();
  KEY_DOES[action]();
});
placeUnder("view-menu", "view-button", "left");
placeUnder("more", "open-more", "right");
keepPinnedHeight();
$("commit").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" || e.isComposing) return;
  const view = $("commit").value.trim();
  if (view && await pickView(view)) $("commit").value = "";
});
$("agent").addEventListener("change", async (e) => {
  await setAgent(use, e.target.value);
  draw(); // a pick that wasn't taken goes back
});
// The browser closed the review path's popover (Escape, a click elsewhere): the state follows.
// This comes after the close, when another file's may be open already
$("path-popover").addEventListener("toggle", () => { if (!$("path-popover").matches(":popover-open")) update(closePathPopover); });
// While it is open, it goes where its line goes
function followLine() {
  const file = state.own.pathPopover?.file;
  if (!file) return;
  update((s) => scrolledTo(s, fileAtTop(), isLineInSight(file)));
  if (state.own.pathPopover) placePathPopover(file);
}
window.addEventListener("scroll", followLine, { passive: true });
window.addEventListener("resize", () => { if (state.own.pathPopover) placePathPopover(state.own.pathPopover.file); });
$("export").addEventListener("click", () => {
  $("more").hidePopover();
  exportReview(use);
});
$("show-comments").addEventListener("click", () => update(toggleComments));
$("submit-close").addEventListener("click", () => on.openSubmit(false));
$("controls").addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.isComposing) on.openSubmit(false); });
$("filter").addEventListener("input", (e) => update((s) => filterFiles(s, e.target.value)));
$("vim-on").addEventListener("change", (e) => update((s) => setVim(s, e.target.checked)));
$("open-keys").addEventListener("click", () => {
  $("settings").hidePopover();
  update((s) => withVim(s, { help: true }));
});
$("vim-notice-off").addEventListener("click", () => update((s) => setVim(seeVimNotice(s), false)));
$("vim-notice-seen").addEventListener("click", () => update(seeVimNotice));
$("picker").addEventListener("keydown", (e) => { if (!e.isComposing && pickerKey(use, e)) e.preventDefault(); });
$("picker-query").addEventListener("input", (e) => update((s) => filterPicker(s, e.target.value)));
// Closed by the browser, as by a second Escape: the state follows. This comes after the close, when
// another picker may be open already
$("picker").addEventListener("close", () => { if (!$("picker").open) update((s) => (s.own.vim.picker ? closePicker(s) : s)); });
$("keys-help").addEventListener("close", () => { if (!$("keys-help").open) update((s) => (s.own.vim.help ? closeKeys(s) : s)); });
$("keys-close").addEventListener("click", () => update(closeKeys));
$("keys-reset").addEventListener("click", () => update(resetKeys));
draw();
poll();
