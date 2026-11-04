// A client for difftate's review API, served by the running watcher (`difftate`, `dtc`, `dto`).
// The watcher writes where it runs to <git common dir>/difftate/api.json ({port, pid, root})
// and its token to <git common dir>/difftate/token. See lib/difftate/api.py for the API.

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
  try { api.review = await api.call("GET", "/api/review"); } catch { return null; } // a stale file: no watcher there
  return api;
}

// A thread from the API, flattened for the view: file, side and lines from its anchor
// (file null for a general thread), the API's thread state, and its comments as they are.
function viewThread(t) {
  const a = t.anchor;
  return {
    id: t.id, filePath: a?.file ?? null, side: a?.side ?? "new", startLine: a?.startLine ?? 0, endLine: a?.endLine ?? 0,
    status: t.status, state: t.state, outdated: !!t.outdated, comments: t.comments ?? [],
  };
}

export class ReviewApi {
  constructor(port, token) {
    this.port = port;
    this.token = token;
    this.base = `http://127.0.0.1:${port}`;
    this.review = null;
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

  // {base, commit, diff (the unified diff text), files (parsed)}
  async changeset() {
    const c = await this.call("GET", "/api/changeset");
    return { ...c, files: parseDiff(c.diff) };
  }

  async threads() { return (await this.call("GET", "/api/threads")).map(viewThread); }

  async openThread({ filePath, side, startLine, endLine, code }, body) {
    return viewThread(await this.call("POST", "/api/threads", { anchor: { file: filePath, side, startLine, endLine, code }, body }));
  }

  comment(threadId, body) { return this.call("POST", `/api/threads/${encodeURIComponent(threadId)}/comments`, { kind: "comment", body }); }

  setStatus(threadId, status) { return this.call("PATCH", `/api/threads/${encodeURIComponent(threadId)}/status`, { status }); }
}
