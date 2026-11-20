// The Review tab's Export action: what it says after copying the review's export to the clipboard.
// Plain JavaScript, no Herdr, so tests/test_review_tab_exported.py runs it in node. Wording matches
// the browser viewer's. <text> is what GET /api/export answers (text/plain).

// Said after the export is on the clipboard
export const exportedMessage = () => "Export copied: paste it into an agent session";

// Said when the export could not be fetched or copied; <error> is what went wrong
export const exportFailedMessage = (error) => `Could not export: ${error?.message ?? error}`;

// What the export is worth copying: an empty answer (an old watcher, or a proxy) is not an export
export const exportProblem = (text) => (typeof text === "string" && text.trim() ? null : "The watcher gave no export (is it up to date?)");
