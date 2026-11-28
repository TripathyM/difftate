// Layout D's Vim keys at work: what a press does to the page, and what the page then shows of
// them. DOM-free: it is given actions.js's use, and use.screen, which main.js makes of the
// window: {firstShown() (the first line on screen, a target, or null), isShown(target) (whether
// it is on screen), isThreadShown(id) (whether any of its card is), fileInView() (the path of the file at the top, or null), halfScreen() (in
// lines), reveal(target) (brings it into sight), scrollLines(by), scrollEnd(bottom), top(),
// showThread(target or null, id), focusBox(key), leaveBox(key) (takes the caret out of it)}. A
// target is scroll.js's {file, row}.

import { exportReview, markViewed, send, setAgent, setDone, setMode, setStatus, setView, viewedNext } from "./actions.js";
import { firstIn, move, nextChange, nextFile, nextThread, pickSide, targetOf, threadsAt, toEnd } from "./cursor.js";
import { boxOf, closeDraft, dragEnd, dragOver, dragStart, escapeBox, generalKey, generalReview, isSummary, repliesTo, replyKey, showBoxTab, summaryKey } from "./drafts.js";
import { asShown, filesChanged } from "./files_changed.js";
import { allKeys, bindingsOf, step, tokenOf, whichKey } from "./keymap.js";
import { typing } from "./keys.js";
import { closePicker, movePicker, openPicker, pickerModel, pickerPress } from "./picker.js";
import { threadTarget, viewedNextTarget } from "./scroll.js";
import { settingsModel, vimOn } from "./settings.js";
import { closePathPopover, dialogOpen, followThread, foldFile, isOpen, openSubmit, selectFile, setLayout, setOpen, showTab, togglePathPopover, toggleTree, withVim } from "./state.js";
import { labels, whereText } from "./threads.js";
import { viewPicker } from "./views.js";

const say = (use, said) => use.update((s) => withVim(s, { said }));

// The Files changed tab's files with the threads in them, and as the reviewer sees them
const allFiles = (use) => filesChanged(use.state()).files;
const shownFiles = (use) => asShown(filesChanged(use.state()), use.state()).files;

// ---------- the line cursor ----------

// Where the cursor's line is shown, as a target: null once its file is folded or the diff has it
// no longer, and on the Conversation tab
function cursorShown(use) {
  const { cursor } = use.state().own.vim;
  return onFiles(use) && cursor?.side ? targetOf(shownFiles(use), cursor) : null;
}

// Where a move starts: the cursor while it is on screen, or a selection holds it, else the
// first line on screen
function moveStart(use) {
  const { cursor, visual } = use.state().own.vim;
  const at = cursorShown(use);
  if (at && (visual || use.screen.isShown(at))) return cursor;
  return use.screen.firstShown();
}

// The same as a spot, with its line: null without a line on screen
function spotFrom(use) {
  const here = moveStart(use);
  return here?.side ? here : move(shownFiles(use), here, 0)?.spot ?? null;
}

// Put the cursor where <got> ({spot, target}) says, and bring it into sight
function place(use, got) {
  if (!got) return;
  use.update((s) => withVim(s, { cursor: got.spot, focus: null }));
  use.screen.reveal(got.target);
}

const onFiles = (use) => use.state().own.tab === "files";

// <by> lines on: the Conversation tab has none, so it scrolls
function moveBy(use, by) {
  if (!onFiles(use)) return use.screen.scrollLines(by);
  place(use, move(shownFiles(use), moveStart(use), by, use.state().own.vim.visual));
}

function moveToEnd(use, last) {
  if (!onFiles(use)) return use.screen.scrollEnd(last);
  place(use, toEnd(shownFiles(use), moveStart(use), last, use.state().own.vim.visual));
}

function toSide(use, to) {
  if (!onFiles(use) || use.state().own.vim.visual) return; // a selection keeps its side
  const here = spotFrom(use);
  if (here) place(use, pickSide(shownFiles(use), here, to));
}

