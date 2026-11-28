// What layout D shows: the model of the whole page, from the page state. DOM-free: main.js has it
// drawn. It is never blank: until a poll answered, and for a tab it doesn't have, there is still
// something to show.

import { waitingText, warningsShown } from "./banners.js";
import { conversation } from "./conversation.js";
import { asShown, filesChanged } from "./files_changed.js";
import { settingsModel } from "./settings.js";
import { liveConfirm, reviewModes, submitReviewControl } from "./submit.js";
import { needingYou } from "./tabs.js";
import { viewLabel } from "./views.js";
import { vimModel } from "./vim.js";

const counted = (n, what) => `${n} ${what}${n === 1 ? "" : "s"}`;
// What is still going on, which a reviewer sees beside Done: marking it gates nothing
const stillOpen = ({ openThreads, runsInFlight }) => [
  openThreads ? `${counted(openThreads, "thread")} still open` : "",
  runsInFlight ? `${counted(runsInFlight, "run")} still working` : "",
].filter(Boolean).join(" · ");

// Done is a state of the review, not an approval (GLOSSARY.md, Done)
function header(state) {
  const { review, done } = state.server;
  const doneButton = done.done
    ? { text: "Undo Done", mark: false, title: "Put the review back in review" }
    : { text: "Mark as Done", mark: true, title: "Mark the review Done at the commit its branch is at. It gates nothing, and a new commit makes it not done again" };
  return { branch: review.branch, base: review.base, state: done.done ? "Done" : "In review", done: done.done, doneButton, stillOpen: stillOpen(done), modes: reviewModes(state), submit: submitReviewControl(state) };
}

const title = ({ review, changeset }) => `difftate · ${review.branch}${changeset.view ? ` · ${viewLabel(changeset.view)}` : ""}`;

function tabs({ server }, shown, files) {
  const waiting = needingYou(server.threads);
  return [
    { id: "conversation", text: "Conversation", count: server.threads.length, needs: waiting ? `${waiting} need${waiting === 1 ? "s" : ""} you` : "" },
    { id: "files", text: "Files changed", count: files.files.length, needs: "" },
  ].map((t) => ({ ...t, current: t.id === shown }));
}

/** {title, settings (settings.js), confirm (submit.js's liveConfirm), problem, notice (what the reviewer's last change did, or ""),
 *  waiting (what the waitingForRun banner says, or ""), warnings: [{id, text}] (banners.js),
 *  header: null | {branch, base, state, done, doneButton: {text, mark (what it makes done), title},
 *  stillOpen (the open threads and running runs, or ""), modes, submit (submit.js)}, tab (the one shown, null before
 *  the first answers), why (it opened, or ""), tabs: [{id, text, count, current, needs (that the
 *  tab needs the reviewer, or "")}], body: {kind: "loading", text} | the Conversation tab | the
 *  Files changed tab (files_changed.js), vim: what the Vim keys show (vim.js)}. */
export function pageModel(state) {
  const { server } = state;
  const problem = state.problem || state.refused;
  const settings = settingsModel(state);
  const vim = vimModel(state);
  if (!server) return { vim, title: "difftate", settings, confirm: null, problem, notice: "", waiting: "", warnings: [], header: null, tab: null, why: "", tabs: [], body: { kind: "loading", text: "Loading the review…" } };
  const files = filesChanged(state);
  const body = state.own.tab === "conversation" ? conversation(state, files.files) : asShown(files, state);
  return {
    vim, title: title(server), settings, problem, notice: state.own.notice, header: header(state),
    confirm: liveConfirm(state),
    waiting: waitingText(server.review), warnings: warningsShown(server.review, state.own.dismissed),
    tab: body.kind, why: state.own.why, tabs: tabs(state, body.kind, files), body,
  };
}
