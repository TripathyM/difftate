// A unified diff (`git diff`, as the review API's changeset gives it) as the files
// the tab shows: [{path, oldPath, newPath, status, isBinary, additions, deletions,
// hunks: [{header, oldStart, newStart, lines: [{type, content, oldLineNumber, newLineNumber}]}]}].
// status is added, deleted, renamed, copied or modified; a line's type is add, delete or context.
// No herdr imports, so it runs under plain node too, and in difftate's browser viewer
// (the watcher serves this file to it: lib/difftate/api.py).

// git quotes paths with unusual characters: "a/caf\303\251.txt"
function unquote(s) {
  if (!s.startsWith('"')) return s;
  const bytes = [];
  const esc = { n: 10, t: 9, r: 13, b: 8, f: 12, v: 11, a: 7, '"': 34, "\\": 92 };
  for (let i = 1; i < s.length - 1; i++) {
    const c = s[i];
    if (c !== "\\") { bytes.push(...new TextEncoder().encode(c)); continue; }
    const n = s[++i];
    if (/[0-7]/.test(n)) { bytes.push(parseInt(s.slice(i, i + 3), 8)); i += 2; }
    else bytes.push(esc[n] ?? n.charCodeAt(0));
  }
  return new TextDecoder().decode(new Uint8Array(bytes));
}

// A path from a ---/+++ line or a rename line: null for /dev/null
function pathOf(raw, prefix) {
  const s = unquote(raw.replace(/\t$/, ""));
  if (s === "/dev/null") return null;
  return prefix && s.startsWith(prefix) ? s.slice(prefix.length) : s;
}

// Both paths from "diff --git a/x b/x" (used when no ---/+++ lines follow: binary, mode-only, empty new file)
function gitPaths(rest) {
  if (rest.startsWith('"')) {
    const m = /^("(?:[^"\\]|\\.)*")\s+(.*)$/.exec(rest);
    if (m) return [pathOf(m[1], "a/"), pathOf(m[2], "b/")];
  }
  // Unquoted, same path on both sides: "a/<p> b/<p>"
  const half = (rest.length - 1) / 2;
  if (Number.isInteger(half) && rest.slice(2, half) === rest.slice(half + 3)) return [rest.slice(2, half), rest.slice(half + 3)];
  const m = /^a\/(.*) b\/(.*)$/.exec(rest);
  return m ? [m[1], m[2]] : [rest, rest];
}

export function parseDiff(text) {
  const files = [];
  let f = null, h = null, oldN = 0, newN = 0;
  for (const line of (text ?? "").split("\n")) {
    if (line.startsWith("diff --git ")) {
      const [a, b] = gitPaths(line.slice(11));
      f = { oldPath: a, newPath: b, status: "modified", isBinary: false, additions: 0, deletions: 0, hunks: [] };
      files.push(f);
      h = null;
      continue;
    }
    if (!f) continue;
    if (h) {
      const c = line[0];
      if (c === "+" && newN > 0) { h.lines.push({ type: "add", content: line.slice(1), oldLineNumber: null, newLineNumber: h.newNext++ }); newN--; f.additions++; continue; }
      if (c === "-" && oldN > 0) { h.lines.push({ type: "delete", content: line.slice(1), oldLineNumber: h.oldNext++, newLineNumber: null }); oldN--; f.deletions++; continue; }
      if ((c === " " || line === "") && (oldN > 0 || newN > 0)) {
        h.lines.push({ type: "context", content: line.slice(1), oldLineNumber: h.oldNext++, newLineNumber: h.newNext++ });
        oldN--; newN--; continue;
      }
      if (c === "\\") continue; // \ No newline at end of file
    }
    const hm = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(line);
    if (hm) {
      const oldStart = +hm[1], newStart = +hm[3];
      oldN = hm[2] === undefined ? 1 : +hm[2];
      newN = hm[4] === undefined ? 1 : +hm[4];
      h = { header: line, oldStart, newStart, lines: [], oldNext: oldStart, newNext: newStart };
      f.hunks.push(h);
      continue;
    }
    h = null;
    if (line.startsWith("new file mode")) f.status = "added";
    else if (line.startsWith("deleted file mode")) f.status = "deleted";
    else if (line.startsWith("rename from ")) { f.status = "renamed"; f.oldPath = pathOf(line.slice(12)); }
    else if (line.startsWith("rename to ")) f.newPath = pathOf(line.slice(10));
    else if (line.startsWith("copy from ")) { f.status = "copied"; f.oldPath = pathOf(line.slice(10)); }
    else if (line.startsWith("copy to ")) f.newPath = pathOf(line.slice(8));
    else if (line.startsWith("Binary files ") || line === "GIT binary patch") f.isBinary = true;
    else if (line.startsWith("--- ")) { const p = pathOf(line.slice(4), "a/"); if (p) f.oldPath = p; }
    else if (line.startsWith("+++ ")) { const p = pathOf(line.slice(4), "b/"); if (p) f.newPath = p; }
  }
  for (const x of files) {
    x.path = x.status === "deleted" ? x.oldPath : x.newPath;
    for (const hk of x.hunks) { delete hk.oldNext; delete hk.newNext; }
  }
  return files;
}