function select(use) {
  if (use.state().own.vim.visual) return use.update((s) => withVim(s, { visual: null }));
  const spot = onFiles(use) ? spotFrom(use) : null;
  if (!spot) return;
  use.update((s) => withVim(s, { cursor: spot, visual: spot, focus: null }));
  use.screen.reveal(targetOf(shownFiles(use), spot));
}

// ---------- jumps ----------

function hunk(use, by) {
  use.update((s) => withVim(showTab(s, "files"), { visual: null }));
  const got = nextChange(shownFiles(use), moveStart(use), by);
  if (!got) return say(use, "No changes on screen: ]f goes to a file");
  place(use, got);
  if (got.wrapped) say(use, by > 0 ? "Back to the first change on screen" : "Round to the last change on screen");
}

// The file the keys are about: the cursor's while it is on screen, else the one at the top
function currentFile(use) {
  const { cursor } = use.state().own.vim;
  if (cursor) {
    const target = cursor.side ? targetOf(shownFiles(use), cursor) : { file: cursor.file, row: null };
    if (target && use.screen.isShown(target)) return cursor.file;
  }
  return use.screen.fileInView();
}

// The cursor goes to <path>'s first line, or to the file alone where it shows none
function cursorIn(use, path) {
  const cursor = firstIn(shownFiles(use), path)?.spot ?? { file: path };
  use.update((s) => withVim(s, { cursor, visual: null, focus: null }));
}

function goFile(use, path) {
  use.update((s) => selectFile(showTab(s, "files"), path));
  cursorIn(use, path);
  use.screen.reveal({ file: path, row: null });
}

function stepFile(use, by) {
  const here = onFiles(use) ? currentFile(use) : null;
  const path = nextFile(allFiles(use), here, by);
  if (path) goFile(use, path);
}

// ---------- threads ----------

// Show <thread> where it is: on its lines in Files changed, else on the Conversation tab. The
// keys then act on it
function goThread(use, thread) {
  const target = thread.anchor ? threadTarget(allFiles(use), thread) : null;
  use.update((s) => {
    const shown = target ? followThread(s, thread.id, target.file) : showTab(s, "conversation");
    return thread.status === "open" ? shown : setOpen(shown, thread.id, true);
  });
  const a = thread.anchor;
  const spot = target && target.row !== null
    ? move(allFiles(use), { file: a.file, side: a.side, line: a.endLine }, 0)?.spot : null;
  use.update((s) => withVim(s, { ...(spot && { cursor: spot }), visual: null, focus: thread.id }));
  use.screen.showThread(target, thread.id);
}

function stepThread(use, by) {
  const { focus } = use.state().own.vim;
  const spot = onFiles(use) ? spotFrom(use) : null;
  const here = focus ? { ...spot, thread: focus } : spot;
  const got = nextThread(allFiles(use), use.state().server.threads, here, by);
  if (!got) return say(use, "No open threads");
  goThread(use, got.thread);
  if (got.wrapped) say(use, `Wrapped to the ${by > 0 ? "first" : "last"} open thread`);
}

const firstLine = (thread) => (thread.comments[0]?.body ?? "").split("\n")[0];
const threadItem = (thread) => ({
  text: `${whereText(thread.anchor)}: ${firstLine(thread)}`,
  hint: labels(thread).map((l) => l.text).join(" · "),
  value: thread.id,
});

const threadById = (use, id) => use.state().server.threads.find((t) => t.id === id);

async function changeStatus(use, id, status, done) {
  say(use, await setStatus(use, id, status) ? done : use.state().own.errors[id]);
}

