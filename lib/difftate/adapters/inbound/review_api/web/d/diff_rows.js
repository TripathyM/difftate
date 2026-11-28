// Layout D's diff: the rows of one file, unified. DOM-free: draw_files.js draws them.

/** The rows of <file> (diff.js, parseDiff): for each hunk {kind: "hunk", text}, then its lines
 *  {kind: "line", type: "context"|"add"|"delete", old, new (the line's number on each side, or
 *  null), text}. A binary file, or one with no changed lines, has one {kind: "note", text}. */
export function diffRows(file) {
  if (file.isBinary || !file.hunks.length) return [{ kind: "note", text: file.isBinary ? "Binary file" : "No changes to its lines" }];
  return file.hunks.flatMap((hunk) => [
    { kind: "hunk", text: hunk.header },
    ...hunk.lines.map((l) => ({ kind: "line", type: l.type, old: l.oldLineNumber, new: l.newLineNumber, text: l.content })),
  ]);
}
