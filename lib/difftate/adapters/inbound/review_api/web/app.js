// difftate's own browser viewer: the review's changeset in the view the watcher shows,
// threads under their lines with their thread state and outdated marks, every thread in
// the threads list, and comment, reply, resolve, dismiss and reopen. It is a client of
// the review API (lib/difftate/adapters/inbound/review_api/server.py) like the Neovim viewer. It never sees the API token:
// the link the watcher opened got it a cookie, which its calls send with the page's header.

import { parseDiff } from "./diff.js";
import { unseen } from "./warnings.js";
import { orderFiles, rows as pathRows, stopBlock } from "./review_path.js";

const POLL_MS = 1500;
const STATE_LABEL = {
  held: "held until you submit", waiting: "waiting for agent", queued: "queued", working: "agent working", replied: "agent replied",
  failed: "failed: no reply", resolved: "resolved", dismissed: "dismissed",
};
const AUTHOR = { reviewer: "Reviewer", agent: "Coding agent", difftate: "difftate" };
const KIND = { queued: "queued note", progress: "progress note" };
// Who wrote a comment: the reviewer by their reviewer name when it has one ("by"; a thread
// written before reviewer names, or a watcher without them, has none)
const who = (c) => (c.author === "reviewer" && c.by ? c.by : AUTHOR[c.author] ?? c.author);
// "resolved by security-bot": a resolved or dismissed thread names the reviewer who closed it
const statusLabel = (t, s) => (t.status !== "open" && t.statusBy ? `${STATE_LABEL[s] ?? s} by ${t.statusBy}` : STATE_LABEL[s] ?? s);
// Where a thread stands: its thread state while open, else its status (resolved, dismissed)
const stateOf = (t) => (t.status === "open" ? t.state ?? "waiting" : t.status);
// How the viewer names a view of the review
const viewLabel = (v) => (!v ? "all changes" : v === "HEAD" ? "uncommitted changes" : v === "staged" || v === "unstaged" ? `${v} changes` : `the commits after ${v}`);
const lines = (a) => (a.startLine === a.endLine ? `${a.startLine}` : `${a.startLine}–${a.endLine}`);
const where = (a) => (a ? `${a.file}:${lines(a)}${a.side === "old" ? " (old)" : ""}` : "general");

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// The checked-out folder this page is about: the link that opened it names it (?folder=), and every API
// request names it too (the one watcher serves every folder)
const pageFolder = new URLSearchParams(location.search).get("folder") ?? "";
const aboutFolder = (path) => `${path}${path.includes("?") ? "&" : "?"}folder=${encodeURIComponent(pageFolder)}`;

async function api(method, path, payload) {
  const options = { method, headers: { "X-Difftate": "page" }, credentials: "same-origin" };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const r = await fetch(aboutFolder(path), options);
  const text = await r.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!r.ok) throw new ApiError(r.status, body?.error ?? `${method} ${path}: ${r.status}`);
  return body;
}

// ---------- state ----------

const state = {
  review: null,
  view: "",
  diff: null,
  files: [],
  threads: [],
  mode: { mode: "live", held: [] }, // the review mode, and the ids of the held threads (GET /api/mode)
  agent: null, // who replies: {agent, source: "review"|"repository"|"machine", names} (GET /api/agent); null when the agent list can't be read
  path: null, // the review path the coding agent wrote ("path" of GET /api/review-path), or null: the file list then follows the changeset
  viewed: [], // paths of the files marked viewed (the watcher clears a mark when the file's diff changes)
  sig: null,
  filter: load("difftate.filter", "all"),
  newThread: null, // {file, side, start, end} on lines of the diff, or {general: true}
  drafts: new Map(), // textarea key -> text not sent yet
  expanded: new Set(), // resolved or dismissed threads shown in full
  placed: new Set(), // threads shown under a line of this view
  sending: false,
  boxes: new Map(), // textarea key -> its element, kept across renders (undo, size, IME)
  stale: false, // a render waits for the reviewer to finish composing or selecting text
};

