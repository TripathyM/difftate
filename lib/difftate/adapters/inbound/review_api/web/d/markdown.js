// The little Markdown layout D shows: paragraphs, fenced code, lists, `code` and **bold**. It
// gives data, never HTML, so whatever else was written stays text: comments and replies are
// untrusted (the viewer guide). DOM-free: draw_markdown.js draws it.

const FENCE = /^\s*(```|~~~)/;
const ITEM = /^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/;

/** The spans of <text>: {text}, {code} or {strong}. */
export function spans(text) {
  const out = [];
  let last = 0;
  const plain = (end) => { if (end > last) out.push({ text: text.slice(last, end) }); };
  for (const m of text.matchAll(/`([^`\n]+)`|\*\*([^*\n]+)\*\*/g)) {
    plain(m.index);
    out.push(m[1] !== undefined ? { code: m[1] } : { strong: m[2] });
    last = m.index + m[0].length;
  }
  plain(text.length);
  return out;
}

/** The blocks of <text>: {kind: "paragraph", spans}, {kind: "code", text} or {kind: "list",
 *  ordered, items (the spans of each)}. */
export function markdown(text) {
  const blocks = [];
  let open = null; // the paragraph or list the next line may go on
  const lines = (text ?? "").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = FENCE.exec(line)?.[1];
    if (fence) {
      const code = [];
      while (++i < lines.length && !lines[i].trim().startsWith(fence)) code.push(lines[i]);
      blocks.push({ kind: "code", text: code.join("\n") });
      open = null;
      continue;
    }
    if (!line.trim()) {
      open = null;
      continue;
    }
    const item = ITEM.exec(line);
    if (item) {
      const ordered = item[1] !== undefined;
      if (open?.kind !== "list" || open.ordered !== ordered) blocks.push((open = { kind: "list", ordered, items: [] }));
      open.items.push(item[2]);
    } else if (open?.kind === "list" && /^\s/.test(line)) {
      open.items[open.items.length - 1] += ` ${line.trim()}`;
    } else if (open?.kind === "paragraph") {
      open.lines.push(line);
    } else {
      blocks.push((open = { kind: "paragraph", lines: [line] }));
    }
  }
  return blocks.map((b) => (b.kind === "paragraph" ? { kind: b.kind, spans: spans(b.lines.join("\n")) }
    : b.kind === "list" ? { ...b, items: b.items.map(spans) } : b));
}