// What an action does to its thread, which threads it takes, and what to say without one
const ON_THREAD = {
  thread: { takes: () => true, none: "No thread on this line", run: goThread },
  add_comment: {
    takes: (t) => t.status === "open", none: "No open thread on this line",
    run(use, thread) {
      // The Conversation tab has its card too, so the reviewer stays there
      if (onFiles(use)) goThread(use, thread);
      use.update((s) => showBoxTab(s, replyKey(thread.id), "write"));
      use.screen.focusBox(replyKey(thread.id));
    },
  },
  resolve: { takes: (t) => t.status === "open", none: "No open thread on this line", run: (use, t) => changeStatus(use, t.id, "resolved", "Resolved") },
  reopen: { takes: (t) => t.status !== "open", none: "No resolved or dismissed thread on this line", run: (use, t) => changeStatus(use, t.id, "open", "Reopened") },
};

// Do <action> to the thread the keys point at: the one gone to, else the one on the cursor's
// line, each only while it is on screen; with several there, the reviewer picks
function onThread(use, action) {
  const { takes, none, run } = ON_THREAD[action];
  const { focus, cursor } = use.state().own.vim;
  const focused = focus && use.screen.isThreadShown(focus) ? threadById(use, focus) : null;
  const at = cursorShown(use);
  const here = at && use.screen.isShown(at) ? cursor : null;
  if (!focused && !here) return say(use, "Put the cursor on a line first (j), or go to a thread with ]r");
  const threads = (focused ? [focused] : threadsAt(use.state().server.threads, here)).filter(takes);
  if (!threads.length) return say(use, none);
  if (threads.length === 1) return run(use, threads[0]);
  use.update((s) => openPicker(s, { title: "Which thread?", kind: "which", action, items: threads.map(threadItem) }));
}

// General threads first, then the files' in the changeset's order and by line; in each group the
// open ones first (the Neovim viewer's order)
function pickThread(use) {
  const order = allFiles(use).map((f) => f.path);
  const rank = (t) => {
    const at = order.indexOf(t.anchor.file);
    return at < 0 ? order.length : at;
  };
  const openFirst = (list) => [...list].sort((a, b) => (a.status !== "open") - (b.status !== "open"));
  const { threads } = use.state().server;
  const onLines = threads.filter((t) => t.anchor).sort((a, b) => rank(a) - rank(b)
    || a.anchor.file.localeCompare(b.anchor.file) || a.anchor.endLine - b.anchor.endLine);
  const items = [...openFirst(threads.filter((t) => !t.anchor)), ...openFirst(onLines)].map(threadItem);
  if (!items.length) return say(use, "No threads yet");
  use.update((s) => openPicker(s, { title: "Threads", kind: "threads", items }));
}

function expand(use) {
  const closed = use.state().server.threads.filter((t) => t.status !== "open");
  const all = closed.every((t) => isOpen(use.state(), t.id));
  use.update((s) => closed.reduce((next, t) => setOpen(next, t.id, !all), s));
  say(use, all ? "Resolved and dismissed threads are one line" : "Every thread is expanded");
}

// ---------- the review ----------

function comment(use) {
  const { cursor, visual } = use.state().own.vim;
  if (!cursorShown(use)) return say(use, "Put the cursor on a line first (j)");
  const anchor = visual ?? cursor;
  const [first, last] = [Math.min(anchor.line, cursor.line), Math.max(anchor.line, cursor.line)];
  const spot = (line) => ({ path: anchor.file, side: anchor.side, line });
  const picked = dragOver(dragStart(use.state(), spot(first)), spot(last));
  if (picked.own.drag.to !== last) return say(use, "Those lines aren't all in one piece of the diff: select fewer");
  use.update(() => withVim(dragEnd(picked), { visual: null, focus: null }));
  const { active } = use.state().own;
  if (active) use.screen.focusBox(active);
}

function general(use) {
  const key = generalKey(use.state().server.review.id);
  use.update((s) => showBoxTab(showTab(s, "conversation"), key, "write"));
  use.screen.focusBox(key);
}