function load(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private window: not remembered */ }
}

// ---------- the API, polled ----------

const shownWarnings = new Set(); // the ids of the warnings this page showed
let latest = 0;
async function refresh() {
  const mine = ++latest;
  const review = await api("GET", "/api/review"); // the watcher follows the checked-out branch
  const modeCall = api("GET", "/api/mode");
  const agentCall = api("GET", "/api/agent").catch(() => null); // a wrong agent list shows no agent, not no review
  const c = await api("GET", "/api/changeset");
  const view = c.view ?? "";
  const threads = await api("GET", `/api/threads?view=${encodeURIComponent(view)}`);
  const { files: viewed } = await api("GET", "/api/viewed");
  // The path in the view shown. A file that can't be read as a path answers null (the warning says why);
  // a failed call keeps the path shown, so one bad poll doesn't reorder the list
  const path = (await api("GET", `/api/review-path?view=${encodeURIComponent(view)}`).catch(() => ({ path: state.path })))?.path ?? null;
  const mode = await modeCall;
  const agent = await agentCall;
  if (mine !== latest) return; // a later refresh (after a view switch, say) has newer news
  for (const w of unseen(review.warnings, shownWarnings)) setMessage(`⚠ ${w.text}`);
  const sig = JSON.stringify([review, view, c.base, c.diff, threads, viewed, mode, agent, path]);
  if (sig === state.sig) return;
  // A new thread's lines were the other view's, or the other branch's
  if (view !== state.view || review.id !== state.review?.id) state.newThread = null;
  // The files in the review path's order when there is one, else the changeset's
  state.files = orderFiles(withVersions(parseDiff(c.diff), c.versions), pathRows(path));
  Object.assign(state, { review, view, base: c.base, diff: c.diff, threads, viewed, mode, agent, path, sig });
  render();
}

let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    await refresh();
    if (!message.sticky) return;
    setMessage("");
  } catch (e) {
    problem(e);
  } finally {
    pollTimer = setTimeout(poll, POLL_MS);
  }
}

function problem(e) {
  if (e instanceof ApiError && e.status === 401) {
    setMessage("This page's watcher has stopped. Open the link a running difftate prints.", { sticky: true });
  } else if (e instanceof ApiError) {
    setMessage(e.message, { sticky: true });
  } else {
    setMessage("Can't reach the watcher: is difftate still running in this repository?", { sticky: true });
  }
}

// Run an action against the API, then show the review as it is now
async function act(action, done) {
  if (state.sending) return false;
  state.sending = true;
  try {
    await action();
    if (done) setMessage(done, { info: true });
    await refresh();
    return true;
  } catch (e) {
    setMessage(e.message ?? String(e));
    return false;
  } finally {
    state.sending = false;
  }
}

const message = { timer: null, sticky: false };
function setMessage(text, { info = false, sticky = false } = {}) {
  const m = $("message");
  clearTimeout(message.timer);
  m.textContent = text;
  m.className = info ? "info" : "";
  message.sticky = sticky && !!text;
  if (info && text) message.timer = setTimeout(() => { if (m.textContent === text) m.textContent = ""; }, 3000);
}

// ---------- actions ----------

async function switchView(view) {
  if (view === state.view) return true;
  const ok = await act(() => api("PUT", "/api/view", { view }), `Showing ${viewLabel(view)}`);
  if (!ok) renderHeader(); // the menu shows the view still shown
  return ok;
}

// Change the review mode. Changing to live submits what is held: say so
async function switchMode(mode) {
  if (mode === state.mode.mode) return true;
  let submitted = [];
  const ok = await act(async () => { submitted = (await api("PUT", "/api/mode", { mode })).submitted ?? []; });
  if (ok) setMessage(mode === "batched" ? "Batched: comments are held until you submit" : submitted.length ? `Live: ${heldCount(submitted.length)} submitted to the coding agent` : "Live: comments go to the coding agent as you write them", { info: true });
  else renderHeader(); // the menu shows the mode the review is in
  return ok;
}

