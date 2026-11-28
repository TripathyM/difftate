// What layout D shows of a thread, and of a comment box. DOM-free: draw_threads.js draws them.

import { boxOf, replyKey } from "./drafts.js";
import { markdown, spans } from "./markdown.js";
import { isOpen } from "./state.js";

// An open thread's state (GLOSSARY.md, Thread state); a state this page doesn't know shows as it is
const STATE = { held: "Pending", waiting: "Waiting", queued: "Queued", working: "Working", replied: "Replied", failed: "Failed" };
const STATUS = { resolved: "Resolved", dismissed: "Dismissed" };
const AUTHOR = { reviewer: "Reviewer", agent: "Coding agent", difftate: "difftate" };

/** "line 2", "lines 5–7", with "(old side)" for lines of the old version. */
export const linesText = (side, start, end) => `${start === end ? `line ${start}` : `lines ${start}–${end}`}${side === "old" ? " (old side)" : ""}`;

/** The box <key> of the page <state> (drafts.js): {key, text, tab: "write"|"preview", preview (the
 *  Markdown's blocks on that tab, else null), sending, error, send (what its button reads)}. */
export function boxModel(state, key, send) {
  const { text, tab, sending, error } = boxOf(state, key);
  return { key, text, tab, preview: tab === "preview" ? markdown(text) : null, sending, error, send };
}

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
  return {
    id: c.id, kind: "comment", time: c.time, agent: c.author === "agent",
    who: c.author === "reviewer" && c.by ? c.by : AUTHOR[c.author] ?? c.author, body: markdown(c.body),
  };
}

// What a card away from its lines says of them, with the code the thread was written on. Never the
// code there now
function written(t) {
  const a = t.anchor;
  if (!a?.code) return null;
  const why = t.outdated ? "" : t.inView === false ? "Its code isn't in this view. " : "Not among the lines shown. ";
  return { text: `${why}Written on ${linesText(a.side, a.startLine, a.endLine)}:`, code: a.code };
}

/** The card of <thread> (as the API gives it) in the page <state>. <placed>: it sits under its
 *  lines. {id, tone, labels: [{text, tone}], folds (it is resolved or dismissed), folded, gist,
 *  written: {text, code} | null, comments, reply: boxModel | null, actions: [{status, text}],
 *  error}. A comment is {id, kind: "comment", time, agent, who, body (Markdown blocks)}; a note
 *  {id, kind: "note", time, line (spans), more (blocks), open}. */
export function threadCard(thread, state, { placed }) {
  const open = thread.status === "open";
  return {
    id: thread.id, tone: labels(thread)[0].tone, labels: labels(thread),
    folds: !open, folded: !open && !isOpen(state, thread.id), gist: (thread.comments[0]?.body ?? "").split("\n")[0],
    written: placed ? null : written(thread),
    comments: thread.comments.map((c) => comment(state, c)),
    reply: open ? boxModel(state, replyKey(thread.id), "Reply") : null,
    actions: open ? [{ status: "resolved", text: "Resolve" }, { status: "dismissed", text: "Dismiss" }] : [{ status: "open", text: "Reopen" }],
    error: state.own.errors[thread.id] ?? "",
  };
}
