// Layout D's views (GLOSSARY.md, View): what the view picker offers, and how the page names a
// view. DOM-free: draw_views.js draws it.

// The views the picker offers. Any other is typed in the commit box
const OFFERED = [
  ["", "All changes"], ["HEAD", "Uncommitted"], ["staged", "Staged"], ["unstaged", "Unstaged"],
  ["HEAD~1", "Last commit"], ["HEAD~2", "Last 2 commits"], ["HEAD~3", "Last 3 commits"],
];

/** How a sentence names the view <v>. */
export const viewLabel = (v) => (!v ? "all changes" : v === "HEAD" ? "uncommitted changes"
  : v === "staged" || v === "unstaged" ? `${v} changes` : `the commits after ${v}`);

/** The view picker of the page <state>, which has a poll's answers: {text (the view shown, on
 *  its button), choices: [{view, text, current}]}. */
export function viewPicker(state) {
  const shown = state.server.changeset.view ?? "";
  const offered = OFFERED.some(([view]) => view === shown) ? OFFERED : [...OFFERED, [shown, `Commits after ${shown}`]];
  const choices = offered.map(([view, text]) => ({ view, text, current: view === shown }));
  return { text: choices.find((c) => c.current).text, choices };
}
