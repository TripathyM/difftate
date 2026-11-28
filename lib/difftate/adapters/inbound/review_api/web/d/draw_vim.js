// Draws what the Vim keys show (vim.js): the notice about browser extensions, which-key, the line
// at the bottom, the picker and All keys. index.html has them all.

import { el, keptByKey, keptWhileSame, place, setText, showDialog } from "./dom.js";

const $ = (id) => document.getElementById(id);
const drawn = keptWhileSame();

function show(id, shown) {
  $(id).hidden = !shown;
}

function drawWhich(which) {
  show("which", which);
  if (!which) return;
  place($("which"), [drawn("which", which, () => el("section", {}, el("b", { text: which.title }),
    which.keys.map((k) => el("div", {}, el("kbd", { text: k.key }), el("span", { text: k.text })))))]);
}

function drawPicker(picker, on) {
  showDialog($("picker"), Boolean(picker));
  if (!picker) return;
  setText($("picker-title"), picker.title);
  if ($("picker-query").value !== picker.query) $("picker-query").value = picker.query;
  show("picker-none", !picker.items.length);
  const list = drawn("picker", picker.items, () => el("div", {}, picker.items.map((item) =>
    el("button", { type: "button", class: "menu-item", "aria-current": item.current ? "true" : false, onclick: () => on.pick(item.value) },
      el("span", { text: item.text }), el("span", { class: "muted", text: item.hint })))));
  place($("picker-items"), [list]);
  list.querySelector("[aria-current]")?.scrollIntoView({ block: "nearest" });
}

// A key's row keeps its input, so that what is typed there keeps its caret
const keyRow = keptByKey((name, on) => {
  const input = el("input", { spellcheck: "false", autocomplete: "off", oninput: () => on.setKey(name, input.value) });
  const text = el("span");
  const note = el("span", { class: "key-note" });
  const node = el("label", { class: "key-row" }, text, input, note);
  return {
    node,
    update(row) {
      setText(text, row.text);
      text.title = name;
      if (input.value !== row.key) input.value = row.key;
      setText(note, row.note);
      note.hidden = !row.note;
    },
  };
});

const section = keptByKey((title) => {
  const rows = el("div");
  const node = el("section", {}, el("h2", { text: title }), rows);
  return { node, update: (nodes) => place(rows, nodes) };
});

function drawHelp(help, on) {
  if (help) {
    setText($("keys-extension"), help.extension);
    place($("keys-groups"), [
      ...help.groups.map((g) => section(g.title, g.rows.map((r) => keyRow(r.name, r, on)))),
      section("In a comment box (fixed)", [drawn("fixed", help.fixed, () => el("div", {}, help.fixed.map(([key, text]) =>
        el("div", { class: "key-row" }, el("span", { text }), el("kbd", { text: key })))))]),
    ]);
  }
  showDialog($("keys-help"), Boolean(help));
}

/** The Vim keys' model, drawn. on: {pick(value), setKey(action, key)} */
export function drawVim({ notice, which, line, picker, help }, on) {
  show("vim-notice", notice);
  setText($("vim-notice-text"), notice);
  show("vim-line", line);
  setText($("vim-line"), line);
  drawWhich(which);
  drawPicker(picker, on);
  drawHelp(help, on);
}
