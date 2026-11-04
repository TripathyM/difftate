// difftate review: a code-editor-like diff view with vim keys, go to definition,
// fuzzy file open, and review threads read and written through the running watcher's
// review API (difftate / dtc / dto), so the watcher answers them as from any viewer.
//
// Open: mod.open difftate (it opens itself as a tab for the focused pane's repo), or
//   herdr-app do tab.new '{"name":"Review · repo","mod":"difftate","props":{"folder":"/path/to/repo"}}'
//   (difftate itself does this with DT_OPEN=herdr).
// Keys: keymap.json next to this file holds the defaults; ~/.config/difftate/keymap.json,
// if present, overrides them per key and survives updates. Any action also runs as
// `difftate.<action>`. Editing (insert mode, dd/yy/p, undo, :w) lives in edit.js.

import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, Scrollbar, v_virtual_list, VirtualListScrollHandle } from "gpui-base";
import { exec, readTextFile, theme, settings, props, run, closeOverlay, focused, panes, spaces, nextCommand, appHome, home } from "herdr";
import { findApi } from "./api.js";
import { tokenize, langOf } from "./syntax.js";
import { Editing } from "./edit.js";

const MOD = "difftate";
const SEP = "\u0001";
const LH = 16; // thread text line height
const EXPLORER_W = 270;
const SPECIAL = {
  escape: "<esc>", enter: "<cr>", tab: "<tab>", space: "<space>", backspace: "<bs>", delete: "<del>",
  up: "<up>", down: "<down>", left: "<left>", right: "<right>",
  pageup: "<pageup>", pagedown: "<pagedown>", home: "<home>", end: "<end>",
};
const STATE_LABEL = { waiting: "waiting for agent", queued: "queued", working: "agent working", replied: "agent replied", failed: "failed: no reply", resolved: "resolved", dismissed: "dismissed" };
// Where a thread stands: the API's thread state while open, else its status (resolved, dismissed).
const stateOf = (th) => (th.status === "open" ? th.state ?? "waiting" : th.status);
// How the tab names a view of the review
const viewLabel = (v) => (!v ? "all changes" : v === "HEAD" ? "uncommitted" : v === "staged" || v === "unstaged" ? v : `commits after ${v}`);

// ---------- keymap ----------

function canon(tok, leader) {
  if (/^<leader>$/i.test(tok)) return leader;
  const m = /^<(.+)>$/.exec(tok);
  if (!m) return tok;
  const c = /^[cC]-(.)$/.exec(m[1]);
  return c ? `<C-${c[1].toLowerCase()}>` : `<${m[1].toLowerCase()}>`;
}
const splitSeq = (seq, leader) => (seq.match(/<[^>]+>|./g) ?? []).map((t) => canon(t, leader));

function compile(table, leader) {
  const map = new Map(), prefixes = new Set();
  for (const [seq, action] of Object.entries(table ?? {})) {
    const toks = splitSeq(seq, leader);
    if (!toks.length) continue;
    map.set(toks.join(SEP), action);
    for (let i = 1; i < toks.length; i++) prefixes.add(toks.slice(0, i).join(SEP));
  }
  return { map, prefixes };
}

function tokenOf(e) {
  const m = e.modifiers ?? {};
  if (m.platform) return null; // cmd keys stay with the app
  if (m.control) return `<C-${String(e.key).toLowerCase()}>`;
  if (SPECIAL[e.key]) return SPECIAL[e.key];
  const ch = e.key_char;
  if (ch && ch.length === 1) return ch === " " ? "<space>" : ch;
  if (String(e.key).length === 1) return m.shift ? e.key.toUpperCase() : e.key;
  return null;
}

// ---------- helpers ----------

const detab = (s, n) => (s ?? "").replace(/\t/g, " ".repeat(n));
const isWord = (c) => /[\w$]/.test(c ?? "");
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function fuzzy(query, text) {
  if (!query) return 0;
  const q = query.toLowerCase(), s = text.toLowerCase();
  let score = 0, j = 0, run = 0;
  const base = s.lastIndexOf("/") + 1;
  for (let i = 0; i < s.length && j < q.length; i++) {
    if (s[i] === q[j]) {
      run++;
      score += 1 + run * 2 + (i === base ? 6 : 0) + (i > 0 && /[\/_\-. ]/.test(s[i - 1]) ? 3 : 0) + (i >= base ? 1 : 0);
      j++;
    } else run = 0;
  }
  return j === q.length ? score - s.length * 0.01 : null;
}

function wrap(text, cols) {
  const out = [];
  for (const para of String(text).split("\n")) {
    let s = para;
    if (!s) { out.push(""); continue; }
    while (s.length > cols) {
      let cut = s.lastIndexOf(" ", cols);
      if (cut < cols * 0.5) cut = cols;
      out.push(s.slice(0, cut));
      s = s.slice(cut).replace(/^ /, "");
    }
    out.push(s);
  }
  return out;
}

export default class Review extends View {
  init(_props, cx) {
    // Opened with mod.open: become a launcher that opens the real tab, then go.
    if (props()?.overlay) {
      this.launcher = true;
      const f = focused();
      const all = panes();
      const pane = f?.pane ? all.find((p) => p.pane === f.pane) : null;
      // A mod pane (another Review tab) has no folder: use a terminal in the same space.
      const space = spaces().find((s) => s.id === f?.space);
      const tabs = new Set((space?.tabs ?? []).map((t) => t.id));
      const sibling = all.find((p) => tabs.has(p.tab) && p.cwd && p.terminal);
      const folder = pane?.cwd || f?.cwd || sibling?.cwd || space?.folder || home();
      closeOverlay(props().overlay);
      // Same name the difftate watcher uses (DT_OPEN=herdr), so either one reuses the tab.
      const name = `Review · ${folder.replace(/\/+$/, "").split("/").pop()}`;
      const open = spaces().flatMap((s) => s.tabs).find((t) => t.name === name);
      if (open) run("tab.select", { id: open.id });
      else run("tab.new", { name, mod: MOD, props: { folder } });
      return;
    }
    this.folder = props()?.folder || focused()?.cwd || home();
    this.opts = { font_size: 12.5, char_width: 0.6, row_height: 20, tab_width: 4, sequence_timeout_ms: 800 };
    this.maps = { normal: compile({}, "<space>"), visual: compile({}, "<space>"), insert: compile({}, "<space>") };
    this.keymapError = null;
    // Editing state (edit.js): the file as loaded, undo history, the dd/yy register.
    this.loaded = null;
    this.dirty = false;
    this.undoStack = [];
    this.redoStack = [];
    this.groupOpen = false;
    this.register = null;
    this.switching = false;
    this.keyQueue = [];
    this.mode = "normal";
    this.pending = [];
    this.count = "";
    this.seqId = 0;
    this.cur = { row: 0, col: 0 };
    this.wantCol = 0;
    this.anchor = 0;
    this.rows = [];
    this.items = [];
    this.itemOfRow = [];
    this.files = [];
    this.threads = [];
    this.viewed = new Set(); // paths of the files marked viewed (the watcher clears a mark when the file's diff changes)
    this.reviewView = ""; // the review's view (all changes, commits, staged…); this.view is the file shown
    this.view = null;
    this.jumps = [];
    this.jumpIdx = 0;
    this.explorer = true;
    this.picker = null;
    this.prompt = null;
    this.search = "";
    this.msg = "Connecting…";
    this.size = { width: 1200, height: 800 };
    this.api = null;
    this.handle = cx.focus_handle();
    this.scroll = VirtualListScrollHandle.new();
    this.input = InputState.new({ placeholder: "" });
    this.input.on("submit", (_e, cx) => this.submitInput(cx));
    this.input.on("change", (_e, cx) => { if (this.picker) { this.filterPicker(); cx.notify(); } });
    cx.timer.after(150, () => this.handle.focus());

    cx.spawn(async (cx) => {
      await this.loadKeymap();
      await this.connect(cx);
      cx.notify();
    });
    cx.timer.every(2000, (cx) => this.poll(cx));
    cx.spawn(async (cx) => {
      for (;;) {
        const c = await nextCommand();
        this.perform(c, 1, cx);
        cx.notify();
      }
    });
  }

  // ---------- data ----------