// Choose the agent for this review, or "" to go back to the repository's
async function switchAgent(agent) {
  const ok = await act(() => api("PUT", "/api/agent", { agent: agent || null }));
  if (ok) setMessage(agent ? `${agent} replies in this review, from the next run` : `The review's own agent is cleared: the repository's (or the machine's) agent replies, from the next run`, { info: true });
  else renderHeader(); // the menu shows the agent the review has
  return ok;
}

// Submit the held threads: they go to the coding agent as one run
async function submitHeld() {
  let submitted = [];
  const ok = await act(async () => { submitted = (await api("POST", "/api/submit", {})).submitted ?? []; });
  if (ok) setMessage(submitted.length ? `Submitted ${heldCount(submitted.length)}` : "Nothing is held: nothing to submit", { info: true });
}

// Copy the review's export to the clipboard, for an agent session the reviewer starts. It names the
// watcher's folder in its reply command, so the session can reply from anywhere. Changes no thread
async function exportReview() {
  try {
    const folder = state.review?.folder;
    const r = await fetch(aboutFolder(`/api/export${folder ? `?reply_folder=${encodeURIComponent(folder)}` : ""}`), { headers: { "X-Difftate": "page" }, credentials: "same-origin" });
    const text = await r.text();
    if (!r.ok) {
      let said = null;
      try { said = JSON.parse(text).error; } catch { /* not JSON */ }
      throw new Error(said ?? `GET /api/export: ${r.status}`);
    }
    if (!text.trim()) throw new Error("The watcher gave no export (is it up to date?)");
    await copyText(text);
    setMessage("Export copied: paste it into an agent session", { info: true });
  } catch (e) {
    setMessage(`Could not export: ${e.message ?? e}`);
  }
}

// The text on the clipboard: the async API where the page may use it, else a selected textarea
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch { /* fall through */ }
  const area = el("textarea", { style: "position:fixed;opacity:0" });
  area.value = text;
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("the browser refused to copy");
}

const heldCount = (n) => `${n} held thread${n === 1 ? "" : "s"}`;

async function sendNewThread() {
  const t = state.newThread;
  const body = (state.drafts.get("new") ?? "").trim();
  if (!t || !body) return;
  // The code and the version of the file shown when the lines were picked: if the file
  // changed since, the thread moves with that code to where it is now
  const anchor = t.general ? null : { file: t.file, side: t.side, startLine: t.start, endLine: t.end, code: t.code, version: t.version };
  const ok = await act(() => api("POST", "/api/threads", { anchor, body, view: state.view }), state.mode.mode === "batched" ? "Comment held until you submit" : "Comment sent");
  if (ok) {
    state.newThread = null;
    state.drafts.delete("new");
    state.boxes.delete("new");
    render();
  }
}

async function sendReply(t) {
  const key = `reply:${t.id}`;
  const body = (state.drafts.get(key) ?? "").trim();
  if (!body) return;
  const ok = await act(() => api("POST", `/api/threads/${encodeURIComponent(t.id)}/comments`, { kind: "comment", body }), "Reply sent");
  if (ok) {
    state.drafts.delete(key);
    state.boxes.delete(key);
    render();
  }
}

function setStatus(t, status) {
  const done = { open: "Reopened", resolved: "Resolved", dismissed: "Dismissed" }[status];
  return act(() => api("PATCH", `/api/threads/${encodeURIComponent(t.id)}/status`, { status }), done);
}

// A thread with no line in this view that the view it was written in shows: its view
const shownIn = (t) => (t.anchor && !t.outdated && !state.placed.has(t.id) && (t.anchor.view ?? "") !== state.view ? t.anchor.view ?? "" : null);

