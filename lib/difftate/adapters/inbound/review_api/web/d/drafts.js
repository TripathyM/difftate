// What the reviewer writes in layout D and hasn't sent: the comment boxes of the page state
// (own.boxes): a draft, a thread's reply box, the box for a general thread, or the summary of
// Submit review. A draft is a box
// for a new thread on lines, kept per anchor (GLOSSARY.md: the file, the
// side, the line range and the code on those lines) in its review, so each is posted on its own
// lines. Here too: picking those lines, by
// dragging over line numbers or with Shift-click. DOM-free: each function gives a new state.

import { parseDiff } from "../diff.js";
import { codeOn, diffRows, linesShown } from "./diff_rows.js";
import { openSubmit, showComments, withOwn, without } from "./state.js";

const EMPTY = { text: "", tab: "write", sending: false, error: "" };

/** The key of the reply box of the thread <id>. */
export const replyKey = (id) => `reply:${id}`;
export const repliesTo = (key) => key.slice("reply:".length);
/** The key of the box for a general thread of <review>: one for each review, so that what was
 *  typed for one branch is never posted on another's. */
export const generalKey = (review) => `general:${review}`;
/** The review whose general thread the box <key> is for, or null when it is another box. */
export const generalReview = (key) => (key.startsWith("general:") ? key.slice("general:".length) : null);

/** The key of the Submit review panel's summary box for <review>. */
export const summaryKey = (review) => `summary:${review}`;
/** Whether the box <key> is a summary's. */
export const isSummary = (key) => key.startsWith("summary:");

export const boxOf = (state, key) => (Object.hasOwn(state.own.boxes, key) ? state.own.boxes[key] : EMPTY);
const withBox = (state, key, changes) => withOwn(state, { boxes: { ...state.own.boxes, [key]: { ...boxOf(state, key), ...changes } } });
export const dropBox = (state, key) => withOwn(state, { boxes: without(state.own.boxes, key) });
/** The reviewer cancelled the draft <key>. One being sent stays: its call may fail, or has gone. */
export const cancelDraft = (state, key) => (boxOf(state, key).sending ? state : dropBox(state, key));
/** The reviewer closed the draft <key>, keeping its text: it is out of sight until they comment
 *  on its lines again. One with nothing written goes. */
export function closeDraft(state, key) {
  return boxOf(state, key).text.trim() ? withBox(state, key, { closed: true }) : cancelDraft(state, key);
}

/** The reviewer pressed Escape in the box <key>: in the summary, the Submit review panel closes;
 *  else a draft with nothing written goes. Escape never throws text away. */
export function escapeBox(state, key) {
  if (isSummary(key)) return openSubmit(state, false);
  return boxOf(state, key).anchor && !boxOf(state, key).text.trim() ? cancelDraft(state, key) : state;
}

/** The drafts of the review shown, each with its key: {key, text, tab, sending, error, anchor:
 *  {review, path, side, start, end, from (the line the pick started on), code, version, view},
 *  closed (once the reviewer closed it)}.
 *  Another review's stay, for when its branch is checked out again. */
export const draftsOf = (state) => Object.entries(state.own.boxes)
  .filter(([, box]) => box.anchor && box.anchor.review === state.server.review.id)
  .map(([key, box]) => ({ key, ...box }));

// The rows the diff shows of <path>: a file that changed its type has two parts
const rowsOf = (state, path) => parseDiff(state.server.changeset.diff).filter((f) => f.path === path).flatMap(diffRows);

// The line nearest <to> that a range from <from> can end on: the diff shows every line between
function reach(rows, side, from, to) {
  const shown = linesShown(rows, side);
  const step = to < from ? -1 : 1;
  let end = from;
  while (end !== to && shown.has(end + step)) end += step;
  return end;
}

/** The reviewer pressed on the line number <spot> ({path, side, line}). <extend> (Shift): the
 *  draft picked last now runs from where its pick started to here, if the diff shows every line
 *  between; else a new pick starts here. */
export function dragStart(state, spot, { extend = false } = {}) {
  const last = draftsOf(state).find((d) => d.key === state.own.active);
  const { path, side, line } = spot;
  if (extend && last && !last.sending && last.anchor.path === path && last.anchor.side === side
    && reach(rowsOf(state, path), side, last.anchor.from, line) === line) {
    return withOwn(state, { drag: { path, side, from: last.anchor.from, to: line, resize: last.key } });
  }
  return withOwn(state, { drag: { path, side, from: line, to: line } });
}

/** The reviewer dragged on to the line number <spot>: the pick ends there, or as near as the
 *  lines of its side go without a gap. A line of another file or side changes nothing. */
export function dragOver(state, spot) {
  const { drag } = state.own;
  if (!drag || drag.path !== spot.path || drag.side !== spot.side || drag.to === spot.line) return state;
  const to = reach(rowsOf(state, drag.path), drag.side, drag.from, spot.line);
  return to === drag.to ? state : withOwn(state, { drag: { ...drag, to } });
}

/** The reviewer let go: the lines picked get their draft, or the one they had. Drafts with no
 *  text elsewhere are dropped. */
export function dragEnd(state) {
  const { drag } = state.own;
  if (!drag) return state;
  const done = withOwn(state, { drag: null });
  const { path, side, from, resize } = drag;
  const [start, end] = [Math.min(from, drag.to), Math.max(from, drag.to)];
  const code = codeOn(rowsOf(state, path), side, start, end);
  if (code === null) return done; // the diff changed under the pick
  const { id: review } = state.server.review;
  const { view = "", versions } = state.server.changeset;
  const key = JSON.stringify([review, path, side, start, end, code]);
  const anchor = { review, path, side, start, end, from, code, version: versions?.[path]?.[side] ?? null, view };
  // A range made longer or shorter takes its text along, unless the new range has its own draft
  const moved = resize && !Object.hasOwn(done.own.boxes, key);
  const text = boxOf(done, moved ? resize : key).text;
  let next = moved ? dropBox(done, resize) : done;
  for (const d of draftsOf(next)) if (d.key !== key && !d.text.trim()) next = cancelDraft(next, d.key);
  // Comments hidden in the diff come back: sent, this one would go out of sight
  return showComments(withOwn(withBox(next, key, { anchor, text, tab: "write", closed: false }), { active: key }));
}

/** The reviewer typed in the box <key>: a draft's, a thread's reply box (replyKey), or the
 *  general thread's (generalKey). */
export const typeIn = (state, key, text) => withBox(state, key, { text, error: "" });
export const showBoxTab = (state, key, tab) => withBox(state, key, { tab });
export const boxSending = (state, key) => withBox(state, key, { sending: true, error: "" });
export const boxFailed = (state, key, error) => withBox(state, key, { sending: false, error });