  // Defaults from keymap.json here, then the person's own file on top, key by key.
  async loadKeymap() {
    const read = async (path) => {
      const raw = await readTextFile(path).catch(() => null);
      if (raw === null) return {};
      try { return JSON.parse(raw); } catch (e) { throw new Error(`${path}: ${e}`); }
    };
    try {
      const base = await read(`${appHome()}/mods/${MOD}/keymap.json`);
      const mine = await read(`${home()}/.config/difftate/keymap.json`);
      const km = {
        ...base,
        leader: mine.leader ?? base.leader,
        options: { ...base.options, ...mine.options },
        normal: { ...base.normal, ...mine.normal },
        visual: { ...base.visual, ...mine.visual },
        insert: { ...base.insert, ...mine.insert },
      };
      const leader = canon(km.leader ?? "<Space>", "<space>");
      this.opts = { ...this.opts, ...km.options };
      this.maps = { normal: compile(km.normal, leader), visual: compile(km.visual, leader), insert: compile(km.insert, leader) };
      this.keymap = km;
      this.leader = leader;
      this.keymapError = null;
    } catch (e) {
      this.keymapError = `Keymap not loaded: ${e.message ?? e}`;
    }
  }

  async git(args) {
    return exec("git", ["--no-optional-locks", ...args], { cwd: this.root ?? this.folder });
  }

  async connect(cx) {
    const top = await exec("git", ["rev-parse", "--show-toplevel"], { cwd: this.folder }).catch(() => null);
    if (!top || top.code !== 0) { this.msg = `${this.folder} is not a git repository`; return; }
    this.root = top.stdout.trim();
    this.repo = this.root.split("/").pop();
    await this.attach(cx);
    if (!this.view && this.files.length) await this.openFile(this.files[0].path, "diff", null, false);
  }

  async attach(cx) {
    const api = await findApi(this.root).catch(() => null);
    if (!api) {
      this.api = null;
      this.msg = "No difftate review running for this repo. Run difftate (or dto) here to comment.";
      return;
    }
    this.api = api;
    this.msg = "";
    await this.loadDiff();
    await this.loadThreads();
    await this.loadViewed();
  }

  async loadDiff() {
    this.applyChangeset(await this.api.changeset());
  }

  applyChangeset(c) {
    this.diffText = c.diff;
    this.base = c.base;
    this.commit = c.commit;
    this.files = c.files;
    if (c.view !== this.reviewView) this.threadSig = null; // threads sit elsewhere in another view
    this.reviewView = c.view;
  }

  async loadThreads() {
    if (!this.api) return;
    const list = await this.api.threads(this.reviewView).catch(() => null);
    if (!list) return;
    const sig = JSON.stringify(list.map((t) => [t.id, t.status, t.state, t.outdated, t.inView, t.startLine, t.endLine, t.comments.length, t.comments.at(-1)?.body]));
    if (sig === this.threadSig) return false;
    this.threadSig = sig;
    this.threads = list;
    this.rebuildItems();
    return true;
  }

  // True when the viewed files changed
  async loadViewed() {
    if (!this.api) return false;
    const viewed = await this.api.viewed().catch(() => null);
    if (!viewed || [...viewed].sort().join("\0") === [...this.viewed].sort().join("\0")) return false;
    this.viewed = viewed;
    return true;
  }

  toggleViewed(cx) {
    const path = this.view?.path;
    if (!this.api || !path || !this.fileOf(path)) { this.msg = "Open a changed file to mark it viewed"; return; }
    const viewed = !this.viewed.has(path);
    cx.spawn(async (cx) => {
      try {
        this.viewed = await this.api.setViewed(path, viewed);
        this.msg = viewed ? `Viewed ${path}` : `Not viewed: ${path}`;
      } catch (e) { this.msg = String(e.message ?? e); }
      cx.notify();
    });
  }

  poll(cx) {
    if (this.polling || !this.root) return;
    this.polling = true;
    cx.spawn(async (cx) => {
      try {
        if (!this.api) {
          await this.attach(cx);
          if (this.api && !this.view && this.files.length) await this.openFile(this.files[0].path, "diff", null, false);
          else if (this.api) this.rebuildItems();
          cx.notify();
          return;
        }
        let c;
        try { c = await this.api.changeset(); }
        catch (e) {
          // No watcher there (stopped, or a new one with another port and token): look again next time
          if (!e.status || e.status === 401) { this.api = null; this.msg = "difftate stopped. Run difftate again to keep commenting."; cx.notify(); return; }
          throw e;
        }
        if (c.diff !== this.diffText || c.view !== this.reviewView) {
          this.applyChangeset(c);
          // Never reload over edits in progress; catch up once they're saved or dropped.
          if (this.view) { if (this.busyEditing()) this.needsReopen = true; else await this.reopen(); }
          cx.notify();
        }
        if (await this.loadThreads()) cx.notify();
        if (await this.loadViewed()) cx.notify();
      } catch (e) {
        this.msg = String(e);
      } finally {
        this.polling = false;
      }
    });
  }

  fileOf(path) { return this.files.find((f) => f.path === path); }

  diffRows(f) {
    const tw = this.opts.tab_width;
    if (f.isBinary) return [{ kind: "meta", text: "Binary file" }];
    const rows = [];
    for (const h of f.hunks ?? []) {
      rows.push({ kind: "hunk", text: h.header });
      for (const l of h.lines) {
        rows.push({
          kind: l.type === "add" ? "add" : l.type === "delete" ? "del" : "ctx",
          old: l.oldLineNumber, new: l.newLineNumber, raw: l.content, text: detab(l.content, tw),
        });
      }
    }
    return rows.length ? rows : [{ kind: "meta", text: "No text changes" }];
  }

  async fileRows(path, f) {
    const text = await readTextFile(`${this.root}/${path}`).catch(() => null);
    if (text === null) return [{ kind: "meta", text: "Can't show this file (deleted, binary, or over 1 MiB)" }];
    if (text.includes("\0")) return [{ kind: "meta", text: "Binary file" }];
    const added = new Set(), delBelow = new Set();
    for (const h of f?.hunks ?? []) {
      let prevNew = h.newStart - 1;
      for (const l of h.lines) {
        if (l.type === "add") added.add(l.newLineNumber);
        if (l.type === "delete") delBelow.add(prevNew);
        if (l.newLineNumber != null) prevNew = l.newLineNumber;
      }
    }
    const tw = this.opts.tab_width;
    const lines = text.replace(/\n$/, "").split("\n");
    this.pendingLoaded = { path, text, eol: text.endsWith("\n") };
    return lines.map((s, i) => ({ kind: added.has(i + 1) ? "add" : "ctx", old: null, new: i + 1, raw: s, text: detab(s, tw), delBelow: delBelow.has(i + 1) || (i === 0 && delBelow.has(0)) }));
  }

  indexRows() {
    this.rowOfNew = new Map();
    this.rowOfOld = new Map();
    this.rows.forEach((r, i) => {
      if (r.new != null && r.kind !== "del") this.rowOfNew.set(r.new, i);
      if (r.old != null && r.kind !== "add") this.rowOfOld.set(r.old, i);
    });
  }

  // ---------- view ----------

  here() {
    const r = this.rows[this.cur.row];
    return { path: this.view?.path, mode: this.view?.mode, line: r?.new ?? r?.old ?? null, row: this.cur.row, col: this.cur.col };
  }

  pushJump() {
    if (!this.view) return;
    this.jumps = this.jumps.slice(0, this.jumpIdx);
    this.jumps.push(this.here());
    if (this.jumps.length > 100) this.jumps.shift();
    this.jumpIdx = this.jumps.length;
  }

  async openFile(path, mode, target, record = true) {
    const f = this.fileOf(path);
    if (!f) mode = "file";
    if (this.dirty && this.view && (path !== this.view.path || mode !== this.view.mode)) {
      this.msg = `Unsaved changes in ${this.view.path}: :w saves them, :e! drops them`;
      return false;
    }
    if (record) this.pushJump();
    this.pendingLoaded = null;
    const rows = mode === "diff" ? this.diffRows(f) : await this.fileRows(path, f);
    const before = this.loaded;
    if (mode === "file") this.loaded = this.pendingLoaded;
    // Undo history belongs to one file's content: drop it on another file, or when
    // something else (the agent) changed this one on disk.
    if (before?.path !== path || (mode === "file" && this.loaded && before.text !== this.loaded.text)) {
      this.undoStack = [];
      this.redoStack = [];
    }
    this.dirty = false;
    this.groupOpen = false;
    this.view = { path, mode };
    this.rows = rows;
    this.lang = langOf(path);
    this.hlUpTo = 0;
    this.hlState = false;
    this.indexRows();
    let row = -1;
    if (target?.line != null) row = this.rowNear(target.line, target.side);
    if (row < 0 && target?.row != null) row = Math.min(target.row, rows.length - 1);
    if (row < 0) row = Math.max(0, rows.findIndex((r) => r.kind === "add" || r.kind === "del"));
    this.cur = { row, col: target?.col ?? 0 };
    this.mode = "normal";
    this.clampCol();
    this.rebuildItems();
    this.reveal("center");
  }