// Show a thread from the threads list: in the view it was written in when this one
// has no line for it, opened when it was closed
async function goTo(t) {
  const view = shownIn(t);
  if (view !== null && !(await switchView(view))) return;
  t = state.threads.find((x) => x.id === t.id) ?? t;
  if (t.status !== "open" && !state.expanded.has(t.id)) {
    state.expanded.add(t.id);
    render();
  }
  const card = document.getElementById(`thread-${t.id}`);
  if (!card) return;
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  card.classList.add("flash");
  setTimeout(() => card.classList.remove("flash"), 1500);
}

// Pick lines to comment on: a click starts, a shift-click on the same side extends
function pick(file, side, n, extend) {
  const t = state.newThread;
  if (extend && t && !t.general && t.file === file.path && t.side === side) {
    const start = Math.min(t.start, n), end = Math.max(t.end, n);
    const have = new Set(sideRows(file, side).map((r) => r.n));
    let whole = true;
    for (let i = start; i <= end; i++) whole &&= have.has(i);
    if (whole) {
      state.newThread = picked(file, side, start, end);
      render();
      focusDraft("new");
      return;
    }
  }
  state.newThread = picked(file, side, n, n);
  render();
  focusDraft("new");
}

// Lines <start>..<end> on one side of a file as the diff shows them: their code, and the
// version of the file that side shows (null from a watcher that doesn't name versions)
function picked(file, side, start, end) {
  const code = sideRows(file, side).filter((r) => r.n >= start && r.n <= end).map((r) => r.line.content).join("\n");
  return { file: file.path, side, start, end, code, version: file.versions?.[side] ?? null };
}

// The parsed files, each with the versions of its two sides from the changeset: {old, new}
const withVersions = (files, versions) => files.map((f) => ({ ...f, versions: versions?.[f.path] ?? null }));

// ---------- rendering ----------

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "value") node.value = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c);
  return node;
}

// A file's lines on one side of the diff: [{n, line}] (old: deleted and context lines; new: added and context)
function sideRows(file, side) {
  const rows = [];
  for (const h of file?.hunks ?? []) {
    for (const line of h.lines) {
      const n = side === "old" ? line.oldLineNumber : line.newLineNumber;
      if (n !== null && n !== undefined) rows.push({ n, line });
    }
  }
  return rows;
}

// Where each thread sits: under the line it ends on (key "<file>\0<side>\0<line>"), when
// its code is in this view and on a line the diff shows. Never an outdated one: its code changed.
function placeThreads() {
  const shown = new Set();
  for (const f of state.files) for (const side of ["old", "new"]) for (const r of sideRows(f, side)) shown.add(`${f.path}\0${side}\0${r.n}`);
  const under = new Map(), elsewhere = [];
  for (const t of state.threads) {
    const a = t.anchor;
    const key = a && `${a.file}\0${a.side}\0${a.endLine}`;
    if (a && !t.outdated && t.inView !== false && shown.has(key)) {
      if (!under.has(key)) under.set(key, []);
      under.get(key).push(t);
    } else elsewhere.push(t);
  }
  state.placed = new Set([...under.values()].flat().map((t) => t.id));
  return { under, elsewhere };
}

function ordered(threads) {
  const order = new Map(state.files.map((f, i) => [f.path, i]));
  const pos = (t) => (t.anchor ? order.get(t.anchor.file) ?? 1e6 : -1);
  return [...threads].sort((a, b) => pos(a) - pos(b)
    || (a.anchor?.file ?? "").localeCompare(b.anchor?.file ?? "")
    || (a.anchor?.endLine ?? 0) - (b.anchor?.endLine ?? 0));
}

const visible = (t) => state.filter === "all" || t.status === "open";
const gist = (t) => (t.comments[0]?.body ?? "").split("\n")[0];

// Not while the reviewer composes text (an input method) or selects some: once they're done
let composing = false;
function busyReading() {
  const picked = window.getSelection();
  return composing || (picked && !picked.isCollapsed && $("main").contains(picked.anchorNode));
}

