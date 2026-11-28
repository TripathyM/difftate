// Draws the blocks and spans of markdown.js. Everything written is set as text, never as HTML.

import { el } from "./dom.js";

export const drawSpans = (spans) => spans.map((s) => (s.code !== undefined ? el("code", { text: s.code })
  : s.strong !== undefined ? el("strong", { text: s.strong }) : s.text));

export const drawMarkdown = (blocks) => blocks.map((b) => {
  if (b.kind === "code") return el("pre", { class: "code-block", text: b.text });
  if (b.kind === "list") return el(b.ordered ? "ol" : "ul", {}, b.items.map((spans) => el("li", {}, drawSpans(spans))));
  return el("p", {}, drawSpans(b.spans));
});