  async reopen() {
    const h = this.here();
    const exists = this.fileOf(h.path) || h.mode === "file";
    if (!exists) { this.view = null; this.rows = []; this.rebuildItems(); if (this.files.length) await this.openFile(this.files[0].path, "diff", null, false); return; }
    await this.openFile(h.path, h.mode, { line: h.line, col: h.col, row: h.row }, false);
  }

  // The row showing a line, or the closest one after it.
  rowNear(line, side = "new") {
    const m = side === "old" ? this.rowOfOld : this.rowOfNew;
    if (m.has(line)) return m.get(line);
    let best = -1, bestD = Infinity;
    for (const [n, i] of m) { const d = Math.abs(n - line); if (d < bestD) { bestD = d; best = i; } }
    return best;
  }

  // The row a thread sits under, or -1. An outdated thread's code is no longer on its
  // lines, so it never sits next to them: it is listed below the code, with the code it was written on.
  anchorRow(th) {
    if (th.outdated || !th.inView) return -1;
    const m = th.side === "old" ? this.rowOfOld : this.rowOfNew;
    return m?.get(th.endLine) ?? -1;
  }

  threadsHere() {
    const p = this.view?.path;
    return this.threads.filter((t) => t.filePath && t.filePath === p);
  }

  // Code area metrics.
  cw() { return this.opts.font_size * this.opts.char_width; }
  rowH() { return this.opts.row_height; }
  codeW() { return Math.max(300, this.size.width - (this.explorer ? EXPLORER_W : 0)); }
  numW() { return Math.max(4, String(this.rows.length + 9999).length) * this.cw() + 10; }
  gutterW() { return 3 + (this.view?.mode === "diff" ? 2 : 1) * this.numW() + 16; }
  wrapCols() { return Math.max(30, Math.floor((this.codeW() - this.gutterW() - 60) / this.cw())); }

  layoutThread(th) {
    const cols = this.wrapCols();
    const state = stateOf(th);
    const range = th.startLine === th.endLine ? `${th.startLine}` : `${th.startLine}-${th.endLine}`;
    const lines = [{ k: "head", text: `${state === "resolved" || state === "dismissed" ? "○" : "●"} ${STATE_LABEL[state] ?? state}  ·  ${th.side === "old" ? "old " : ""}line ${range}${th.outdated ? "  ·  outdated" : ""}` }];
    if (th.outdated && th.code) {
      const code = th.code.replace(/\n$/, "").split("\n");
      lines.push({ k: "author", text: "code when written (it changed since)" });
      for (const l of code.slice(0, 8)) lines.push({ k: "code", text: detab(l, this.opts.tab_width).slice(0, cols) });
      if (code.length > 8) lines.push({ k: "dim", text: `… ${code.length - 8} more lines` });
    }
    if (state === "resolved" || state === "dismissed") {
      const first = (th.comments[0]?.body ?? "").split("\n")[0];
      lines.push({ k: "dim", text: first.slice(0, cols) });
      lines.push({ k: "hint", text: "<leader>cR reopen" });
    } else {
      for (const c of th.comments) {
        let body = c.body ?? "", who = "you", k = "body";
        if (c.author === "agent") { who = "agent"; k = "agent"; }
        else if (c.author === "difftate") { body = body.split("\n").slice(0, 6).join("\n"); who = "note"; k = "status"; }
        lines.push({ k: "author", text: who });
        const w = wrap(body, cols);
        for (const l of w.slice(0, 40)) lines.push({ k, text: l });
        if (w.length > 40) lines.push({ k: "dim", text: `… ${w.length - 40} more lines` });
      }
      lines.push({ k: "hint", text: "r reply  ·  R resolve  ·  ]d next thread" });
    }
    return { lines, h: lines.length * LH + 28 };
  }

  rebuildItems() {
    const items = [], itemOfRow = [];
    const byRow = new Map(), orphans = [], outdated = [];
    for (const th of this.threadsHere()) {
      const i = this.anchorRow(th);
      if (th.outdated) outdated.push(th);
      else if (i < 0) orphans.push(th);
      else byRow.set(i, [...(byRow.get(i) ?? []), th]);
    }
    const RH = this.rowH();
    this.rows.forEach((r, i) => {
      itemOfRow[i] = items.length;
      items.push({ t: "row", i, h: RH, key: `r${i}` });
      for (const th of byRow.get(i) ?? []) items.push({ t: "thread", th, i, key: `t${th.id}`, ...this.layoutThread(th) });
    });
    if (orphans.length) {
      items.push({ t: "note", h: RH + 8, key: "orphans", text: `${orphans.length} thread(s) on lines this view doesn't show. <leader>v switches diff / full file.` });
      for (const th of orphans) items.push({ t: "thread", th, i: -1, key: `t${th.id}`, ...this.layoutThread(th) });
    }
    if (outdated.length) {
      items.push({ t: "note", h: RH + 8, key: "outdated", text: `${outdated.length} outdated thread(s): their code changed after they were written.` });
      for (const th of outdated) items.push({ t: "thread", th, i: -1, key: `t${th.id}`, ...this.layoutThread(th) });
    }
    this.items = items;
    this.itemOfRow = itemOfRow;
  }

  reveal(strategy) {
    const it = this.itemOfRow[this.cur.row];
    if (it == null) return;
    // Bring the cursor's thread blocks along when moving down onto a commented line.
    let idx = it;
    if (strategy !== "center") while (this.items[idx + 1]?.t === "thread" && this.items[idx + 1].i === this.cur.row && idx - it < 1) idx++;
    this.scroll.scroll_to_item(strategy === "center" ? it : idx, strategy === "center" ? "center" : undefined);
  }

  clampCol() {
    const len = this.rows[this.cur.row]?.text?.length ?? 0;
    // Insert mode may sit after the last character.
    const max = this.mode === "insert" ? len : Math.max(0, len - 1);
    this.cur.col = Math.max(0, Math.min(this.cur.col, max));
  }

  visibleRows() { return Math.max(5, Math.floor((this.size.height - 100) / this.rowH())); }

  spansOf(i) {
    while (this.hlUpTo <= i && this.hlUpTo < this.rows.length) {
      const r = this.rows[this.hlUpTo];
      if (r.kind === "hunk" || r.kind === "meta") { this.hlState = false; r.spans = null; }
      else { r.hlIn = this.hlState; const t = tokenize(r.text, this.lang, this.hlState); r.spans = t.spans; this.hlState = t.inBlock; }
      this.hlUpTo++;
    }
    return this.rows[i]?.spans ?? [{ text: this.rows[i]?.text ?? "", k: "text" }];
  }

  // ---------- keys ----------

  resetKeys() { this.pending = []; this.count = ""; this.seqId++; }

  onKey(e, cx) {
    // While switching to the editable view, hold keys and replay them after.
    if (this.switching) { this.keyQueue.push(e); cx.stop_propagation(); return; }
    if (this.handleKey(e, cx)) { cx.stop_propagation(); cx.notify(); }
  }

  // Returns true when the key was ours.
  handleKey(e, cx) {
    const m = e.modifiers ?? {};
    if (m.platform && String(e.key).toLowerCase() === "s") { this.save(false, cx); return true; }
    // Text fields get their own keys; we only steer the picker and close things.
    if (this.picker || this.prompt) {
      const tok = tokenOf(e);
      if (tok === "<esc>") { this.closeInput(); return true; }
      if (this.picker) {
        const down = ["<down>", "<C-n>", "<C-j>", "<tab>"].includes(tok), up = ["<up>", "<C-p>", "<C-k>"].includes(tok);
        if (down || up) {
          const n = this.picker.shown.length;
          if (n) this.picker.sel = (this.picker.sel + (down ? 1 : -1) + n) % n;
          return true;
        }
      }
      return false;
    }
    const tok = tokenOf(e);
    if (this.mode === "insert") return this.insertKey(e, tok, cx);
    if (!tok) return false;
    if (!this.pending.length && /^[0-9]$/.test(tok) && (tok !== "0" || this.count)) {
      this.count += tok;
      return true;
    }
    this.pending.push(tok);
    const key = this.pending.join(SEP);
    const tables = this.mode === "visual" ? [this.maps.visual, this.maps.normal] : [this.maps.normal];
    let action, prefix = false;
    for (const t of tables) {
      if (action === undefined && t.map.has(key)) action = t.map.get(key);
      if (t.prefixes.has(key)) prefix = true;
    }
    const count = Math.max(1, parseInt(this.count || "1", 10));
    if (action && !prefix) {
      this.resetKeys();
      this.perform(action, count, cx);
    } else if (prefix) {
      const id = ++this.seqId;
      cx.timer.after(this.opts.sequence_timeout_ms, (cx) => {
        if (this.seqId !== id) return;
        this.resetKeys();
        if (action) this.perform(action, count, cx);
        cx.notify();
      });
    } else {
      this.resetKeys();
    }
    return true;
  }

