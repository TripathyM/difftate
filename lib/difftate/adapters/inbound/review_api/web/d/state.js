// Layout D's page state. server: the last good answers of a poll. own: what is the reviewer's,
// which a poll keeps, so that a poll never throws it away. DOM-free: each function gives a new
// state.

import { firstTab } from "./tabs.js";

// What the Vim keys have under way (vim.js). cursor: the line it is on (cursor.js, a spot; with
// only a file where one shows no line), visual: the line a selection started on, focus: the
// thread last gone to, pending: the presses of a longer key, leftBox: the comment box Esc just left,
// said: what a key has to tell, picker: the list to pick from (picker.js), help: all keys show
export const NO_VIM = { cursor: null, visual: null, focus: null, pending: [], leftBox: null, said: "", picker: null, help: false };

// problem: why the last poll failed; refused: why the last change was refused ("" for neither)
// address: the tab the page's address names, or null. tab: null until the first answers choose it
// (tabs.js), and why: what the page says of why they did, until the reviewer changes tab
// kept: the settings the reviewer chose before (settings.js). systemDark: the system's theme
export const initialState = (address = null, kept = {}) => ({ server: null, problem: "", refused: "", own: { address, tab: null, why: "", notice: "", submitOpen: false, hideComments: false, folds: {}, selected: null, filter: "", sort: "order", boxes: {}, active: null, drag: null, opened: {}, errors: {}, dismissed: [], hideTree: false, vim: NO_VIM, settings: { layout: "unified", theme: null, vim: "on", vimNotice: null, keys: {}, ...kept }, systemDark: false } });

export const withOwn = (state, changes) => ({ ...state, own: { ...state.own, ...changes } });
export const withVim = (state, changes) => withOwn(state, { vim: { ...state.own.vim, ...changes } });

// A fold the reviewer chose holds until the file's viewed mark changes: then the file follows the
// mark again (folded when viewed), whoever changed it
function foldsAfter(folds, before, now) {
  return Object.fromEntries(Object.entries(folds).filter(([path]) => before.includes(path) === now.includes(path)));
}

// Another view numbers its lines otherwise: a pick under way ends, no draft is the one to make
// longer, and a draft with nothing written goes. A written one stays, with the lines and the view
// it was started on
const otherView = (state) => withOwn(state, {
  drag: null, active: null, vim: { ...state.own.vim, cursor: null, visual: null },
  boxes: Object.fromEntries(Object.entries(state.own.boxes).filter(([, box]) => !box.anchor || box.sending || box.text.trim())),
});

/** The state with a poll's <answers> (poll.js): <state> itself when they say nothing new. */
export function polled(state, answers) {
  if (!state.problem && JSON.stringify(answers) === JSON.stringify(state.server)) return state;
  // The first answers choose the tab; after them only the reviewer changes it
  const chosen = state.own.tab ? {} : firstTab(state.own.address, answers.threads);
  // A live review has no Submit review panel: it doesn't come back open with batched
  const closed = answers.mode.mode === "batched" ? {} : { submitOpen: false };
  const polledNow = withOwn({ ...state, server: answers, problem: "" }, { ...chosen, ...closed });
  const next = state.server && state.server.changeset.view !== answers.changeset.view ? otherView(polledNow) : polledNow;
  // Another review (a checkout): its files are others, so what was folded, selected or being
  // picked is gone. Drafts stay: each names its review
  if (state.server && state.server.review.id !== answers.review.id) {
    return withOwn({ ...next, refused: "" }, { why: "", notice: "", submitOpen: false, folds: {}, selected: null, active: null, drag: null, vim: NO_VIM });
  }
  return withOwn(next, { folds: foldsAfter(next.own.folds, state.server?.viewed ?? [], answers.viewed) });
}

/** A poll failed: the last good answers stay, with <problem> saying why. */
export const pollFailed = (state, problem) => (problem === state.problem ? state : { ...state, problem });

/** The state once the API answered a change of <path>'s viewed mark with the viewed <files>. */
export const viewedAnswered = (state, files) => polled(state, { ...state.server, viewed: files });

/** change(state) when the page still shows <review>, else <state>: an answer about a review the
 *  page has left says nothing of the one it shows. */