function render() {
  if (busyReading()) {
    state.stale = true;
    return;
  }
  state.stale = false;
  // Keep what the reviewer is typing, and where
  const active = document.activeElement;
  const focusKey = active?.dataset?.draft;
  const selection = focusKey ? [active.selectionStart, active.selectionEnd] : null;

  renderHeader();
  const placed = placeThreads();
  renderSidebar();
  renderMain(placed);
  for (const key of state.boxes.keys()) if (!state.boxes.get(key).isConnected) state.boxes.delete(key);

  if (focusKey) {
    const again = document.querySelector(`textarea[data-draft="${CSS.escape(focusKey)}"]`);
    if (again) {
      again.focus({ preventScroll: true });
      again.setSelectionRange(...selection);
    }
  }
}

// While a run holds the watcher on this review after a checkout: one line saying so
function waitingBanner(r) {
  if (!r.waitingForRun) return "";
  const other = r.checkedOut ? `${r.checkedOut} is checked out` : "Another branch is checked out";
  return `⏳ ${other}: this review stays until the run in progress ends, then the watcher moves to that branch's review. Threads aren't placed in its code meanwhile.`;
}

function renderHeader() {
  const r = state.review ?? {};
  $("what").textContent = r.branch ? `${r.branch} against ${r.base ?? state.base}` : `against ${state.base ?? "the base"}`;
  const select = $("view");
  if (![...select.options].some((o) => o.value === state.view)) {
    select.append(el("option", { value: state.view, text: `Commits after ${state.view}` }));
  }
  select.value = state.view;
  document.title = `difftate · ${r.branch ?? "review"} · ${viewLabel(state.view)}`;
  $("waiting").textContent = waitingBanner(r);
  const { mode, held } = state.mode;
  $("mode").value = mode;
  // Submit only in a batched review (a live one holds nothing); disabled while nothing is held
  const choice = $("agent"), agent = state.agent;
  choice.disabled = !agent;
  if (agent) {
    const own = agent.source === "review";
    // The first entry is the review without a choice of its own: the one the repository (or the machine) says
    const inherited = own ? "Default" : `Default (${agent.agent}, ${agent.source})`;
    choice.replaceChildren(el("option", { value: "", text: inherited }), ...(own && !agent.names.includes(agent.agent) ? [...agent.names, agent.agent] : agent.names).map((n) => el("option", { value: n, text: n })));
    choice.value = own ? agent.agent : "";
  } else {
    choice.replaceChildren(el("option", { value: "", text: "agent list not readable" }));
  }
  $("submit-box").hidden = mode !== "batched";
  $("held").textContent = `${held.length} held`;
  $("submit").disabled = held.length === 0;
  $("submit").title = held.length ? `Submit the ${heldCount(held.length)} to the coding agent as one run` : "Nothing is held: comment first";
}