  // ---------- actions ----------

  perform(action, n, cx) {
    const A = {
      down: () => this.moveRow(n), up: () => this.moveRow(-n),
      left: () => this.moveCol(-n), right: () => this.moveCol(n),
      word_next: () => this.word(n, "next"), word_prev: () => this.word(n, "prev"), word_end: () => this.word(n, "end"),
      line_start: () => { this.cur.col = 0; this.wantCol = 0; },
      first_char: () => { this.cur.col = Math.max(0, (this.rows[this.cur.row]?.text ?? "").search(/\S/)); this.wantCol = this.cur.col; },
      line_end: () => { this.cur.col = Math.max(0, (this.rows[this.cur.row]?.text.length ?? 1) - 1); this.wantCol = Infinity; },
      top: () => this.setRow(0, true), bottom: () => this.setRow(this.rows.length - 1, true),
      half_down: () => this.moveRow(Math.floor(this.visibleRows() / 2) * n), half_up: () => this.moveRow(-Math.floor(this.visibleRows() / 2) * n),
      page_down: () => this.moveRow(this.visibleRows() * n), page_up: () => this.moveRow(-this.visibleRows() * n),
      center: () => this.reveal("center"),
      next_hunk: () => this.hunk(1, cx), prev_hunk: () => this.hunk(-1, cx),
      next_file: () => this.fileStep(n, cx), prev_file: () => this.fileStep(-n, cx),
      next_thread: () => this.threadStep(1, cx), prev_thread: () => this.threadStep(-1, cx),
      visual_line: () => { if (this.mode === "visual") this.mode = "normal"; else { this.mode = "visual"; this.anchor = this.cur.row; } },
      escape: () => {
        if (this.picker || this.prompt) this.closeInput();
        if (this.mode === "insert") { this.leaveInsert(cx); return; }
        this.mode = "normal";
        this.msg = this.dirty ? "Unsaved changes · :w saves · :e! drops them" : "";
      },
      // Editing (edit.js). From the diff these switch to the full-file view at the same line.
      insert: () => this.withEditable(cx, () => this.enterInsert("i")),
      append: () => this.withEditable(cx, () => this.enterInsert("a")),
      insert_line_start: () => this.withEditable(cx, () => this.enterInsert("I")),
      append_line_end: () => this.withEditable(cx, () => this.enterInsert("A")),
      open_below: () => this.withEditable(cx, () => this.openLine(true)),
      open_above: () => this.withEditable(cx, () => this.openLine(false)),
      delete_char: () => this.withEditable(cx, () => this.deleteChar(n)),
      delete_line: () => (this.mode === "visual" ? this.visualDelete(cx) : this.withEditable(cx, (c) => this.deleteLines(this.cur.row, n, c))),
      yank_line: () => (this.mode === "visual" ? this.visualYank(cx) : this.yankLines(this.cur.row, n, cx)),
      put_below: () => this.withEditable(cx, (c) => this.put(true, n, c)),
      put_above: () => this.withEditable(cx, (c) => this.put(false, n, c)),
      undo: () => (this.undoStack.length ? this.withEditable(cx, () => this.undo()) : (this.msg = "Already at oldest change")),
      redo: () => (this.redoStack.length ? this.withEditable(cx, () => this.redo()) : (this.msg = "Already at newest change")),
      save: () => this.save(false, cx),
      save_force: () => this.save(true, cx),
      revert: () => this.revert(cx),
      command: () => this.openPrompt({ kind: "cmd", label: ":" }),
      comment: () => this.startComment(),
      reply: () => this.startReply(),
      resolve: () => this.setThreadStatus("resolved", cx), reopen: () => this.setThreadStatus("open", cx),
      toggle_viewed: () => this.toggleViewed(cx),
      goto_definition: () => this.gotoDefinition(cx), references: () => this.references(cx),
      jump_back: () => this.jump(-1, cx), jump_forward: () => this.jump(1, cx),
      find_files: () => this.findFiles(cx), changed_files: () => this.changedFiles(), threads: () => this.threadPicker(), views: () => this.viewPicker(cx),
      toggle_explorer: () => { this.explorer = !this.explorer; this.rebuildItems(); },
      toggle_view: () => this.toggleView(cx),
      search: () => this.openPrompt({ kind: "search", label: "/" }),
      search_next: () => this.searchStep(n, cx), search_prev: () => this.searchStep(-n, cx),
      search_word: () => { const w = this.wordAt(); if (w) { this.search = w; this.searchStep(1, cx); } },
      open_in_editor: () => this.openInEditor(),
      refresh: () => this.refresh(cx),
      help: () => this.helpPicker(),
    };
    const f = A[action];
    if (!f) { this.msg = `Unknown action "${action}" (see keymap.json)`; return; }
    f();
  }

  setRow(row, reveal) {
    this.cur.row = Math.max(0, Math.min(row, this.rows.length - 1));
    this.cur.col = this.wantCol === Infinity ? Infinity : this.wantCol;
    this.clampCol();
    if (reveal) this.reveal();
  }
  moveRow(d) { this.setRow(this.cur.row + d, true); }
  moveCol(d) { this.cur.col += d; this.clampCol(); this.wantCol = this.cur.col; }

  word(n, how) {
    for (let k = 0; k < n; k++) {
      let { row, col } = this.cur;
      let text = this.rows[row]?.text ?? "";
      if (how === "next") {
        let i = col;
        if (isWord(text[i])) while (i < text.length && isWord(text[i])) i++;
        else if (i < text.length) i++;
        while (i < text.length && !isWord(text[i])) i++;
        if (i >= text.length && row < this.rows.length - 1) { row++; text = this.rows[row].text ?? ""; i = Math.max(0, text.search(/[\w$]/)); }
        this.cur = { row, col: i };
      } else if (how === "end") {
        let i = col + 1;
        while (i < text.length && !isWord(text[i])) i++;
        while (i + 1 < text.length && isWord(text[i + 1])) i++;
        this.cur = { row, col: Math.min(i, Math.max(0, text.length - 1)) };
      } else {
        let i = col - 1;
        while (i > 0 && !isWord(text[i])) i--;
        while (i > 0 && isWord(text[i - 1])) i--;
        if (i < 0 || (col === 0 && row > 0)) { row--; text = this.rows[row].text ?? ""; i = Math.max(0, text.length - 1); while (i > 0 && isWord(text[i - 1])) i--; }
        this.cur = { row, col: Math.max(0, i) };
      }
    }
    this.clampCol();
    this.wantCol = this.cur.col;
    this.reveal();
  }

  wordAt() {
    const text = this.rows[this.cur.row]?.text ?? "";
    let a = this.cur.col, b = this.cur.col;
    if (!isWord(text[a])) return null;
    while (a > 0 && isWord(text[a - 1])) a--;
    while (b < text.length && isWord(text[b])) b++;
    return text.slice(a, b);
  }

  isChangeStart(i) {
    const r = this.rows[i], p = this.rows[i - 1];
    const ch = (x) => x && (x.kind === "add" || x.kind === "del" || x.delBelow);
    return ch(r) && !(p && (p.kind === "add" || p.kind === "del") && (r.kind === "add" || r.kind === "del"));
  }

  hunk(d, cx) {
    for (let i = this.cur.row + d; i >= 0 && i < this.rows.length; i += d) {
      if (this.isChangeStart(i)) { this.setRow(i, false); this.cur.col = 0; this.reveal("center"); return; }
    }
    // Past the last change: on to the next (or previous) changed file.
    const idx = this.files.findIndex((f) => f.path === this.view?.path);
    const next = this.files[idx + d];
    if (!next) { this.msg = d > 0 ? "Last change" : "First change"; return; }
    cx.spawn(async (cx) => {
      await this.openFile(next.path, "diff", null);
      if (d < 0) {
        for (let i = this.rows.length - 1; i >= 0; i--) if (this.isChangeStart(i)) { this.setRow(i, false); break; }
        this.reveal("center");
      }
      cx.notify();
    });
  }