// What the review path says of the file the keys are about, in full
function reviewPathOfFile(use) {
  if (use.state().own.pathPopover) return use.update(closePathPopover);
  const path = onFiles(use) ? currentFile(use) : null;
  if (!path) return say(use, "No file on screen");
  if (!use.state().server.reviewPath) return say(use, "There is no review path");
  if (!allFiles(use).find((f) => f.path === path)?.pathLine) return say(use, `The review path says nothing of ${path}`);
  use.update((s) => togglePathPopover(s, path, use.screen.fileInView()));
}

async function viewed(use) {
  const path = onFiles(use) ? currentFile(use) : null;
  if (!path) return say(use, "No file on screen");
  use.update((s) => withVim(s, { visual: null, focus: null }));
  if (use.state().server.viewed.includes(path)) {
    if (!await markViewed(use, path, false)) return;
    use.update((s) => foldFile(s, path, false));
    return say(use, `Not viewed: ${path}`);
  }
  const next = viewedNextTarget(allFiles(use), path);
  if (!await viewedNext(use, path)) return;
  // A viewed file folds, so the cursor goes on
  if (next) cursorIn(use, next.file);
  say(use, `Viewed ${path}`);
}

function pickFile(use) {
  const items = allFiles(use).map((f) => ({ text: f.path, hint: `+${f.additions} −${f.deletions}${f.viewed ? " · viewed" : ""}`, value: f.path }));
  if (!items.length) return say(use, "No changed files");
  use.update((s) => openPicker(s, { title: "Changed files", kind: "files", items }));
}

function pickView(use) {
  const items = viewPicker(use.state()).choices.map((c) => ({ text: c.text, hint: c.current ? "shown now" : "", value: c.view }));
  use.update((s) => openPicker(s, { title: "Choose the view", kind: "views", items }));
}

function pickAgent(use) {
  const { agent } = settingsModel(use.state());
  if (!agent || agent.disabled) return say(use, "The agent list can't be read");
  const items = agent.choices.map((c) => ({ text: c.text, hint: c.value === agent.value ? "chosen" : "", value: c.value }));
  use.update((s) => openPicker(s, { title: "The coding agent that replies in this review", kind: "agent", items }));
}

function submit(use) {
  if (use.state().server.mode.mode !== "batched") return say(use, "Live: nothing is held, so there is nothing to submit");
  use.update((s) => openSubmit(s, true));
  use.screen.focusBox(summaryKey(use.state().server.review.id));
}

async function done(use) {
  const mark = !use.state().server.done.done;
  if (await setDone(use, mark)) say(use, mark ? "Marked Done" : "Not done any more");
}

// What each action (keymap.js) does
const RUN = {
  down: (use) => moveBy(use, 1), up: (use) => moveBy(use, -1),
  half_down: (use) => moveBy(use, use.screen.halfScreen()), half_up: (use) => moveBy(use, -use.screen.halfScreen()),
  first: (use) => moveToEnd(use, false), last: (use) => moveToEnd(use, true),
  old_side: (use) => toSide(use, "old"), new_side: (use) => toSide(use, "new"),
  visual_line: select, visual: select,
  next_hunk: (use) => hunk(use, 1), previous_hunk: (use) => hunk(use, -1),
  next: (use) => stepThread(use, 1), previous: (use) => stepThread(use, -1),
  next_file: (use) => stepFile(use, 1), previous_file: (use) => stepFile(use, -1),
  comment,
  thread: (use) => onThread(use, "thread"), add_comment: (use) => onThread(use, "add_comment"),
  resolve: (use) => onThread(use, "resolve"), reopen: (use) => onThread(use, "reopen"),
  expand, general, viewed, done, submit, review_path: reviewPathOfFile,
  threads: pickThread, files: pickFile, views: pickView, agent: pickAgent,
  files_sidebar(use) {
    // The tree is Files changed's: from the other tab, the key brings it
    if (onFiles(use)) return use.update(toggleTree);
    use.update((s) => (s.own.hideTree ? toggleTree(showTab(s, "files")) : showTab(s, "files")));
  },
  mode: (use) => setMode(use, use.state().server.mode.mode === "live" ? "batched" : "live"),
  export: exportReview,
  side_by_side: (use) => use.update((s) => setLayout(s, s.own.settings.layout === "split" ? "unified" : "split")),
  help: (use) => use.update((s) => withVim(s, { help: true })),
};

