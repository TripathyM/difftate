// The review path's drawing in the browser (GLOSSARY.md, Review path): the rows of the file list
// when the coding agent wrote a review path, and the stop shown above a file's diff. It turns
// what GET /api/review-path answers (its "path") into rows and blocks and draws nothing else,
// so a pane can replace it later without touching the rest. Pure: the page gives it its `el`.
// The rows and their text match lua/difftate/review_path.lua, the Neovim picker's.

const ranges = (rs) => (rs ?? []).map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(", ");
const linesText = (rs) => (ranges(rs) ? `lines ${ranges(rs)}` : "");
const inParens = (text) => (text ? ` (${text})` : "");

// "1 util.py ★", then in the list " · What does shout do?"
const stopHeading = (s) => `${s.number} ${s.file}${s.key ? " ★" : ""}`;
const stopLabel = (s) => `${stopHeading(s)}${s.questions?.[0] ? ` · ${s.questions[0].question}` : ""}`;

/** The rows of the file list for the review path <written>: the stops in reading order as a tree
 *  (side files first, then the stops under a stop, below it with ├─ and └─), then "Skipped" and
 *  "Not on the path" headings with their files. [] for no path. A file row: {text, file, ...}. */
export function rows(written) {
  if (!written) return [];
  const out = [];
  const addStop = (stop, prefix, connector) => {
    out.push({ kind: "stop", text: `${prefix}${connector}${stopLabel(stop)}`, file: stop.file, stop });
    const below = prefix + (connector === "├─ " ? "│  " : connector === "└─ " ? "   " : "");
    const items = [...(stop.side_files ?? []).map((side) => ({ side })), ...(stop.children ?? []).map((child) => ({ child }))];
    items.forEach((item, i) => {
      const last = i === items.length - 1 ? "└─ " : "├─ ";
      if (item.side) out.push({ kind: "side", text: `${below}${last}${item.side.file}`, file: item.side.file, side: item.side, stop });
      else addStop(item.child, below, last);
    });
  };
  for (const stop of written.stops ?? []) addStop(stop, "", "");
  const group = (heading, items, make) => {
    if (!items.length) return;
    out.push({ kind: "heading", text: heading });
    items.forEach((item, i) => {
      const row = make(item);
      out.push({ ...row, text: `${i === items.length - 1 ? "└─ " : "├─ "}${row.text}` });
    });
  };
  group("Skipped", written.skipped ?? [], (one) => ({ kind: "skipped", text: one.file + (one.reason ? ` — ${one.reason}` : ""), file: one.file, reason: one.reason }));
  group("Not on the path", written.not_on_the_path ?? [], (file) => ({ kind: "off", text: file, file }));
  return out;
}

/** The changeset's <files> ({path}) in the order of the file list <rows>: the files the rows
 *  name, then the others as they were. */
export function orderFiles(files, listed) {
  const at = new Map();
  for (const r of listed) if (r.file && !at.has(r.file)) at.set(r.file, at.size);
  const known = files.filter((f) => at.has(f.path)).sort((a, b) => at.get(a.path) - at.get(b.path));
  return [...known, ...files.filter((f) => !at.has(f.path))];
}

/** The block shown above <file>'s diff: its stop (questions and answers, specs, side files, the
 *  path sections it points to), or what the path says of a side file, a skipped file, a file off
 *  the path. null when the path knows nothing of the file. Built with <el>, in its own style
 *  (.review-path-stop), not a thread's. */
export function stopBlock(written, file, el) {
  const list = rows(written);
  const row = list.find((r) => r.file === file && r.kind !== "heading");
  if (!row) return null;
  const sections = new Map((written.sections ?? []).map((s) => [s.name, s]));
  const label = el("div", { class: "label", text: "Review path" });
  const part = (title, ...kids) => el("div", { class: "part" }, title ? el("h4", { text: title }) : null, ...kids);

  if (row.kind === "stop") {
    const s = row.stop;
    const caption = linesText(s.ranges);
    return el("div", { class: "review-path-stop" }, label,
      el("h4", { class: "head", text: stopHeading(s) }),
      caption ? el("div", { class: "lines", text: caption[0].toUpperCase() + caption.slice(1) }) : null,
      ...(s.questions ?? []).map((q) => part(q.question, el("div", { class: "answer", text: q.answer }))),
      s.specs?.length ? part(s.specs.length > 1 ? "Specs" : "Spec", ...s.specs.map((sp) => el("div", { text: sp.file + (sp.name ? ` "${sp.name}"` : "") }))) : null,
      s.side_files?.length ? part(s.side_files.length > 1 ? "Side files" : "Side file", ...s.side_files.map((sf) =>
        el("div", { text: `${sf.file}${inParens(linesText(sf.ranges))}${sf.text ? `: ${sf.text.replace(/\n/g, " ")}` : ""}` }))) : null,
      ...(s.see ?? []).filter((n) => sections.has(n)).map((n) => part(sections.get(n).name, el("div", { class: "answer", text: sections.get(n).text }))));
  }
  if (row.kind === "side") {
    const caption = linesText(row.side.ranges);
    return el("div", { class: "review-path-stop" }, label,
      el("h4", { class: "head", text: `${row.side.file}${inParens(caption)}` }),
      el("div", { class: "lines", text: `Side file of ${row.stop.number} ${row.stop.file}` }),
      row.side.text ? el("div", { class: "answer", text: row.side.text }) : null);
  }
  if (row.kind === "skipped") {
    return el("div", { class: "review-path-stop" }, label, el("div", { class: "lines", text: `Skipped: ${row.reason || "no reason given"}` }));
  }
  return el("div", { class: "review-path-stop" }, label, el("div", { class: "lines", text: "Not on the review path: the coding agent named it nowhere." }));
}