  fileStep(d, cx) {
    if (!this.files.length) return;
    const idx = this.files.findIndex((f) => f.path === this.view?.path);
    const next = this.files[Math.max(0, Math.min(this.files.length - 1, (idx < 0 ? 0 : idx + d)))];
    if (!next || next.path === this.view?.path) return;
    cx.spawn(async (cx) => { await this.openFile(next.path, "diff", null); cx.notify(); });
  }

  // Open threads in review order: changed files first, then the rest, by line.
  orderedThreads() {
    const order = new Map(this.files.map((f, i) => [f.path, i]));
    return this.threads.filter((t) => t.status === "open" && t.filePath)
      .sort((a, b) => (order.get(a.filePath) ?? 1e6) - (order.get(b.filePath) ?? 1e6) || a.filePath.localeCompare(b.filePath) || a.endLine - b.endLine);
  }

  threadStep(d, cx) {
    const list = this.orderedThreads();
    if (!list.length) { this.msg = "No open threads"; return; }
    const order = new Map(this.files.map((f, i) => [f.path, i]));
    const pos = (p, l) => [order.get(p) ?? 1e6, p, l];
    const cmp = (a, b) => a[0] - b[0] || a[1].localeCompare(b[1]) || a[2] - b[2];
    const r = this.rows[this.cur.row];
    const me = pos(this.view?.path ?? "", r?.new ?? r?.old ?? 0);
    const pick = d > 0 ? list.find((t) => cmp(pos(t.filePath, t.endLine), me) > 0) ?? list[0] : [...list].reverse().find((t) => cmp(pos(t.filePath, t.endLine), me) < 0) ?? list.at(-1);
    this.goToThread(pick, cx);
  }

  goToThread(th, cx) {
    cx.spawn(async (cx) => {
      // Its code isn't in this view: switch to the view it was written in, which showed it
      if (!th.inView && !th.outdated && th.writtenIn !== this.reviewView) {
        await this.switchView(th.writtenIn, cx);
        th = this.threads.find((x) => x.id === th.id) ?? th;
      }
      if (this.view?.path !== th.filePath) await this.openFile(th.filePath, this.fileOf(th.filePath) ? "diff" : "file", { line: th.endLine, side: th.side });
      let row = this.anchorRow(th);
      if (row < 0 && !th.outdated && this.view.mode === "diff") { await this.openFile(th.filePath, "file", { line: th.endLine }, false); row = this.anchorRow(th); }
      this.curThread = th.id;
      if (row >= 0) { this.setRow(row, false); this.reveal(); }
      else { const idx = this.items.findIndex((x) => x.key === `t${th.id}`); if (idx >= 0) this.scroll.scroll_to_item(idx); }
      cx.notify();
    });
  }

  // ---------- views ----------

  // Show <view> here and in every other viewer of the review (the watcher keeps it).
  async switchView(view, cx) {
    if (!this.api) { this.msg = "Start difftate (or dto) in this repo to switch views."; return; }
    if (this.busyEditing()) { this.msg = "Save or drop your edits first (:w or :e!)"; return; }
    try { await this.api.setView(view); }
    catch (e) { this.msg = `Can't show ${viewLabel(view)}: ${e.message ?? e}`; return; }
    await this.loadDiff();
    this.threadSig = null;
    await this.loadThreads();
    if (this.view) await this.reopen();
    else if (this.files.length) await this.openFile(this.files[0].path, "diff", null, false);
    this.msg = `Showing ${viewLabel(view)}`;
    cx?.notify();
  }

  // Pick a view: all changes, uncommitted, staged, unstaged, or the last N commits of the branch.
  viewPicker(cx) {
    if (!this.api) { this.msg = "Start difftate (or dto) in this repo to switch views."; return; }
    cx.spawn(async (cx) => {
      const log = this.commit ? await this.git(["log", "--format=%h %s", "-n", "30", `${this.commit}..HEAD`]).catch(() => null) : null;
      const commits = log?.code === 0 ? log.stdout.split("\n").filter(Boolean) : [];
      const items = [
        { label: "All changes", detail: `against ${this.base ?? "the base"}`, value: "" },
        { label: "Uncommitted", detail: "HEAD", value: "HEAD" },
        { label: "Staged", detail: "", value: "staged" },
        { label: "Unstaged", detail: "", value: "unstaged" },
        ...commits.map((c, i) => ({ label: `Last ${i + 1} commit${i ? "s" : ""}`, detail: `HEAD~${i + 1} · down to ${c}`, value: `HEAD~${i + 1}` })),
      ].map((it) => ({ ...it, detail: it.value === this.reviewView ? `${it.detail}${it.detail ? " · " : ""}shown` : it.detail }));
      this.openPicker("Review views", items, (v, cx) => cx.spawn(async (cx) => { await this.switchView(v, cx); cx.notify(); }));
      cx.notify();
    });
  }

  // ---------- comments ----------

  selectedRows() {
    const a = this.mode === "visual" ? Math.min(this.anchor, this.cur.row) : this.cur.row;
    const b = this.mode === "visual" ? Math.max(this.anchor, this.cur.row) : this.cur.row;
    return this.rows.slice(a, b + 1).filter((r) => r.kind === "add" || r.kind === "del" || r.kind === "ctx");
  }

  startComment() {
    if (!this.api) { this.msg = "Start difftate (or dto) in this repo to comment."; return; }
    const sel = this.selectedRows();
    if (!sel.length) { this.msg = "Nothing to comment on here"; return; }
    const side = sel.every((r) => r.kind === "del") ? "old" : "new";
    const mine = sel.filter((r) => (side === "old" ? r.old : r.new) != null && (side === "old" ? r.kind !== "add" : r.kind !== "del"));
    const nums = mine.map((r) => (side === "old" ? r.old : r.new));
    const startLine = Math.min(...nums), endLine = Math.max(...nums);
    const range = startLine === endLine ? `${startLine}` : `${startLine}-${endLine}`;
    this.openPrompt({
      kind: "comment",
      label: `Comment on ${this.view.path}:${range}${side === "old" ? " (old)" : ""}`,
      target: { filePath: this.view.path, side, startLine, endLine, code: mine.map((r) => r.raw).join("\n") },
    });
  }

  threadAtCursor() {
    const here = this.threadsHere().filter((t) => this.anchorRow(t) === this.cur.row);
    // A thread below the code (outdated, say) is picked by clicking it, ]d or the threads picker
    return here.find((t) => t.id === this.curThread) ?? here.find((t) => t.status === "open") ?? here[0]
      ?? this.threadsHere().find((t) => t.id === this.curThread && this.anchorRow(t) < 0) ?? null;
  }

  startReply() {
    if (!this.api) { this.msg = "Start difftate (or dto) in this repo to reply."; return; }
    const th = this.threadAtCursor();
    if (!th) { this.msg = "No thread on this line (]d jumps to the next one)"; return; }
    this.openPrompt({ kind: "reply", label: `Reply on ${th.filePath}:${th.endLine}`, thread: th });
  }

  setThreadStatus(status, cx) {
    const th = this.threadAtCursor();
    if (!th || !this.api) { this.msg = "No thread on this line"; return; }
    cx.spawn(async (cx) => {
      try { await this.api.setStatus(th.id, status); this.threadSig = null; await this.loadThreads(); this.msg = status === "open" ? "Reopened" : "Resolved"; }
      catch (e) { this.msg = String(e); }
      cx.notify();
    });
  }

  // ---------- bottom input: comment, reply, search, picker query ----------

  openPrompt(p) {
    this.picker = null;
    this.prompt = p;
    this.input.set_value(p.kind === "search" ? this.search : "");
    this.input.focus();
  }

  closeInput() {
    this.prompt = null;
    this.picker = null;
    this.input.set_value("");
    this.handle.focus();
  }