function renderSidebar() {
  const files = $("files");
  const viewedMark = (path) => (state.viewed.includes(path) ? el("span", { class: "viewed", text: " ✓", title: "Viewed" }) : null);
  const listed = pathRows(state.path);
  if (!state.files.length) {
    files.replaceChildren(el("li", { class: "empty", text: "No changes in this view" }));
  } else if (!listed.length) {
    files.replaceChildren(...state.files.map((f, i) => el("li", {},
      el("a", { href: `#file-${i}`, title: f.path },
        el("span", { class: "counts" }, el("span", { class: "add", text: `+${f.additions}` }), " ", el("span", { class: "del", text: `−${f.deletions}` })),
        ` ${f.path}`, viewedMark(f.path)))));
  } else {
    // The review path's rows (review_path.js); a row for a file with no diff here is not a link
    files.replaceChildren(...listed.map((r) => {
      if (r.kind === "heading") return el("li", { class: "path-heading", text: r.text });
      const i = state.files.findIndex((f) => f.path === r.file);
      // The viewed mark first, in its own column as in the picker; a skipped file has none
      const mark = el("span", { class: "path-mark", text: r.kind !== "skipped" && state.viewed.includes(r.file) ? "✓ " : "  ", title: "Viewed" });
      const text = el("span", { class: "path-row", text: r.text });
      return el("li", {}, i < 0 ? el("span", { class: "empty", title: `${r.file}: no changes in this view` }, mark, text)
        : el("a", { href: `#file-${i}`, title: r.file }, mark, text));
    }));
  }

  $("filter").value = state.filter;
  const list = ordered(state.threads.filter(visible));
  $("threads").replaceChildren(...(list.length ? list.map((t) => {
    const s = stateOf(t);
    const marks = [statusLabel(t, s), t.outdated && "outdated", !t.outdated && t.inView === false && "not in this view"].filter(Boolean).join(" · ");
    return el("li", { class: "thread-item" }, el("a", {
      href: `#thread-${t.id}`, title: (t.comments[0]?.body ?? "").slice(0, 300),
      onclick: (e) => { e.preventDefault(); goTo(t); },
    },
    el("div", {}, el("span", { class: `s-${s}`, text: "● " }), el("span", { class: "where", text: where(t.anchor) })),
    el("div", { class: "gist", text: `${marks} · ${gist(t)}` })));
  }) : [el("li", { class: "empty", text: state.filter === "open" ? "No open threads" : "No threads yet" })]));
}

function renderMain({ under, elsewhere }) {
  const main = $("main");
  const parts = [];

  // Threads with no line here: general, outdated, or with code this view doesn't show
  const others = ordered(elsewhere.filter(visible));
  const general = state.newThread?.general ? newThreadForm() : null;
  parts.push(el("section", { class: "elsewhere" },
    others.length || general ? el("h3", { text: others.length ? "Threads not on a line of this view" : "New general comment" }) : null,
    ...others.map((t) => threadCard(t, false)),
    general ?? el("button", { text: "New general comment", onclick: () => { state.newThread = { general: true }; render(); focusDraft("new"); } })));

  if (!state.files.length) parts.push(el("p", { class: "empty", text: `No changes in ${viewLabel(state.view)}.` }));
  state.files.forEach((f, i) => parts.push(fileBlock(f, i, under)));
  main.replaceChildren(...parts);
}

function fileBlock(f, i, under) {
  const status = f.status === "renamed" || f.status === "copied" ? `${f.status} from ${f.oldPath}` : f.status === "modified" ? "" : f.status;
  const block = el("div", { class: "file", id: `file-${i}` },
    el("h3", {}, el("span", { text: f.path }), el("span", { class: "status", text: status }),
      el("span", { class: "counts" }, el("span", { class: "add", text: `+${f.additions}` }), " ", el("span", { class: "del", text: `−${f.deletions}` })),
      el("label", { class: "viewed-box", title: "Stays checked until the file's diff changes" },
        el("input", { type: "checkbox", checked: state.viewed.includes(f.path),
          onchange: async (e) => {
            const box = e.target;
            // Not taken (another action was sending, or the watcher refused): show what it was
            if (!(await act(() => api("PUT", "/api/viewed", { file: f.path, viewed: box.checked })))) box.checked = !box.checked;
          } }), " Viewed")));
  // The review path's stop for this file, above its diff (not a thread: .review-path-stop)
  const stop = state.path && stopBlock(state.path, f.path, el);
  if (stop) block.append(stop);
  if (f.isBinary || !f.hunks.length) {
    block.append(el("div", { class: "note", text: f.isBinary ? "Binary file" : "No changes to its lines" }));
    return block;
  }

  const t = state.newThread;
  const selected = (side, n) => t && !t.general && t.file === f.path && t.side === side && n >= t.start && n <= t.end;
  const body = el("tbody");
  for (const h of f.hunks) {
    body.append(el("tr", { class: "hunk" }, el("td", { colspan: 3, text: h.header })));
    for (const line of h.lines) {
      const o = line.oldLineNumber, n = line.newLineNumber;
      const sel = (line.type !== "add" && selected("old", o)) || (line.type !== "delete" && selected("new", n));
      const num = (side, v) => (v === null || v === undefined
        ? el("td", { class: "num none" })
        : el("td", { class: "num", text: v, title: "Comment on this line (shift-click: more lines)", onclick: (e) => pick(f, side, v, e.shiftKey) }));
      body.append(el("tr", { class: `${line.type}${sel ? " selected" : ""}` },
        num("old", line.type === "add" ? null : o), num("new", line.type === "delete" ? null : n),
        el("td", { class: "code", text: `${line.type === "add" ? "+" : line.type === "delete" ? "-" : " "}${line.content}` })));
      // Threads, and a new comment, under the line they end on (old side first, then new)
      for (const [side, v] of [["old", line.type === "add" ? null : o], ["new", line.type === "delete" ? null : n]]) {
        if (v === null || v === undefined) continue;
        const here = (under.get(`${f.path}\0${side}\0${v}`) ?? []).filter(visible);
        const form = t && !t.general && t.file === f.path && t.side === side && t.end === v ? newThreadForm() : null;
        if (here.length || form) body.append(el("tr", { class: "below" }, el("td", { colspan: 3 }, ...here.map((x) => threadCard(x, true)), form)));
      }
    }
  }
  block.append(el("table", { class: "diff" }, el("colgroup", {}, el("col", { class: "num" }), el("col", { class: "num" }), el("col")), body));
  return block;
}

