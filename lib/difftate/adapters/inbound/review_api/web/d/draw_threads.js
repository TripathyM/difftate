// Draws thread cards and comment boxes (threads.js, files_changed.js, conversation.js). Each keeps its node, and
// changes only the parts that differ: a comment box's textarea stays on the page through a poll,
// so what is typed there keeps its caret, its undo history and an input method's half-typed text.

import { drawMarkdown, drawSpans } from "./draw_markdown.js";
import { el, keptByKey, keptWhileSame, place, setText } from "./dom.js";

const when = (time) => {
  const at = new Date(time);
  return Number.isNaN(at.getTime()) ? "" : at.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
};

const codeShown = ({ text, code }) => el("div", { class: "written" }, el("p", { class: "muted", text }), el("pre", { class: "code-block", text: code }));

// on: {type(key, text), boxTab(key, tab), send(key), startReview(key), cancel(key), escape(key), setStatus(id,
// status), setOpen(id, open), follow(id, target)}
function makeBox(key, on) {
  const area = el("textarea", {
    "data-focus": `box:${key}`, rows: 3, placeholder: "Write to the coding agent…",
    oninput: () => on.type(key, area.value),
    onkeydown: (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); on.send(key); }
      else if (e.key === "Escape" && !e.isComposing) { area.blur(); on.escape(key); }
    },
  });
  const tab = (id, text) => el("button", { type: "button", role: "tab", "data-focus": `tab:${id}:${key}`, text, onclick: () => on.boxTab(key, id) });
  const tabs = { write: tab("write", "Write"), preview: tab("preview", "Preview") };
  const title = el("div", { class: "box-title" });
  const was = el("div");
  const preview = el("div", { class: "preview markdown" });
  const error = el("p", { class: "box-error", role: "alert" });
  const hint = el("span", { class: "muted hint" });
  const cancel = el("button", { type: "button", class: "btn", "data-focus": `cancel:${key}`, text: "Cancel", onclick: () => on.cancel(key) });
  const send = el("button", { type: "button", class: "btn primary", "data-focus": `send:${key}`, title: "⌘/Ctrl+Enter", onclick: () => on.send(key) });
  const start = el("button", { type: "button", class: "btn", "data-focus": `start:${key}`, title: "Switch this review to batched: comments are held until you submit", onclick: () => on.startReview(key) });
  const node = el("div", {}, title, was, el("div", { class: "box-tabs", role: "tablist" }, tabs.write, tabs.preview),
    area, preview, error, el("div", { class: "box-foot" }, hint, cancel, send, start));
  const wasShown = keptWhileSame();
  const previewShown = keptWhileSame();
  return {
    node,
    update(model) {
      const reply = model.kind === "reply";
      node.className = `box${reply ? " reply" : ""}${model.tab === "write" ? " writing" : ""}`;
      setText(title, model.title ?? "");
      title.hidden = reply;
      place(was, model.was ? [wasShown("was", model.was, codeShown)] : []);
      for (const [id, button] of Object.entries(tabs)) button.setAttribute("aria-selected", String(id === model.tab));
      area.setAttribute("aria-label", model.title ?? "Reply");
      if (area.value !== model.text) area.value = model.text;
      area.readOnly = model.sending;
      area.hidden = model.tab !== "write";
      preview.hidden = model.tab !== "preview";
      if (model.preview) {
        place(preview, [previewShown("preview", model.preview, (blocks) =>
          el("div", {}, blocks.length ? drawMarkdown(blocks) : el("p", { class: "muted", text: "Nothing to preview" })))]);
      }
      setText(error, model.error);
      error.hidden = !model.error;
      setText(hint, model.hint ?? "");
      cancel.hidden = !model.cancels;
      cancel.disabled = model.sending;
      setText(send, model.sending ? "Sending…" : model.send);
      send.disabled = model.sending;
      start.hidden = !model.start;
      setText(start, model.start ?? "");
      start.disabled = model.sending;
    },
  };
}

function drawComment(c, on) {
  if (c.kind === "note") {
    return el("div", { class: "note-event" },
      el("div", { class: "note-line" }, el("span", { class: "note-text" }, drawSpans(c.line)),
        c.more.length ? el("button", { type: "button", class: "link", "data-focus": `note:${c.id}`, "aria-expanded": String(c.open), text: c.open ? "Hide details" : "Details", onclick: () => on.setOpen(c.id, !c.open) }) : null,
        el("span", { class: "muted time", text: when(c.time) })),
      c.open ? el("div", { class: "note-more markdown" }, drawMarkdown(c.more)) : null);
  }
  return el("div", { class: `comment${c.agent ? " from-agent" : ""}` },
    el("div", { class: "comment-head" }, el("b", { text: c.who }),
      el("span", { class: "muted time", text: when(c.time) })),
    el("div", { class: "markdown" }, drawMarkdown(c.body)));
}

const boxes = keptByKey(makeBox);
/** The node of the comment box <model>: the same one for its key every time. */
export const drawBox = (model, on) => boxes(model.key, model, on);

// What a card on the timeline says of where its thread is: a link, when Files changed has a place
// for it
function whereShown({ id, where }, on) {
  if (!where) return null;
  if (!where.target) return el("span", { class: "thread-where", text: where.text });
  return el("button", { type: "button", class: "link thread-where", "data-focus": `goto:${id}`, title: "Show in Files changed", text: where.text, onclick: () => on.follow(id, where.target) });
}

function makeThread(id, on) {
  const node = el("article", { id: `thread-${id}` });
  const head = el("div");
  const body = el("div", { class: "thread-body" });
  node.append(head, body);
  const parts = keptWhileSame();
  return {
    node,
    update(t) {
      node.className = `thread tone-${t.tone}${t.folded ? " folded" : ""}${t.needsYou ? " needs-you" : ""}`;
      place(head, [parts("head", [t.where, t.labels, t.folds, t.folded, t.gist], () => el("div", { class: "thread-head" },
        whereShown(t, on),
        t.labels.map((l) => el("span", { class: `label tone-${l.tone}`, text: l.text })),
        t.folded ? el("span", { class: "gist muted", text: t.gist }) : null,
        t.folds ? el("button", { type: "button", class: "link fold-thread", "data-focus": `thread:${t.id}`, "aria-expanded": String(!t.folded), text: t.folded ? "Show" : "Hide", onclick: () => on.setOpen(t.id, t.folded) }) : null))]);
      body.hidden = t.folded;
      place(body, [
        t.written ? parts("written", t.written, codeShown) : null,
        ...t.comments.map((c) => parts(`comment:${c.id}`, c, () => drawComment(c, on))),
        t.reply ? drawBox(t.reply, on) : null,
        parts("foot", [t.actions, t.error], () => el("div", { class: "thread-foot" },
          t.actions.map((a) => el("button", { type: "button", class: "btn", "data-focus": `status:${a.status}:${t.id}`, text: a.text, onclick: () => on.setStatus(t.id, a.status) })),
          t.error ? el("span", { class: "box-error", role: "alert", text: t.error }) : null)),
      ].filter(Boolean));
    },
  };
}

const threads = keptByKey(makeThread);
/** The node of the thread card <model>: the same one for its thread every time. */
export const drawThread = (model, on) => threads(model.id, model, on);