  submitInput(cx) {
    if (this.picker) {
      const it = this.picker.shown[this.picker.sel];
      const onPick = this.picker.onPick;
      this.closeInput();
      if (it) onPick(it.value, cx);
      cx.notify();
      return;
    }
    const p = this.prompt;
    if (!p) return;
    const typed = this.input.value();
    this.closeInput();
    // The input is one line: \n typed in a comment is a line break
    const text = p.kind === "comment" || p.kind === "reply" ? typed.replace(/\\n/g, "\n") : typed;
    if (p.kind === "search") { this.search = text; this.searchStep(1, cx); cx.notify(); return; }
    if (p.kind === "cmd") { this.runCommand(text, cx); cx.notify(); return; }
    if (!text.trim()) { cx.notify(); return; }
    cx.spawn(async (cx) => {
      try {
        if (p.kind === "comment") {
          const th = await this.api.openThread(p.target, text, this.reviewView);
          this.curThread = th.id;
          this.mode = "normal";
          this.msg = "Comment sent. The agent picks it up within a few seconds.";
        } else if (p.kind === "reply") {
          await this.api.comment(p.thread.id, text);
          this.curThread = p.thread.id;
          this.msg = "Comment sent";
        }
        this.threadSig = null;
        await this.loadThreads();
      } catch (e) {
        this.msg = `Failed: ${e}`;
      }
      cx.notify();
    });
    cx.notify();
  }

  searchStep(d, cx) {
    if (!this.search) return;
    const smart = this.search === this.search.toLowerCase();
    const q = smart ? this.search.toLowerCase() : this.search;
    const n = this.rows.length;
    for (let k = 1; k <= n; k++) {
      const i = (((this.cur.row + d * k) % n) + n) % n;
      const t = this.rows[i].text ?? "";
      const c = (smart ? t.toLowerCase() : t).indexOf(q);
      if (c >= 0) { this.cur = { row: i, col: c }; this.wantCol = c; this.reveal("center"); this.msg = `/${this.search}`; return; }
    }
    this.msg = `Pattern not found: ${this.search}`;
  }

  // ---------- pickers ----------

  openPicker(title, items, onPick) {
    this.prompt = null;
    this.picker = { title, items, onPick, sel: 0, shown: items.slice(0, 200) };
    this.input.set_value("");
    this.input.focus();
  }

  filterPicker() {
    const q = this.input.value().trim();
    const p = this.picker;
    if (!q) p.shown = p.items.slice(0, 200);
    else p.shown = p.items.map((it) => ({ it, s: fuzzy(q, it.label + (it.match ?? "")) })).filter((x) => x.s !== null).sort((a, b) => b.s - a.s).slice(0, 200).map((x) => x.it);
    p.sel = 0;
  }

  async listFiles() {
    if (this.fileCache && Date.now() - this.fileCache.at < 30000) return this.fileCache.list;
    const r = await this.git(["ls-files", "--cached", "--others", "--exclude-standard"]);
    const list = r.code === 0 ? r.stdout.split("\n").filter(Boolean) : [];
    this.fileCache = { at: Date.now(), list };
    return list;
  }

  findFiles(cx) {
    if (!this.root) return;
    cx.spawn(async (cx) => {
      const list = await this.listFiles();
      const changed = new Set(this.files.map((f) => f.path));
      this.openPicker("Find files", list.map((p) => ({ label: p, detail: changed.has(p) ? "changed" : "", value: p })), (p, cx) => {
        cx.spawn(async (cx) => { await this.openFile(p, changed.has(p) ? "diff" : "file", null); cx.notify(); });
      });
      cx.notify();
    });
  }

  changedFiles() {
    this.openPicker("Changed files", this.files.map((f) => ({ label: f.path, detail: `+${f.additions} −${f.deletions}${this.viewed.has(f.path) ? " · viewed" : ""}`, value: f.path })), (p, cx) => {
      cx.spawn(async (cx) => { await this.openFile(p, "diff", null); cx.notify(); });
    });
  }

  threadPicker() {
    const all = [...this.orderedThreads(), ...this.threads.filter((t) => t.status !== "open" && t.filePath)];
    this.openPicker("Review threads", all.map((t) => ({
      label: `${t.filePath}:${t.startLine === t.endLine ? t.startLine : `${t.startLine}-${t.endLine}`}`,
      match: " " + (t.comments[0]?.body ?? ""),
      detail: `${STATE_LABEL[stateOf(t)] ?? t.status}${t.outdated ? " · outdated" : !t.inView ? " · not in this view" : ""} · ${(t.comments[0]?.body ?? "").split("\n")[0].slice(0, 60)}`,
      value: t,
    })), (t, cx) => this.goToThread(t, cx));
  }

  helpPicker() {
    const rows = [];
    for (const [mode, table] of [["normal", this.keymap?.normal], ["visual", this.keymap?.visual], ["insert", this.keymap?.insert]]) {
      const by = {};
      for (const [k, a] of Object.entries(table ?? {})) if (a) (by[a] ??= []).push(k);
      for (const [a, ks] of Object.entries(by)) rows.push({ label: `${a}`, detail: `${mode === "normal" ? "" : `${mode}: `}${ks.join("  ")}`, match: " " + ks.join(" "), value: a });
    }
    this.openPicker("Keys (Enter runs the action)", rows, (a, cx) => this.perform(a, 1, cx));
  }

  // ---------- code navigation ----------

  async grep(args) {
    const r = await exec("rg", ["-n", "--no-heading", "--color", "never", "-m", "50", ...args, "."], { cwd: this.root }).catch(() => null);
    if (!r) return null;
    return r.stdout.split("\n").filter(Boolean).map((l) => {
      const m = /^(?:\.\/)?(.*?):(\d+):(.*)$/.exec(l);
      return m ? { path: m[1], line: +m[2], text: m[3].trim() } : null;
    }).filter(Boolean).slice(0, 300);
  }

  async goTo(hit, cx) {
    const f = this.fileOf(hit.path);
    const inDiff = f && this.diffRows(f).some((r) => r.new === hit.line && r.kind !== "del");
    await this.openFile(hit.path, inDiff ? "diff" : "file", { line: hit.line });
    const text = this.rows[this.cur.row]?.text ?? "";
    if (hit.word) { const c = text.search(new RegExp(`\\b${escapeRe(hit.word)}\\b`)); if (c >= 0) { this.cur.col = c; this.wantCol = c; } }
    cx.notify();
  }

  hitPicker(title, hits, word) {
    this.openPicker(title, hits.map((h) => ({ label: `${h.path}:${h.line}`, detail: h.text.slice(0, 90), match: " " + h.text, value: { ...h, word } })), (h, cx) => {
      cx.spawn(async (cx) => this.goTo(h, cx));
    });
  }

  gotoDefinition(cx) {
    const w = this.wordAt();
    if (!w || !this.root) { this.msg = "No word under the cursor"; return; }
    const W = escapeRe(w);
    const pats = [
      `\\b(function\\*?|def|class|interface|type|enum|struct|trait|impl|fn|func|const|let|var|module|namespace|macro|object|record|alias|typedef|local)\\s+${W}\\b`,
      `^\\s*(export\\s+)?(default\\s+)?(async\\s+)?${W}\\s*[:=]\\s*(async\\s*)?(function\\b|\\(|[A-Za-z_$][\\w$]*\\s*=>)`,
      `^\\s*((public|private|protected|static|async|override|get|set|readonly)\\s+)*${W}\\s*(<[^>]*>)?\\([^)]*\\)\\s*(:[^{]*)?\\{`,
      `^\\s*(function\\s+)?${W}\\s*\\(\\)\\s*\\{`,
      `func\\s+\\([^)]*\\)\\s+${W}\\b`,
      `^${W}=`,
    ];
    this.msg = `Finding ${w}…`;
    cx.spawn(async (cx) => {
      const hits = await this.grep(pats.flatMap((p) => ["-e", p]));
      if (hits === null) { this.msg = "ripgrep (rg) is needed for go to definition"; cx.notify(); return; }
      if (hits.length === 1) { this.msg = ""; await this.goTo({ ...hits[0], word: w }, cx); return; }
      if (hits.length > 1) { this.msg = ""; this.hitPicker(`Definitions of ${w}`, hits, w); cx.notify(); return; }
      const refs = await this.grep(["-w", "-F", w]);
      this.msg = `No definition found for ${w}; showing references`;
      if (refs?.length) this.hitPicker(`References to ${w}`, refs, w);
      cx.notify();
    });
  }

  references(cx) {
    const w = this.wordAt();
    if (!w || !this.root) { this.msg = "No word under the cursor"; return; }
    cx.spawn(async (cx) => {
      const hits = await this.grep(["-w", "-F", w]);
      if (!hits?.length) this.msg = `No references to ${w}`;
      else this.hitPicker(`References to ${w} (${hits.length})`, hits, w);
      cx.notify();
    });
  }