// What a pick in each picker does
const PICKED = {
  which: (use, id, { action }) => ON_THREAD[action].run(use, threadById(use, id)),
  threads: (use, id) => goThread(use, threadById(use, id)),
  files: goFile,
  async views(use, view) {
    use.screen.top();
    await setView(use, view);
  },
  agent: setAgent,
};

/** Pick the picker's item with <value>. */
export function pick(use, value) {
  const { picker } = use.state().own.vim;
  use.update(closePicker);
  return PICKED[picker.kind](use, value, picker);
}

/** A keydown event in the picker: true, or the pick's promise, when it is the picker's. */
export function pickerKey(use, press) {
  const does = pickerPress(press);
  if (!does) return false;
  if (does.move) use.update((s) => movePicker(s, does.move));
  else if (does === "close") use.update(closePicker);
  else {
    const item = pickerModel(use.state()).items.find((i) => i.current);
    if (item) return pick(use, item.value) ?? true;
  }
  return true;
}

// ---------- the comment box Esc left ----------

/** The state once the reviewer pressed Escape in the box <key> (drafts.js): with the Vim keys,
 *  i goes back into it and q closes it, unless Escape dropped it. */
export function escapedBox(state, key) {
  const next = escapeBox(state, key);
  const dropped = boxOf(state, key).anchor && !Object.hasOwn(next.own.boxes, key);
  return vimOn(state) && !dropped ? withVim(next, { leftBox: key, pending: [], said: "" }) : next;
}

// Back into the box <key>, wherever it is
function backInto(use, key) {
  const { anchor } = boxOf(use.state(), key);
  use.update((s) => {
    let next = withVim(showBoxTab(s, key, "write"), { leftBox: null });
    if (isSummary(key)) next = openSubmit(next, true);
    else if (generalReview(key) !== null) next = showTab(next, "conversation");
    else if (anchor) next = selectFile(showTab(next, "files"), anchor.path);
    else if (next.own.tab === "files") next = followReply(next, repliesTo(key));
    return next;
  });
  use.screen.focusBox(key);
}

// The thread <id>'s reply box in Files changed is in its file, which may be folded by now
function followReply(state, id) {
  const file = state.server.threads.find((t) => t.id === id)?.anchor?.file;
  return file ? followThread(state, id, file) : state;
}

// A draft whose lines the diff no longer shows as picked is out of their way already: closed or
// not, it stays in sight, so that what was typed isn't lost
function stays(use, key) {
  const { files, loose } = filesChanged(use.state());
  return [...loose, ...files.flatMap((f) => f.top.drafts)].some((d) => d.key === key);
}

// q: the box closes, and what it holds stays
function closeLeft(use, key) {
  if (isSummary(key)) use.update((s) => openSubmit(s, false));
  let said = "";
  const { anchor, text } = boxOf(use.state(), key);
  if (anchor) {
    use.update((s) => closeDraft(s, key));
    if (text.trim()) {
      said = stays(use, key) ? "The draft stays in sight: the diff no longer shows the lines you picked"
        : "Draft kept: comment on those lines again to get it back";
    }
  }
  use.update((s) => withVim(s, { leftBox: null, said }));
}

// Ctrl+S: send what the box <key> holds, and leave a box that stays (a reply's, the general
// one), as the Neovim viewer closes its own
async function sendFrom(use, key) {
  if (!await send(use, key)) return;
  if (use.state().own.vim.leftBox === key) use.update((s) => withVim(s, { leftBox: null }));
  use.screen.leaveBox(key);
}

// ---------- a press ----------

// A key held down goes on with these; anything else it does once
const REPEATS = new Set(["down", "up", "half_down", "half_up"]);

