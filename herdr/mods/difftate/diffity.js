// A small client for a running diffity server (the one `difftate` / `dto` starts).
// Threads written here are the same threads the difftate watcher dispatches to the agent.

import { readTextFile, home } from "herdr";

export const AUTHOR = { name: "You", type: "user" };

async function json(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(`${options?.method ?? "GET"} ${url}: ${r.status} ${await r.text()}`);
  return r.json();
}

// The newest live diffity instance for this repo root, or null.
export async function findInstance(root) {
  const raw = await readTextFile(`${home()}/.diffity/registry.json`).catch(() => null);
  let list = [];
  try { list = JSON.parse(raw ?? "[]"); } catch { list = []; }
  const mine = list.filter((e) => e.repoRoot === root).sort((a, b) => String(b.startedAt).localeCompare(String(a.startedAt)));
  for (const e of mine) {
    try {
      const info = await json(`http://localhost:${e.port}/api/info`);
      let sessionId = info.sessionId;
      if (!sessionId) sessionId = (await json(`http://localhost:${e.port}/api/sessions/current`).catch(() => null))?.id ?? null;
      return { port: e.port, ref: e.ref, description: info.description ?? e.description, sessionId };
    } catch { /* stale entry: try the next */ }
  }
  return null;
}

export class Diffity {
  constructor(inst) {
    this.port = inst.port;
    this.sessionId = inst.sessionId;
    this.base = `http://localhost:${inst.port}`;
  }
  diff() { return json(`${this.base}/api/diff`); }
  async fingerprint() { return (await json(`${this.base}/api/diff-fingerprint`)).fingerprint; }
  threads() { return json(`${this.base}/api/threads?session=${encodeURIComponent(this.sessionId)}`); }
  createThread({ filePath, side, startLine, endLine, body, anchorContent }) {
    return json(`${this.base}/api/threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: this.sessionId, filePath, side, startLine, endLine, body, author: AUTHOR, anchorContent }),
    });
  }
  reply(threadId, body) {
    return json(`${this.base}/api/threads/${threadId}/reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body, author: AUTHOR }),
    });
  }
  setStatus(threadId, status) {
    return json(`${this.base}/api/threads/${threadId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
  }
}

// Where a thread stands in the difftate loop, from its last comment.
export function threadState(th) {
  if (th.status !== "open") return th.status; // resolved / dismissed
  const last = th.comments.at(-1)?.body ?? "";
  if (last.startsWith("[dt-reply]")) return "replied";
  if (last.startsWith("[dt-status]")) return /✅|❌/.test(last.split("\n")[0]) ? "replied" : "working";
  if (last.startsWith("[dt-queued]")) return "queued";
  return "waiting";
}
