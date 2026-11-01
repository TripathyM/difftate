// Insert mode and small vim edits for the full-file view, mixed into the Review view.
// Edits change `raw` (the line as on disk, tabs kept); `text` is what's drawn (tabs expanded).
// Saving writes the file only if it still matches what was loaded, so an agent's edit
// made in the meantime is never overwritten silently.

import { exec, readTextFile, writeTextFile } from "herdr";

// Prints the real path (symlinks resolved) and permission bits, so a save keeps both.
const STAT = 'r=$(realpath "$1" 2>/dev/null || printf "%s" "$1"); m=$(stat -f %Lp "$r" 2>/dev/null || stat -c %a "$r" 2>/dev/null); printf "%s\\n%s" "$r" "$m"';
const MODE = 'stat -f %Lp "$1" 2>/dev/null || stat -c %a "$1"';

export const Editing = {
  editable() {
    return this.view?.mode === "file" && this.loaded?.path === this.view.path;
  },

  // Edits in progress that a reload from disk would throw away.
  busyEditing() {
    return this.mode === "insert" || this.dirty;
  },

  bufferText() {
    return this.rows.map((r) => r.raw ?? "").join("\n") + (this.loaded?.eol ? "\n" : "");
  },

  updateDirty() {
    this.dirty = this.editable() && this.bufferText() !== this.loaded.text;
  },

  // Runs fn in the editable full-file view. From the diff, switches there at the cursor's line first;
  // keys typed during the switch are replayed after it.
  withEditable(cx, fn) {
    if (this.editable()) { fn(cx); return; }
    const r = this.rows[this.cur.row];
    if (!this.view || !r || r.new == null || r.kind === "del" || r.kind === "hunk" || r.kind === "meta") {
      this.msg = r?.kind === "del" ? "Deleted lines can't be edited (they're not in the file any more)" : "Nothing to edit here";
      return;
    }
    const line = r.new, col = this.cur.col, path = this.view.path;
    this.switching = true;
    this.keyQueue = [];
    cx.spawn(async (cx) => {
      try {
        await this.openFile(path, "file", { line, col }, false);
        if (this.editable()) fn(cx);
        else this.msg = "This file can't be edited here (binary, deleted, or over 1 MiB)";
      } finally {
        this.switching = false;
        for (const e of this.keyQueue.splice(0)) this.handleKey(e, cx);
        cx.notify();
      }
    });
  },

  // ---------- columns: display (tabs expanded) <-> raw index ----------

  tw() { return this.opts.tab_width; },
  rawIdx(raw, col) {
    let w = 0;
    for (let i = 0; i < raw.length; i++) {
      const c = raw[i] === "\t" ? this.tw() : 1;
      if (w + c > col) return i;
      w += c;
    }
    return raw.length;
  },
  dispCol(raw, idx) {
    let w = 0;
    for (let i = 0; i < idx && i < raw.length; i++) w += raw[i] === "\t" ? this.tw() : 1;
    return w;
  },
  curIdx() {
    return this.rawIdx(this.rows[this.cur.row]?.raw ?? "", this.cur.col);
  },
  firstNonBlank(raw) {
    const i = raw.search(/\S/);
    return this.dispCol(raw, i < 0 ? 0 : i);
  },

  // ---------- buffer changes ----------

  setRaw(i, raw) {
    const r = this.rows[i];
    r.raw = raw;
    r.text = raw.replace(/\t/g, " ".repeat(this.tw()));
    r.edited = true;
    this.invalidate(i);
    this.dirty = true;
  },

  // Re-highlight from the line before i (block comments carry over lines).
  invalidate(i) {
    const k = Math.max(0, i - 1);
    if (k < this.hlUpTo) { this.hlUpTo = k; this.hlState = this.rows[k]?.hlIn ?? false; }
  },

  spliceRows(at, remove, raws) {
    const tw = this.tw();
    const made = raws.map((raw) => ({ kind: "ctx", old: null, new: 0, raw, text: raw.replace(/\t/g, " ".repeat(tw)), edited: true, delBelow: false }));
    this.rows.splice(at, remove, ...made);
    if (!this.rows.length) this.rows.push({ kind: "ctx", old: null, new: 1, raw: "", text: "", edited: true, delBelow: false });
    this.rows.forEach((r, i) => { r.new = i + 1; });
    this.indexRows();
    this.invalidate(at);
    this.rebuildItems();
    this.dirty = true;
  },

  // ---------- undo: one step per normal-mode command or per insert session ----------

  snapshot() {
    return { rows: this.rows.map((r) => ({ ...r, spans: null })), cur: { ...this.cur } };
  },
  beginChange() {
    if (this.groupOpen) return;
    this.undoStack.push(this.snapshot());
    if (this.undoStack.length > 200) this.undoStack.shift();
    this.redoStack = [];
    this.groupOpen = true;
  },
  endChange() {
    this.groupOpen = false;
    this.updateDirty();
  },
  restore(s) {
    this.rows = s.rows.map((r) => ({ ...r }));
    this.indexRows();
    this.hlUpTo = 0;
    this.hlState = false;
    this.cur = { ...s.cur };
    this.clampCol();
    this.rebuildItems();
    this.updateDirty();
    this.reveal();
  },
  undo() {
    if (!this.undoStack.length) { this.msg = "Already at oldest change"; return; }
    this.redoStack.push(this.snapshot());
    this.restore(this.undoStack.pop());
    this.msg = this.dirty ? "Undone · unsaved changes" : "Undone · matches the file on disk";
  },
  redo() {
    if (!this.redoStack.length) { this.msg = "Already at newest change"; return; }
    this.undoStack.push(this.snapshot());
    this.restore(this.redoStack.pop());
    this.msg = "Redone";
  },

  // ---------- insert mode ----------

  enterInsert(how) {
    const raw = this.rows[this.cur.row]?.raw ?? "";
    const len = this.dispCol(raw, raw.length);
    if (how === "a" && raw.length) this.cur.col = this.dispCol(raw, Math.min(raw.length, this.curIdx() + 1));
    else if (how === "A") this.cur.col = len;
    else if (how === "I") this.cur.col = this.firstNonBlank(raw);
    else this.cur.col = this.dispCol(raw, this.curIdx());
    this.mode = "insert";
    this.groupOpen = false;
    this.msg = "-- INSERT --   Esc stops · Ctrl-S / Cmd-S / :w saves";
  },

  leaveInsert(cx) {
    this.mode = "normal";
    this.endChange();
    this.cur.col = Math.max(0, this.cur.col - 1);
    this.clampCol();
    this.wantCol = this.cur.col;
    this.msg = this.dirty ? "Unsaved changes · :w or Ctrl-S saves · u undoes" : "";
    if (this.needsReopen && !this.dirty) {
      this.needsReopen = false;
      cx.spawn(async (cx) => { await this.reopen(); cx.notify(); });
    }
  },

  insertKey(e, tok, cx) {
    if (tok === "<esc>") { this.leaveInsert(cx); return true; }
    const act = tok ? this.maps.insert?.map.get(tok) : null;
    if (act) { this.perform(act, 1, cx); return true; }
    switch (tok) {
      case "<cr>": this.newline(); return true;
      case "<bs>": this.backspace(); return true;
      case "<del>": this.deleteForward(); return true;
      case "<tab>": this.insertText(this.indentUnit()); return true;
      case "<left>": this.stepCol(-1); return true;
      case "<right>": this.stepCol(1); return true;
      case "<up>": this.moveRow(-1); return true;
      case "<down>": this.moveRow(1); return true;
      case "<home>": this.cur.col = 0; return true;
      case "<end>": { const raw = this.rows[this.cur.row]?.raw ?? ""; this.cur.col = this.dispCol(raw, raw.length); return true; }
    }
    const m = e.modifiers ?? {};
    const ch = e.key_char;
    if (!m.control && !m.platform && ch && !/[\u0000-\u001f\u007f]/.test(ch)) { this.insertText(ch); return true; }
    return Boolean(tok);
  },

  stepCol(d) {
    const raw = this.rows[this.cur.row]?.raw ?? "";
    const at = Math.max(0, Math.min(raw.length, this.curIdx() + d));
    this.cur.col = this.dispCol(raw, at);
    this.wantCol = this.cur.col;
  },

  insertText(s) {
    this.beginChange();
    const i = this.cur.row, raw = this.rows[i].raw ?? "", at = this.curIdx();
    const next = raw.slice(0, at) + s + raw.slice(at);
    this.setRaw(i, next);
    this.cur.col = this.dispCol(next, at + s.length);
    this.wantCol = this.cur.col;
  },

  newline() {
    this.beginChange();
    const i = this.cur.row, raw = this.rows[i].raw ?? "", at = this.curIdx();
    const before = raw.slice(0, at), after = raw.slice(at).replace(/^[ \t]+/, "");
    const indent = /^[ \t]*/.exec(before)[0];
    this.setRaw(i, before);
    this.spliceRows(i + 1, 0, [indent + after]);
    this.cur = { row: i + 1, col: this.dispCol(indent, indent.length) };
    this.wantCol = this.cur.col;
    this.reveal();
  },

  backspace() {
    const i = this.cur.row, raw = this.rows[i].raw ?? "", at = this.curIdx();
    if (at > 0) {
      this.beginChange();
      const next = raw.slice(0, at - 1) + raw.slice(at);
      this.setRaw(i, next);
      this.cur.col = this.dispCol(next, at - 1);
    } else if (i > 0) {
      this.beginChange();
      const prev = this.rows[i - 1].raw ?? "";
      this.setRaw(i - 1, prev + raw);
      this.spliceRows(i, 1, []);
      this.cur = { row: i - 1, col: this.dispCol(prev + raw, prev.length) };
      this.reveal();
    }
    this.wantCol = this.cur.col;
  },

  deleteForward() {
    const i = this.cur.row, raw = this.rows[i].raw ?? "", at = this.curIdx();
    if (at < raw.length) {
      this.beginChange();
      this.setRaw(i, raw.slice(0, at) + raw.slice(at + 1));
    } else if (i < this.rows.length - 1) {
      this.beginChange();
      this.setRaw(i, raw + (this.rows[i + 1].raw ?? ""));
      this.spliceRows(i + 1, 1, []);
    }
  },

  // The file's own indent: a tab, or the smallest run of leading spaces.
  indentUnit() {
    let tabs = 0, spaced = 0, min = Infinity;
    for (const r of this.rows.slice(0, 2000)) {
      const raw = r.raw ?? "";
      if (raw.startsWith("\t")) tabs++;
      const m = /^( +)\S/.exec(raw);
      if (m) { spaced++; min = Math.min(min, m[1].length); }
    }
    if (tabs > spaced) return "\t";
    return " ".repeat(min >= 2 && min <= 8 ? min : this.tw());
  },

  // ---------- normal-mode edits ----------

  openLine(below) {
    this.beginChange();
    const i = this.cur.row, indent = /^[ \t]*/.exec(this.rows[i].raw ?? "")[0];
    const at = below ? i + 1 : i;
    this.spliceRows(at, 0, [indent]);
    this.cur = { row: at, col: this.dispCol(indent, indent.length) };
    this.mode = "insert"; // the new line and what's typed on it undo together
    this.msg = "-- INSERT --   Esc stops · Ctrl-S / Cmd-S / :w saves";
    this.reveal();
  },

  deleteChar(n) {
    const i = this.cur.row, raw = this.rows[i].raw ?? "", at = this.curIdx();
    if (at >= raw.length) return;
    this.beginChange();
    this.setRaw(i, raw.slice(0, at) + raw.slice(at + n));
    this.clampCol();
    this.endChange();
  },

  // The line register mirrors the system clipboard (like vim's clipboard=unnamedplus):
  // yanks and deletes copy to it, and p / P put what it holds when something else
  // copied there since.
  setRegister(lines, cx) {
    this.register = lines;
    this.clip = lines.join("\n") + "\n";
    try { cx?.write_to_clipboard(this.clip); } catch {}
  },

  syncRegister(cx) {
    let text;
    try { text = cx?.read_from_clipboard(); } catch {}
    if (text == null || text === "" || text === this.clip) return;
    this.clip = text;
    this.register = text.replace(/\r\n?/g, "\n").replace(/\n$/, "").split("\n");
  },

  deleteLines(a, n, cx) {
    n = Math.max(1, Math.min(n, this.rows.length - a));
    this.beginChange();
    this.setRegister(this.rows.slice(a, a + n).map((r) => r.raw ?? r.text), cx);
    this.spliceRows(a, n, []);
    this.cur.row = Math.min(a, this.rows.length - 1);
    this.cur.col = this.firstNonBlank(this.rows[this.cur.row].raw ?? "");
    this.endChange();
    this.msg = `${n} line${n === 1 ? "" : "s"} deleted · p puts ${n === 1 ? "it" : "them"} back`;
    this.reveal();
  },

  yankLines(a, n, cx) {
    const rows = this.rows.slice(a, a + Math.max(1, n)).filter((r) => r.kind !== "hunk" && r.kind !== "meta");
    if (!rows.length) return;
    this.setRegister(rows.map((r) => r.raw ?? r.text), cx);
    this.msg = `${rows.length} line${rows.length === 1 ? "" : "s"} yanked (also in the clipboard)`;
  },

  put(below, n, cx) {
    this.syncRegister(cx);
    if (!this.register?.length) { this.msg = "Nothing to put: yy or dd first"; return; }
    this.beginChange();
    const lines = Array.from({ length: n }, () => this.register).flat();
    const at = below ? this.cur.row + 1 : this.cur.row;
    this.spliceRows(at, 0, lines);
    this.cur = { row: at, col: this.firstNonBlank(lines[0]) };
    this.endChange();
    this.reveal();
  },

  visualRange() {
    return [Math.min(this.anchor, this.cur.row), Math.max(this.anchor, this.cur.row)];
  },

  visualYank(cx) {
    const [a, b] = this.visualRange();
    this.mode = "normal";
    this.yankLines(a, b - a + 1, cx);
  },

  visualDelete(cx) {
    const [a, b] = this.visualRange();
    this.mode = "normal";
    if (this.editable()) { this.deleteLines(a, b - a + 1, cx); return; }
    // From the diff: delete the file lines the selection covers.
    const nums = this.rows.slice(a, b + 1).filter((r) => r.new != null && (r.kind === "add" || r.kind === "ctx")).map((r) => r.new);
    if (!nums.length) { this.msg = "Only deleted lines selected: nothing in the file to delete"; return; }
    const lo = Math.min(...nums), hi = Math.max(...nums);
    this.cur.row = this.rowOfNew.get(lo) ?? this.cur.row;
    this.withEditable(cx, (c) => this.deleteLines(lo - 1, hi - lo + 1, c));
  },

  // ---------- save, reload, : commands ----------

  save(force, cx) {
    if (this.mode === "insert") this.leaveInsert(cx);
    if (!this.editable()) { this.msg = "Nothing to save: edits happen in the full-file view (i starts one)"; return; }
    this.updateDirty();
    if (!this.dirty && !force) { this.msg = "No changes to save"; return; }
    const path = this.view.path, file = `${this.root}/${path}`, text = this.bufferText(), expected = this.loaded.text;
    this.msg = `Saving ${path}…`;
    cx.spawn(async (cx) => {
      try {
        const st = await exec("sh", ["-c", STAT, "sh", file]).catch(() => null);
        const [real, mode] = (st?.stdout ?? "").split("\n");
        const target = real?.trim() || file;
        const disk = await readTextFile(target).catch(() => null);
        if (!force && disk !== expected) {
          this.msg = `${path} changed on disk since you opened it (the agent may have edited it). :w! overwrites it, :e! reloads it and drops your edits.`;
          cx.notify();
          return;
        }
        await writeTextFile(target, text, disk);
        const m = mode?.trim();
        if (m) {
          const after = await exec("sh", ["-c", MODE, "sh", target]).catch(() => null);
          if (after && after.stdout.trim() !== m) await exec("chmod", [m, target]);
        }
        this.loaded = { ...this.loaded, text };
        for (const r of this.rows) r.edited = false;
        this.updateDirty();
        this.fileCache = null;
        this.msg = `"${path}" written · ${this.rows.length} lines · the diff updates in a moment`;
      } catch (e) {
        this.msg = `Save failed: ${e}`;
      }
      cx.notify();
    });
  },

  // :e! — reload from disk and drop unsaved edits.
  revert(cx) {
    if (!this.view) return;
    if (this.mode === "insert") { this.mode = "normal"; this.groupOpen = false; }
    this.dirty = false;
    const h = this.here();
    cx.spawn(async (cx) => {
      await this.openFile(h.path, h.mode, { line: h.line, col: h.col, row: h.row }, false);
      this.msg = "Reloaded from disk";
      cx.notify();
    });
  },

  runCommand(input, cx) {
    const c = input.trim();
    if (!c) return;
    if (/^\d+$/.test(c)) {
      const n = parseInt(c, 10);
      this.pushJump();
      const row = this.view?.mode === "file" ? n - 1 : this.rowNear(n);
      if (row >= 0) { this.setRow(row, false); this.reveal("center"); }
      return;
    }
    if (["w", "write", "wq", "x", "up", "update"].includes(c)) return this.save(false, cx);
    if (c === "w!" || c === "wq!" || c === "x!") return this.save(true, cx);
    if (c === "e!" || c === "edit!") return this.revert(cx);
    if (c === "e" || c === "edit") {
      if (this.dirty) { this.msg = "Unsaved changes: :w saves them, :e! drops them"; return; }
      return this.revert(cx);
    }
    this.msg = `Not a command: :${c}   (try :w  :w!  :e!  :42)`;
  },
};