const isSend = (press) => press.ctrlKey && !press.metaKey && !press.altKey && press.key.toLowerCase() === "s";

/** The keydown event <press> (with box: the key of the comment box it is in, and ringed: the
 *  keyboard moved the focus to the control pressed in). False when it isn't the Vim keys': they are
 *  off, the reviewer is typing, or it is a key of the page's or the browser's. Else true, or the
 *  promise of what it does. */
export function keyPress(use, press) {
  const state = use.state();
  const { vim } = state.own;
  if (!vimOn(state) || !state.server || press.defaultPrevented || press.isComposing || dialogOpen(state)) return false;
  const typed = typing(press.target);
  const sends = isSend(press) ? (typed ? press.box : vim.leftBox) : null;
  if (sends) return press.repeat ? true : sendFrom(use, sends);
  if (typed) return false;
  const token = tokenOf(press);
  if (!token) return false;
  if (token === "Esc") {
    // The review path's popover is what is on top: it closes first, and a selection stays
    if (state.own.pathPopover) {
      use.update(closePathPopover);
      return true;
    }
    const under = vim.pending.length || vim.visual || vim.leftBox;
    if (under || vim.said) use.update((s) => withVim(s, { pending: [], visual: null, leftBox: null, said: "" }));
    return Boolean(under); // else the page's own Esc, which closes its menus
  }
  // A button the keyboard went to is pressed with Space
  if (token === " " && press.ringed && !vim.pending.length) return false;
  if (vim.leftBox && !vim.pending.length && (token === "i" || token === "q")) {
    if (!press.repeat) (token === "i" ? backInto : closeLeft)(use, vim.leftBox);
    return true;
  }
  const { took, action, pending } = step(bindingsOf(state.own.settings.keys), vim.pending, token);
  // A Ctrl press that ends no key is the browser's (Ctrl+C)
  const browsers = token.startsWith("C-") && !action && !pending.length;
  if (took && !browsers && press.repeat && !REPEATS.has(action)) return true;
  if (!took || browsers) {
    if (vim.pending.length || vim.leftBox || vim.said) use.update((s) => withVim(s, { pending: [], leftBox: null, said: "" }));
    return false;
  }
  use.update((s) => withVim(s, { pending, leftBox: null, said: "" }));
  return (action && RUN[action](use)) ?? true;
}

// ---------- what the page shows of them ----------

const EXTENSION = "A Vim browser extension (such as Vimium) takes keys before this page sees them: turn it off for the viewer, on http://127.0.0.1.";

const BOX_KEYS = [
  ["Ctrl+S", "Send what the box holds"], ["Esc", "Leave the box, keeping the text"],
  ["i", "Back into the box you just left"], ["q", "Close the box you just left, keeping the text"],
];

// The line at the bottom: what a key has to tell, else what Esc left under way
function line({ said, leftBox, visual }) {
  if (said) return said;
  if (leftBox) return "i goes back into the box · q closes it, keeping the text";
  return visual ? "Selecting lines: Space r c comments on them, Esc stops" : "";
}

/** What the Vim keys show of the page <state>: {on, notice (what an extension does to them,
 *  until the reviewer has seen it, else ""), which (whichKey()'s list, or null), line (what to
 *  say at the bottom, or ""), picker (picker.js), help: null, or all keys: {extension, groups
 *  (allKeys()), fixed: [[key, what it does in a comment box]]}}. */
export function vimModel(state) {
  const { vim, settings } = state.own;
  const on = vimOn(state);
  if (!on) return { on, notice: "", which: null, line: "", picker: null, help: null };
  return {
    on,
    notice: settings.vimNotice === "seen" ? "" : `Vim keys are on (? shows them). ${EXTENSION}`,
    which: whichKey(bindingsOf(settings.keys), vim.pending),
    line: line(vim),
    picker: pickerModel(state),
    help: vim.help ? { extension: EXTENSION, groups: allKeys(settings.keys), fixed: BOX_KEYS } : null,
  };
}
