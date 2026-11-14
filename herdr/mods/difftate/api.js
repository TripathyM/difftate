// A client for difftate's review API, served by the running watcher (`difftate`, `dtc`, `dto`).
// The watcher writes where it runs to <git common dir>/difftate/api.json ({port, pid, root})
// and its token to <git common dir>/difftate/token. See lib/difftate/adapters/inbound/review_api/server.py for the API.

import { exec, readTextFile } from "herdr";
import { parseDiff } from "./diff.js";

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// The review API for the repository at <root>, or null when no watcher serves it.
export async function findApi(root) {
  const r = await exec("git", ["rev-parse", "--git-common-dir"], { cwd: root }).catch(() => null);
  if (!r || r.code !== 0) return null;
  const common = r.stdout.trim();
  const folder = `${common.startsWith("/") ? common : `${root}/${common}`}/difftate`;
  let info, token;
  try {
    info = JSON.parse(await readTextFile(`${folder}/api.json`));
    token = (await readTextFile(`${folder}/token`)).trim();
  } catch { return null; }
  if (!info?.port || !token) return null;
  const api = new ReviewApi(info.port, token);
  try { await api.call("GET", "/api/review"); } catch { return null; } // a stale file: no watcher there
  return api;
}

// A thread from the API, flattened for the view: file, side, lines (where its code is in the view
// asked for) and the code it was written on from its anchor (file null for a general thread),
// whether its code is in that view and the view it was written in, the API's thread state, and its comments as they are.
function viewThread(t) {
  const a = t.anchor;
  return {
    id: t.id, filePath: a?.file ?? null, side: a?.side ?? "new", startLine: a?.startLine ?? 0, endLine: a?.endLine ?? 0, code: a?.code ?? null, writtenIn: a?.view ?? "",
    inView: t.inView !== false, status: t.status, state: t.state, outdated: !!t.outdated, comments: t.comments ?? [],
  };
}

export class ReviewApi {
  constructor(port, token) {
    this.port = port;
    this.token = token;
    this.base = `http://127.0.0.1:${port}`;
  }

  async call(method, path, payload) {
    const options = { method, headers: { Authorization: `Bearer ${this.token}` } };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const r = await fetch(`${this.base}${path}`, options);
    const text = await r.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = null; }
    if (!r.ok) throw new ApiError(r.status, body?.error ?? `${method} ${path}: ${r.status}`);
    return body;
  }

  // The changeset in the view viewers show: {view, base, commit, diff (the unified diff text), files (parsed)}.
  // Each file has the versions of its two sides, {old, new} (null from a watcher that doesn't name them)
  async changeset() {
    const c = await this.call("GET", "/api/changeset");
    return { ...c, view: c.view ?? "", files: parseDiff(c.diff).map((f) => ({ ...f, versions: c.versions?.[f.path] ?? null })) };
  }

  // Show another view in every viewer: "" (all changes), a commit (the commits after it), HEAD, staged or unstaged
  setView(view) { return this.call("PUT", "/api/view", { view }); }

  async threads(view = "") { return (await this.call("GET", `/api/threads?view=${encodeURIComponent(view)}`)).map(viewThread); }

  // <version>: the version of the file shown (a file's versions), so a thread on code that moved since moves with it
  async openThread({ filePath, side, startLine, endLine, code, version }, body, view = "") {
    return viewThread(await this.call("POST", "/api/threads", { anchor: { file: filePath, side, startLine, endLine, code, version: version ?? undefined }, body, view }));
  }

  comment(threadId, body) { return this.call("POST", `/api/threads/${encodeURIComponent(threadId)}/comments`, { kind: "comment", body }); }

  // The files the reviewer marked viewed (until their diff changes), as a Set of paths
  async viewed() { return new Set((await this.call("GET", "/api/viewed")).files); }

  async setViewed(file, viewed) { return new Set((await this.call("PUT", "/api/viewed", { file, viewed })).files); }

  setStatus(threadId, status) { return this.call("PATCH", `/api/threads/${encodeURIComponent(threadId)}/status`, { status }); }
}
