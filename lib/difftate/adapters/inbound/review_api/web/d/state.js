// Layout D's page state. server: the last good answers of a poll. own: what is the reviewer's,
// which a poll keeps, so that a poll never throws it away. DOM-free: each function gives a new
// state.

// problem: why the last poll failed; refused: why the last change was refused ("" for neither)
export const initialState = () => ({ server: null, problem: "", refused: "", own: { tab: "files", folds: {}, selected: null, filter: "", boxes: {}, active: null, drag: null, opened: {}, errors: {} } });

export const withOwn = (state, changes) => ({ ...state, own: { ...state.own, ...changes } });

// A fold the reviewer chose holds until the file's viewed mark changes: then the file follows the
// mark again (folded when viewed), whoever changed it
function foldsAfter(folds, before, now) {
  return Object.fromEntries(Object.entries(folds).filter(([path]) => before.includes(path) === now.includes(path)));
}

/** The state with a poll's <answers> (poll.js): <state> itself when they say nothing new. */
export function polled(state, answers) {
  if (!state.problem && JSON.stringify(answers) === JSON.stringify(state.server)) return state;
  const next = { ...state, server: answers, problem: "" };
  // Another review (a checkout): its files are others, so what was folded, selected or being
  // picked is gone. Drafts stay: each names its review
  if (state.server && state.server.review.id !== answers.review.id) {
    return withOwn({ ...next, refused: "" }, { folds: {}, selected: null, active: null, drag: null });
  }
  return withOwn(next, { folds: foldsAfter(state.own.folds, state.server?.viewed ?? [], answers.viewed) });
}

/** A poll failed: the last good answers stay, with <problem> saying why. */
export const pollFailed = (state, problem) => (problem === state.problem ? state : { ...state, problem });

/** The state once the API answered a change of <path>'s viewed mark with the viewed <files>. */
export const viewedAnswered = (state, files) => polled(state, { ...state.server, viewed: files });

export const refused = (state, why) => (why === state.refused ? state : { ...state, refused: why });

export const showTab = (state, tab) => withOwn(state, { tab });
export const filterFiles = (state, filter) => withOwn(state, { filter });
export const foldFile = (state, path, folded) => withOwn(state, { folds: { ...state.own.folds, [path]: folded } });

/** The reviewer picked <path> in the file tree: it is selected, and open to read. */
export const selectFile = (state, path) => withOwn(foldFile(state, path, false), { selected: path });

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