  jump(d, cx) {
    if (d < 0) {
      if (this.jumpIdx <= 0) { this.msg = "Start of jump list"; return; }
      if (this.jumpIdx === this.jumps.length) this.jumps.push(this.here());
      this.jumpIdx--;
    } else {
      if (this.jumpIdx >= this.jumps.length - 1) { this.msg = "End of jump list"; return; }
      this.jumpIdx++;
    }
    const j = this.jumps[this.jumpIdx];
    cx.spawn(async (cx) => { await this.openFile(j.path, j.mode, { line: j.line, col: j.col, row: j.row }, false); cx.notify(); });
  }

  toggleView(cx) {
    if (!this.view) return;
    const h = this.here();
    const r = this.rows[this.cur.row];
    let line = r?.new;
    for (let i = this.cur.row; line == null && i >= 0; i--) line = this.rows[i]?.new;
    const mode = h.mode === "diff" ? "file" : "diff";
    if (mode === "diff" && !this.fileOf(h.path)) { this.msg = "This file has no changes"; return; }
    cx.spawn(async (cx) => { await this.openFile(h.path, mode, { line, col: h.col }, false); cx.notify(); });
  }

  openInEditor() {
    if (!this.view) return;
    const line = this.rows[this.cur.row]?.new ?? 1;
    // $EDITOR from the login shell, else vi; opens beside the review.
    run("terminal.open", { argv: ["sh", "-lc", 'exec ${EDITOR:-vi} "+$1" "$2"', "sh", String(line), this.view.path], folder: this.root, place: "right" });
  }

  refresh(cx) {
    this.diffText = null;
    this.threadSig = null;
    this.fileCache = null;
    cx.spawn(async (cx) => {
      await this.loadKeymap(); // picks up edits to ~/.config/difftate/keymap.json
      if (this.api) { await this.loadDiff().catch(() => {}); await this.loadThreads(); await this.loadViewed(); }
      else await this.attach(cx);
      if (this.view) await this.reopen();
      this.msg = "Refreshed";
      cx.notify();
    });
  }

  // ---------- render ----------

  color(t, k) {
    return { keyword: t.ansi5, string: t.ansi2, number: t.ansi3, comment: t.dim, type: t.ansi6, function: t.ansi4, punct: t.muted }[k] ?? t.foreground;
  }

  inSel(i) {
    if (this.mode !== "visual") return false;
    return i >= Math.min(this.anchor, this.cur.row) && i <= Math.max(this.anchor, this.cur.row);
  }

  rowEl(i, t) {
    const r = this.rows[i];
    const RH = this.rowH(), cw = this.cw(), nw = this.numW();
    const cur = i === this.cur.row;
    if (r.kind === "hunk" || r.kind === "meta") {
      return h_flex().h(RH).w_full().flex_none().px(10).items_center().bg(cur ? t.selected : t.raised).text_color(t.dim).child(div().whitespace_nowrap().child(r.text));
    }
    const sel = this.inSel(i);
    const bg = sel ? t.selection : r.kind === "add" ? t.ansi2 + "1f" : r.kind === "del" ? t.ansi1 + "1f" : cur ? t.hover : null;
    const mark = r.edited ? t.ansi3 : r.kind === "add" ? t.ansi2 : r.kind === "del" ? t.ansi1 : null;
    const spans = this.spansOf(i);
    const insert = this.mode === "insert";
    const num = (v) => div().w(nw).flex_none().text_right().pr(8).text_color(cur ? t.foreground : t.dim).child(v == null ? "" : String(v));
    return h_flex().h(RH).w_full().flex_none().items_center()
      .when(Boolean(bg), (el) => el.bg(bg))
      .when(Boolean(r.delBelow), (el) => el.border_b(1).border_color(t.ansi1 + "aa"))
      .child(div().w(3).h_full().flex_none().when(Boolean(mark), (el) => el.bg(mark)))
      .when(this.view.mode === "diff", (el) => el.child(num(r.kind === "add" ? null : r.old)))
      .child(num(r.kind === "del" ? null : r.new))
      .child(div().w(16).flex_none().text_color(mark ?? t.dim).child(r.kind === "add" ? "+" : r.kind === "del" ? "−" : " "))
      .child(div().relative().flex_1().h_full().min_w(0)
        .child(h_flex().h_full().items_center().children(spans.length ? spans.map((s) => div().whitespace_nowrap().flex_none().text_color(this.color(t, s.k)).child(s.text)) : [div().child(" ")]))
        .when(cur, (el) => el.child(div().absolute().top(2).left(Math.min(this.cur.col, Math.max(0, r.text.length)) * cw)
          .w(insert ? 2 : cw).h(RH - 4).rounded(1).bg(insert ? t.foreground : t.accent + (this.handle.is_focused() ? "99" : "44")))));
  }

  threadEl(it, t) {
    const th = it.th, state = stateOf(th);
    const on = th.id === this.curThread && (it.i < 0 || this.anchorRow(th) === this.cur.row);
    const stripe = { waiting: t.blocked, queued: t.blocked, working: t.working, replied: t.done, failed: t.ansi1 }[state] ?? t.dim;
    const tc = (k) => ({ head: stripe, author: t.dim, agent: t.foreground, status: t.muted, hint: t.dim, dim: t.dim, code: t.muted }[k] ?? t.foreground);
    return h_flex().h(it.h).w_full().flex_none().pl(this.gutterW()).pr(20).py(5)
      .child(h_flex().h_full().flex_1().min_w(0).rounded(6).overflow_hidden().border_1().border_color(on ? t.accent : t.border).bg(t.surface)
        .child(div().w(3).h_full().flex_none().bg(stripe))
        .child(v_flex().flex_1().min_w(0).px(10).py(4)
          .children(it.lines.map((l) => div().h(LH).flex_none().whitespace_nowrap().overflow_hidden()
            .text_color(tc(l.k)).when(l.k === "author" || l.k === "head", (el) => el.font_semibold()).child(l.text || " ")))));
  }

  itemEl(idx, t) {
    const it = this.items[idx];
    if (it.t === "row") return this.rowEl(it.i, t);
    if (it.t === "thread") return this.threadEl(it, t);
    return h_flex().h(it.h).w_full().flex_none().px(12).items_center().text_color(t.dim).child(it.text);
  }

  clickItem(key, cx) {
    const it = this.items.find((x) => x.key === key);
    if (!it) return;
    const row = it.t === "row" ? it.i : it.t === "thread" ? it.i : -1;
    if (it.t === "thread") this.curThread = it.th.id;
    if (row >= 0) {
      if (this.shift && this.mode !== "visual") { this.mode = "visual"; this.anchor = this.cur.row; }
      else if (!this.shift && this.mode === "visual") this.mode = "normal";
      this.cur.row = row;
      this.clampCol();
    }
    this.handle.focus();
    cx.notify();
  }

  explorerEl(t) {
    const open = new Map();
    for (const th of this.threads) if (th.status === "open") open.set(th.filePath, (open.get(th.filePath) ?? 0) + 1);
    const status = { added: "A", deleted: "D", renamed: "R", copied: "C" };
    return v_flex().w(EXPLORER_W).flex_none().h_full().min_h(0).bg(t.chrome).border_r(1).border_color(t.border)
      .child(h_flex().h(30).flex_none().px(12).items_center().text_size(11).text_color(t.dim)
        .child(div().flex_1().child(`Changed files · ${this.files.length}`))
        .child(div().child(`${this.files.filter((f) => this.viewed.has(f.path)).length} viewed`)))
      .child(v_flex().id("dt-files").flex_1().min_h(0).px(6).pb(8).overflow_y_scrollbar()
        .children(this.files.map((f) => {
          const parts = f.path.split("/"), name = parts.pop();
          const on = f.path === this.view?.path;
          const n = open.get(f.path) ?? 0;
          const seen = this.viewed.has(f.path);
          return h_flex().id(`dt-f-${f.path}`).h(26).flex_none().px(8).gap(6).rounded(6).items_center().cursor_pointer()
            .when(on, (el) => el.bg(t.selected)).hover((s) => s.bg(t.hover))
            .on_click((_e, cx) => { cx.spawn(async (cx) => { await this.openFile(f.path, "diff", null); this.handle.focus(); cx.notify(); }); })
            .child(div().w(10).flex_none().text_size(10.5).text_color(f.status === "added" ? t.ansi2 : f.status === "deleted" ? t.ansi1 : t.blocked).child(status[f.status] ?? "M"))
            .child(h_flex().flex_1().min_w(0).text_size(12)
              .child(div().min_w(0).truncate().text_color(seen ? t.dim : t.foreground).child(name))
              .when(parts.length > 0, (el) => el.child(div().pl(6).min_w(0).truncate().text_size(10.5).text_color(t.dim).child(parts.join("/")))))
            .when(seen, (el) => el.child(div().text_size(10.5).text_color(t.ansi2).child("✓")))
            .when(n > 0, (el) => el.child(div().px(5).h(16).flex().items_center().rounded(4).bg(t.blocked + "26").text_size(10).text_color(t.blocked).child(String(n))))
            .child(div().text_size(10.5).text_color(t.ansi2).child(f.additions ? `+${f.additions}` : ""))
            .child(div().text_size(10.5).text_color(t.ansi1).child(f.deletions ? `−${f.deletions}` : ""));
        })));
  }

