// Layout D's two tabs: which one a review opens on, and what needs the reviewer. DOM-free.

/** How many of <threads> need the reviewer: the open ones that are replied or failed. */
export const needingYou = (threads) => threads.filter(needsYou).length;
export const needsYou = (t) => t.status === "open" && (t.state === "replied" || t.state === "failed");

/** The tab a review opens on, and why: {tab: "conversation"|"files", why}. <address>: the tab
 *  the page's address names, or null; it wins, with nothing to say. */
export function firstTab(address, threads) {
  if (address) return { tab: address, why: "" };
  const waiting = needingYou(threads);
  if (!waiting) return { tab: "files", why: "Opened on Files changed: no open thread is replied or failed." };
  const who = waiting === 1 ? "1 thread needs" : `${waiting} threads need`;
  return { tab: "conversation", why: `Opened on Conversation: ${who} you (replied or failed).` };
}

/** The tab that an address's query <search> names, or null. */
export function tabIn(search) {
  const named = new URLSearchParams(search).get("tab");
  return named === "conversation" || named === "files" ? named : null;
}

/** The address <href> naming <tab>, so that a reload shows it. */
export function addressWithTab(href, tab) {
  const address = new URL(href);
  address.searchParams.set("tab", tab);
  return address.href;
}