export const onReview = (state, review, change) => (state.server.review.id === review ? change(state) : state);

/** The state once the API answered a change of the review mode with {mode, held}. */
export const modeAnswered = (state, { mode, held }) => polled(state, { ...state.server, mode: { mode, held } });

/** The state once the API answered a mark of Done, or its undo, with what GET /api/done gives. */
export const doneAnswered = (state, done) => polled(state, { ...state.server, done });

/** The state once the API answered a choice of coding agent, with what GET /api/agent gives. */
export const agentAnswered = (state, agent) => polled(state, { ...state.server, agent });

export const refused = (state, why) => (why === state.refused ? state : { ...state, refused: why });

export const showTab = (state, tab) => (tab === state.own.tab ? state : withOwn(state, { tab, why: "", notice: "" }));
/** What to tell the reviewer their last change did ("" for nothing). */
export const noted = (state, notice) => (notice === state.own.notice ? state : withOwn(state, { notice }));
/** Open the Submit review panel, or close it. */
export const openSubmit = (state, submitOpen) => (submitOpen === state.own.submitOpen ? state : withOwn(state, { submitOpen }));
export const setSetting = (state, name, value) => (value === state.own.settings[name]
  ? state : withOwn(state, { settings: { ...state.own.settings, [name]: value } }));
/** Show the diff as <layout>: "unified" or "split". */
export const setLayout = (state, layout) => setSetting(state, "layout", layout);
/** The system's theme is dark, or not. */
export const systemTheme = (state, systemDark) => (systemDark === state.own.systemDark ? state : withOwn(state, { systemDark }));
/** The reviewer dismissed the warning <id>: it doesn't come back while this page is open. */
export const dismissWarning = (state, id) => withOwn(state, { dismissed: [...state.own.dismissed, id] });
/** Hide the comments in the diff, or show them again. Only Files changed has a diff. */
export const toggleComments = (state) => (state.own.tab !== "files" ? state : withOwn(state, { hideComments: !state.own.hideComments }));
/** Show the comments in the diff, if the reviewer hid them. */
export const showComments = (state) => (state.own.hideComments ? withOwn(state, { hideComments: false }) : state);
/** Hide the file tree beside the diff, or show it again. */
export const toggleTree = (state) => withOwn(state, { hideTree: !state.own.hideTree });
export const filterFiles = (state, filter) => withOwn(state, { filter });
/** Sort the files by <sort>: "order" (Reading order) or "folder". Without a review path there is
 *  nothing to choose, so a path written later is followed. */
export const sortTree = (state, sort) => (sort === state.own.sort || !state.server?.reviewPath ? state : withOwn(state, { sort }));
export const foldFile = (state, path, folded) => withOwn(state, { folds: { ...state.own.folds, [path]: folded } });

/** The reviewer picked <path> in the file tree: it is selected, and open to read. */
export const selectFile = (state, path) => withOwn(foldFile(state, path, false), { selected: path });

/** The reviewer followed the link of the thread <id> to <path>: Files changed shows, with the
 *  file open and the thread unfolded. */
export function followThread(state, id, path) {
  const shown = showComments(selectFile(showTab(state, "files"), path));
  const closed = state.server.threads.some((t) => t.id === id && t.status !== "open");
  return closed ? setOpen(shown, id, true) : shown;
}

export const isFolded = (state, path) => (Object.hasOwn(state.own.folds, path) // a file may be named "constructor"
  ? state.own.folds[path] : state.server?.viewed.includes(path) ?? false);

export const without = (all, key) => Object.fromEntries(Object.entries(all).filter(([k]) => k !== key));

/** Unfold, or fold again, what <id> names: a resolved or dismissed thread, or a note's details. */
export const setOpen = (state, id, open) => withOwn(state, { opened: open ? { ...state.own.opened, [id]: true } : without(state.own.opened, id) });
export const isOpen = (state, id) => Object.hasOwn(state.own.opened, id);

/** The API refused a change of the thread <id>'s status. */
export const threadRefused = (state, id, why) => withOwn(state, { errors: { ...state.own.errors, [id]: why } });
/** It took one: the thread folds, or not, as its new status says. */
export const threadTaken = (state, id) => setOpen(withOwn(state, { errors: without(state.own.errors, id) }), id, false);