  pickerEl(t) {
    const p = this.picker;
    const start = Math.max(0, Math.min(p.sel - 7, p.shown.length - 16));
    const shown = p.shown.slice(start, start + 16);
    return div().absolute().top(40).left(0).w_full().flex().justify_center()
      .child(v_flex().w(Math.min(760, this.size.width - 40)).rounded(10).overflow_hidden().border_1().border_color(t.border).bg(t.popover).shadow_lg()
        .child(h_flex().h(30).px(12).items_center().text_size(11.5).text_color(t.dim)
          .child(div().flex_1().child(p.title)).child(div().child(`${p.shown.length}${p.shown.length === 200 ? "+" : ""} · ↑↓ ctrl-n/p · Enter · Esc`)))
        .child(div().px(10).pb(8).child(Input.new(this.input).h(32).px(10).rounded(7).border_1().border_color(t.accent).bg(t.background).text_size(13).text_color(t.foreground)))
        .child(v_flex().pb(6).children(shown.map((it, k) => {
          const on = start + k === p.sel;
          return h_flex().id(`dt-pk-${start + k}`).h(26).px(14).gap(10).items_center().cursor_pointer()
            .when(on, (el) => el.bg(t.selected)).hover((s) => s.bg(t.hover))
            .on_click((_e, cx) => { p.sel = start + k; this.submitInput(cx); })
            .child(div().flex_none().max_w(440).truncate().text_size(12.5).text_color(t.foreground).child(it.label))
            .child(div().flex_1().min_w(0).truncate().text_size(11.5).text_color(t.dim).child(it.detail ?? ""));
        }))
          .when(!p.shown.length, (el) => el.child(div().px(14).py(6).text_size(12).text_color(t.dim).child("No matches")))));
  }

  render(cx) {
    const t = theme();
    if (this.launcher) return div();
    const fs = this.opts.font_size;
    const mono = settings().font_family ?? "JetBrains Mono";
    const open = this.threads.filter((x) => x.status === "open");
    const waiting = open.filter((x) => ["waiting", "queued", "working"].includes(stateOf(x))).length;
    const maxLen = this.rows.reduce((m, r) => Math.max(m, r.text?.length ?? 0), 0);
    const contentW = this.gutterW() + maxLen * this.cw() + 40;
    const r = this.rows[this.cur.row];
    const modeLabel = this.mode === "visual" ? "V-LINE" : this.mode === "insert" ? "INSERT" : "NORMAL";
    const modeBg = this.mode === "visual" ? t.ansi5 : this.mode === "insert" ? t.ansi2 : t.accent;

    const header = h_flex().h(36).flex_none().px(14).gap(10).items_center().bg(t.chrome).border_b(1).border_color(t.border).text_size(12)
      .child(div().font_semibold().text_size(13).child(this.repo ?? "Review"))
      .child(div().text_color(t.dim).child(this.api && this.base ? `${viewLabel(this.reviewView)} · against ${this.base}` : ""))
      .child(div().flex_1())
      .when(open.length > 0, (el) => el.child(div().text_color(t.muted).child(`${open.length} open thread${open.length === 1 ? "" : "s"}${waiting ? ` · ${waiting} with the agent` : ""}`)))
      .child(h_flex().gap(6).items_center()
        .child(div().size(7).rounded(4).bg(this.api ? t.done : t.dim))
        .child(div().text_color(t.dim).child(this.api ? `review API :${this.api.port}` : "not connected")))
      .child(div().id("dt-help").px(8).h(22).flex().items_center().rounded(5).border_1().border_color(t.border).text_color(t.muted).cursor_pointer()
        .hover((s) => s.bg(t.hover)).on_click((_e, cx) => { this.helpPicker(); cx.notify(); }).child("? keys"));

    const code = this.view
      ? div().id("dt-code").flex_1().h_full().min_w(0).min_h(0).relative().font_family(mono).text_size(fs).bg(t.background)
        .on_mouse_down("left", () => this.handle.focus())
        .child(div().id("dt-code-x").size_full().overflow_x_scrollbar()
          .child(div().h_full().min_w(Math.max(contentW, this.codeW())).w_full()
            .child(v_virtual_list("dt-lines", this.items.length, this.items.map((x) => x.h), (i) => this.items[i].key,
              (range) => { const out = []; for (let i = range.start; i < range.end; i++) out.push(this.itemEl(i, t)); return out; })
              .track_scroll(this.scroll).on_item_click((key, cx) => this.clickItem(key, cx)).size_full())))
        .child(Scrollbar.vertical("dt-lines").viewport_from_layout().absolute().inset_0())
      : v_flex().flex_1().h_full().items_center().justify_center().gap(8).bg(t.background).text_color(t.dim).text_size(13)
        .child(div().child(this.msg || "No changes to review"))
        .child(div().text_size(12).child(`${this.leader === "<space>" ? "Space" : this.leader} Space finds any file in the repo · ? lists keys`));

    const promptBar = this.prompt
      ? h_flex().flex_none().px(12).py(8).gap(10).items_center().bg(t.chrome).border_t(1).border_color(t.border)
        .child(div().flex_none().max_w(360).truncate().text_size(12).text_color(this.prompt.kind === "search" ? t.foreground : t.accent).child(this.prompt.label))
        .child(Input.new(this.input).flex_1().h(32).px(10).rounded(7).border_1().border_color(t.accent).bg(t.background).text_size(12.8).text_color(t.foreground))
        .child(div().flex_none().text_size(11).text_color(t.dim).child(this.prompt.kind === "search" || this.prompt.kind === "cmd" ? "Enter · Esc" : "Enter sends · \\n new line · Esc"))
      : null;

    const statusBar = h_flex().h(26).flex_none().px(10).gap(10).items_center().bg(t.chrome).border_t(1).border_color(t.border).text_size(11.5)
      .child(div().px(7).h(18).flex().items_center().rounded(4).font_semibold().text_size(10.5)
        .bg(modeBg).text_color(t.accent_foreground ?? t.background).child(modeLabel))
      .when(Boolean(this.count || this.pending.length), (el) => el.child(div().font_family(mono).text_color(t.foreground).child(this.count + this.pending.join(""))))
      .child(div().flex_1().min_w(0).truncate().text_color(this.keymapError ? t.blocked : t.muted).child(this.keymapError ?? this.msg ?? ""))
      .when(Boolean(this.view), (el) => el
        .child(div().text_color(t.dim).child(this.view.mode === "diff" ? "diff" : "file"))
        .when(this.viewed.has(this.view.path), (el) => el.child(div().text_color(t.ansi2).child("✓ viewed")))
        .when(this.dirty, (el) => el.child(div().text_color(t.ansi3).font_semibold().child("[+] unsaved")))
        .child(div().max_w(420).truncate().text_color(t.muted).child(`${this.view.path}  ${r?.new ?? r?.old ?? "-"}:${this.cur.col + 1}`)));

    return v_flex().id("dt-root").size_full().min_h(0).bg(t.background).text_color(t.foreground).relative()
      .track_focus(this.handle)
      .on_key_down((e, cx) => this.onKey(e, cx))
      .on_modifiers_changed((e) => { this.shift = Boolean(e.modifiers?.shift); })
      .on_size_change((size, cx) => {
        const widthChanged = Math.abs(size.width - this.size.width) > 1;
        this.size = size;
        if (widthChanged) this.rebuildItems();
        cx.notify();
      })
      .child(header)
      .child(h_flex().flex_1().min_h(0)
        .when(this.explorer, (el) => el.child(this.explorerEl(t)))
        .child(code))
      .when(Boolean(promptBar), (el) => el.child(promptBar))
      .child(statusBar)
      .when(Boolean(this.picker), (el) => el.child(this.pickerEl(t)));
  }
}

Object.assign(Review.prototype, Editing);