// The textarea for <key>: the same element on every render, so the browser keeps its
// undo history and size
function draftBox(key, placeholder, onSend, onCancel) {
  if (state.boxes.has(key)) return state.boxes.get(key);
  const box = el("textarea", {
    "data-draft": key, placeholder, value: state.drafts.get(key) ?? "",
    oninput: (e) => state.drafts.set(key, e.target.value),
    onkeydown: (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); onSend(); }
      else if (e.key === "Escape" && onCancel) { e.preventDefault(); onCancel(); }
    },
  });
  state.boxes.set(key, box);
  return box;
}

function focusDraft(key) {
  const box = document.querySelector(`textarea[data-draft="${CSS.escape(key)}"]`);
  if (box) { box.focus({ preventScroll: true }); box.scrollIntoView({ block: "nearest" }); }
}

function newThreadForm() {
  const t = state.newThread;
  const cancel = () => { state.newThread = null; state.boxes.delete("new"); render(); };
  return el("div", { class: "new-thread" },
    el("div", { class: "title", text: t.general ? "A comment on the changes as a whole" : `Comment on ${where({ file: t.file, side: t.side, startLine: t.start, endLine: t.end })}` }),
    draftBox("new", "Ask the coding agent, or ask for a change…", sendNewThread, cancel),
    el("div", { class: "actions" },
      el("span", { class: "hint", text: `⌘/Ctrl+Enter sends · Esc cancels${state.mode.mode === "batched" ? " · held until you submit" : ""}` }),
      el("button", { text: "Cancel", onclick: cancel }),
      el("button", { class: "primary", text: "Comment", onclick: sendNewThread })));
}

