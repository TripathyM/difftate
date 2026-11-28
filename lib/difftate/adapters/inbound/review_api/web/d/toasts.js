// Layout D's toasts: what the page tells the reviewer, in the one place pinned in the window.
// DOM-free: draw_toasts.js draws them.

const toast = (id, kind, text) => ({ id, kind, text });

/** The toasts to show, [{id, kind: "info" | "error", text}]. An error is shown until it is
 *  closed: a refusal on its own tab, and why the polls fail on any. */
export function toastsOf({ problem, problemClosed, refused, refusedOn, own }) {
  const here = refusedOn === own.tab ? refused : "";
  return [
    toast("why", "info", own.why), toast("notice", "info", own.notice),
    toast("refused", "error", here),
    // A change refused as the polls are says it once
    toast("problem", "error", problemClosed || problem === here ? "" : problem),
  ].filter((t) => t.text);
}

// How long an info toast is shown
const INFO_MS = 8000;

/** Gives the info toasts their time: a function to call with the toasts shown (toastsOf()) as
 *  the page is drawn, which calls expire(id) when one's time is up. <timers>: {set(does, ms),
 *  clear(timer)}. */
export function toastTimes(timers, expire) {
  const running = new Map(); // id -> {text, timer}
  return (toasts) => {
    const timed = new Map(toasts.filter((t) => t.kind === "info").map((t) => [t.id, t.text]));
    for (const [id, had] of running) {
      if (timed.get(id) === had.text) continue;
      timers.clear(had.timer);
      running.delete(id);
    }
    for (const [id, text] of timed) {
      if (!running.has(id)) running.set(id, { text, timer: timers.set(() => expire(id), INFO_MS) });
    }
  };
}
