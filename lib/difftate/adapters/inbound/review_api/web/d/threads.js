// What layout D shows of a thread, and of a comment box. DOM-free: draw_threads.js draws them.

import { boxOf, replyKey } from "./drafts.js";
import { markdown, spans } from "./markdown.js";
import { isOpen } from "./state.js";
import { needsYou } from "./tabs.js";
import { viewLabel } from "./views.js";

// An open thread's state (GLOSSARY.md, Thread state); a state this page doesn't know shows as it is
const STATE = { held: "Pending", waiting: "Waiting", queued: "Queued", working: "Working", replied: "Replied", failed: "Failed" };
const STATUS = { resolved: "Resolved", dismissed: "Dismissed" };
const AUTHOR = { reviewer: "Reviewer", agent: "Coding agent", difftate: "difftate" };

/** What a box for a new thread says under it. */
export const heldHint = (state) => (state.server.mode.mode === "batched" ? "Held until you submit the review." : "");

/** "line 2", "lines 5–7", with "(old side)" for lines of the old version. */
export const linesText = (side, start, end) => `${start === end ? `line ${start}` : `lines ${start}–${end}`}${side === "old" ? " (old side)" : ""}`;

/** What a thread on <anchor> says of where it is. */
export const whereText = (anchor) => (anchor
  ? `${anchor.file}, ${linesText(anchor.side, anchor.startLine, anchor.endLine)}` : "On the whole changeset");

/** The box <key> of the page <state> (drafts.js): {key, kind: "draft"|"reply"|"general"|"summary", text,
 *  tab: "write"|"preview", preview (the Markdown's blocks on that tab, else null), sending, error,
 *  send (what its button reads, which ⌘/Ctrl+Enter presses), start (what its second button reads,
 *  which switches the review to batched and holds the comment, or null), cancels (it has a Cancel
 *  button)}. */
export function boxModel(state, key, kind) {
  const { text, tab, sending, error } = boxOf(state, key);
  const sends = kind === "summary" ? { send: "Submit review", start: null } : buttons(state);
  return { key, kind, text, tab, preview: tab === "preview" ? markdown(text) : null, sending, error, ...sends, cancels: kind === "draft" };
}

// A batched review holds every comment, so it has no way to send one now
const buttons = (state) => (state.server.mode.mode === "batched"
  ? { send: "Add review comment", start: null } : { send: "Comment", start: "Start a review" });

// A thread's labels: where it stands in the loop while open, else its status and who closed it
function labels(t) {
  const standing = t.status === "open"
    ? { text: STATE[t.state ?? "waiting"] ?? t.state, tone: t.state ?? "waiting" }
    : { text: `${STATUS[t.status] ?? t.status}${t.statusBy ? ` by ${t.statusBy}` : ""}`, tone: t.status };
  return [standing,
    ...(t.outdated ? [{ text: "Outdated", tone: "outdated" }] : []),
    ...(!t.outdated && t.inView === false ? [{ text: "Not in this view", tone: "elsewhere" }] : [])];
}

// A comment or a reply, or a note of difftate's: a quiet event, its first line shown
function comment(state, c) {
  if (c.author === "difftate") {
    const [first, ...rest] = c.body.trim().split("\n");
    return { id: c.id, kind: "note", time: c.time, line: spans(first), more: markdown(rest.join("\n")), open: isOpen(state, c.id) };
  }
  const named = c.author === "reviewer" && c.by; // the reviewer name hides the role: hovering says it
  return {
    id: c.id, kind: "comment", time: c.time, agent: c.author === "agent",
    who: named ? c.by : AUTHOR[c.author] ?? c.author, title: named ? AUTHOR.reviewer : "", body: markdown(c.body),
  };
}

// What a card away from its lines says of them, with the code the thread was written on (it may
// be a blank line's ""). Never the code there now
function written(t) {
  const a = t.anchor;
  if (typeof a?.code !== "string") return null;
  const why = t.outdated ? "" : t.inView === false ? "Its code isn't in this view. " : "Not among the lines shown. ";
  return { text: `${why}Written on ${linesText(a.side, a.startLine, a.endLine)}:`, code: a.code };
}

// The view that shows a thread whose lines aren't on screen: the one it was written in, when the
// page shows another. Never an outdated one's: no view has its code on its lines
function shownIn(t, state) {
  const view = t.anchor?.view ?? "";
  if (!t.anchor || t.outdated || view === (state.server.changeset.view ?? "")) return null;
  return { view, text: `Show it in ${viewLabel(view)}` };
}

/** The card of <thread> (as the API gives it) in the page <state>. <placed>: it sits under its
 *  lines. <where>: what its head says of where it is, when nothing around it does. {id, where,
 *  needsYou, tone, labels: [{text, tone}], folds (it is resolved or dismissed), folded, gist,
 *  written: {text, code} | null, elsewhere (the view that shows it, when it is away from its
 *  lines: {view, text}, else null), comments, reply: boxModel | null, actions: [{status, text}],
 *  error}. A comment is {id, kind: "comment", time, agent, who, title (the
 *  role behind a reviewer name, else ""), body (Markdown blocks)}; a note
 *  {id, kind: "note", time, line (spans), more (blocks), open}. */
export function threadCard(thread, state, { placed, where = null }) {
  const open = thread.status === "open";
  return {
    id: thread.id, where, needsYou: needsYou(thread), tone: labels(thread)[0].tone, labels: labels(thread),
    folds: !open, folded: !open && !isOpen(state, thread.id), gist: (thread.comments[0]?.body ?? "").split("\n")[0],
    written: placed ? null : written(thread),
    elsewhere: placed ? null : shownIn(thread, state),
    comments: thread.comments.map((c) => comment(state, c)),
    reply: open ? boxModel(state, replyKey(thread.id), "reply") : null,
    actions: open ? [{ status: "resolved", text: "Resolve" }, { status: "dismissed", text: "Dismiss" }] : [{ status: "open", text: "Reopen" }],
    error: state.own.errors[thread.id] ?? "",
  };
}