function threadCard(t, placed) {
  const s = stateOf(t);
  const closed = t.status !== "open" && !state.expanded.has(t.id);
  const a = t.anchor;
  const toggle = t.status === "open" ? undefined : () => { state.expanded.has(t.id) ? state.expanded.delete(t.id) : state.expanded.add(t.id); render(); };
  const head = el("div", { class: "head", onclick: toggle, title: toggle && (closed ? "Show the thread" : "Fold the thread") },
    el("span", { class: `badge s-${s}`, text: statusLabel(t, s) }),
    placed ? null : el("span", { class: "where", text: where(a) }),
    t.outdated ? el("span", { class: "badge outdated", text: "outdated", title: "Its code changed after it was written" }) : null,
    !placed && !t.outdated && a && t.inView === false ? el("span", { class: "badge elsewhere", text: "not in this view" }) : null,
    closed ? el("span", { class: "gist", text: gist(t).slice(0, 80) }) : null);
  const card = el("div", { class: `thread${closed ? " closed" : ""}`, id: `thread-${t.id}` }, head);
  if (closed) return card;

  if (t.outdated && a?.code) {
    card.append(el("div", { class: "written", text: `The code it was written on (${a.side === "old" ? "old side, " : ""}line ${lines(a)}):` }),
      el("pre", { class: "code", text: a.code }));
  } else if (!placed && a) {
    const view = shownIn(t);
    card.append(el("div", { class: "written" },
      t.inView === false ? "Its code isn't in this view. " : a.startLine === a.endLine ? `Line ${lines(a)} isn't among this view's changes. ` : `Lines ${lines(a)} aren't among this view's changes. `,
      view === null ? null : el("a", { href: "#", text: `Show it in ${viewLabel(view)}`, onclick: (e) => { e.preventDefault(); goTo(t); } })));
    if (a.code) card.append(el("pre", { class: "code", text: a.code }));
  }
  for (const c of t.comments) {
    const time = new Date(c.time);
    card.append(el("div", { class: `comment k-${c.kind}` },
      el("div", { class: "who" }, el("b", { text: who(c), title: c.author === "reviewer" && c.by ? "Reviewer" : undefined }),
        KIND[c.kind] ? ` · ${KIND[c.kind]}` : "",
        Number.isNaN(time.getTime()) ? "" : ` · ${time.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })}`),
      el("div", { class: "body" }, ...inline(c.body ?? ""))));
  }
  if (t.status === "open") {
    const key = `reply:${t.id}`;
    card.append(el("div", { class: "actions" },
      draftBox(key, "Reply…", () => sendReply(t)),
      el("span", { class: "hint", text: "⌘/Ctrl+Enter sends" }),
      el("button", { text: "Dismiss", title: "Close it without a fix", onclick: () => setStatus(t, "dismissed") }),
      el("button", { text: "Resolve", onclick: () => setStatus(t, "resolved") }),
      el("button", { class: "primary", text: "Reply", onclick: () => sendReply(t) })));
  } else {
    card.append(el("div", { class: "actions" }, el("button", { text: "Reopen", onclick: () => setStatus(t, "open") })));
  }
  return card;
}

// A comment's text with its `code` and **bold** shown as such; everything else stays text
function inline(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(/`([^`\n]+)`|\*\*([^*\n]+)\*\*/g)) {
    out.push(text.slice(last, m.index));
    out.push(m[1] !== undefined ? el("code", { text: m[1] }) : el("strong", { text: m[2] }));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

// ---------- start ----------

function headerHeight() {
  document.documentElement.style.setProperty("--header-h", `${document.querySelector("header").offsetHeight}px`);
}
// The sticky file headers and the sidebar sit under the header, whatever its height
new ResizeObserver(headerHeight).observe(document.querySelector("header"));

$("view").addEventListener("change", (e) => switchView(e.target.value));
document.addEventListener("compositionstart", () => { composing = true; });
document.addEventListener("compositionend", () => { composing = false; if (state.stale) render(); });
document.addEventListener("selectionchange", () => { if (state.stale && !busyReading()) render(); });
$("commit").addEventListener("keydown", async (e) => {
  if (e.key !== "Enter") return;
  const view = e.target.value.trim();
  if (view && (await switchView(view))) e.target.value = "";
});
$("mode").addEventListener("change", (e) => switchMode(e.target.value));
$("agent").addEventListener("change", (e) => switchAgent(e.target.value));
$("submit").addEventListener("click", submitHeld);
$("export").addEventListener("click", exportReview);
$("filter").addEventListener("change", (e) => {
  state.filter = e.target.value;
  save("difftate.filter", state.filter);
  render();
});
poll();
