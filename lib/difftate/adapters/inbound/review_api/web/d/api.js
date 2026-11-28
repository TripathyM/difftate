// Layout D's calls to the review API. The page never sees the API token: the launch link got it
// a cookie, which its calls send with the page's header. DOM-free: it is given fetch.

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

/** api(method, path, payload) about the checked-out <folder> (the link that opened the page names
 *  it): the answer's JSON, or an ApiError. */
export function reviewApi(fetch, folder) {
  return async (method, path, payload) => {
    const options = { method, headers: { "X-Difftate": "page" }, credentials: "same-origin" };
    if (payload !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(payload);
    }
    const r = await fetch(`${path}${path.includes("?") ? "&" : "?"}folder=${encodeURIComponent(folder)}`, options);
    const text = await r.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = null; }
    if (!r.ok) throw new ApiError(r.status, body?.error ?? `${method} ${path}: ${r.status}`);
    return body;
  };
}

/** What to tell the reviewer when a call failed with <error>. */
export function problemText(error) {
  if (!(error instanceof ApiError)) return "Can't reach the watcher: is difftate still running in this repository?";
  return error.status === 401 ? "This page's watcher has stopped. Open the link a running difftate prints." : error.message;
}
