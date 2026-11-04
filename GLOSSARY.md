# difftate

A review loop: a reviewer comments on lines of a changeset, and the coding agent that wrote the code replies in the same thread, with the context of the agent session where it wrote that code.

## Language

### Review

**Review**:
The review of one branch in one repository, against its base, like a pull request: its threads, and where each one stands. Commits don't end it, and every view shows the same review.
_Avoid_: session (that word belongs to the coding agent), diff, pull request

**View**:
The part of a review's changes that the reviewer looks at: all of them, one commit, the last few commits, or only the staged or unstaged changes. A thread written in any view belongs to the review.
_Avoid_: range, filter, review (a view is not a separate review)

**Review history**:
The record of every thread, comment and reply from every review on this machine. It is never deleted, and outlives the repositories it came from.
_Avoid_: log, archive

**Outdated**:
A thread whose anchored code changed after the thread was written. It stays in the review, and shows the code it was written on.

**Viewed file**:
A file of the changeset that the reviewer marked as read. It stays viewed in every view, across reloads and commits, until the file's diff changes; then the mark is cleared.
_Avoid_: seen, reviewed, read

**Thread**:
A conversation about one anchor, or about the changeset as a whole (a general thread).
_Avoid_: comment (a thread holds comments), issue

**Anchor**:
Where a thread is attached: a file, a side, a line range, and the code on those lines when the thread was opened.
_Avoid_: location, position

**Side**:
The version of a file that an anchor points into: old (before the change) or new (after it).

**Reviewer**:
Whoever writes comments that the coding agent must answer: the user, or a separate reviewing agent.
_Avoid_: user (as a role)

**Comment**:
A reviewer's message in a thread.
_Avoid_: reply (that is the coding agent's), message

**Reply**:
The coding agent's answer in a thread.
_Avoid_: response, comment

**Note**:
A message that difftate itself writes in a thread to show progress: a queued note or a progress note. A note never answers anything.
_Avoid_: status comment, system comment

**Thread status**:
Open, resolved or dismissed. Only a reviewer changes it.
_Avoid_: state (that is where the thread stands in the loop)

**Thread state**:
Where an open thread stands in the loop: **waiting** (it has a reviewer's comment that no run has been sent yet), **queued** (waiting while a run handles other threads), **working** (a run has it), **replied** (the coding agent spoke last) or **failed** (its run ended with no reply to it).
_Avoid_: pending, status

### Changes

**Base**:
The branch a review compares against, such as `main`.
_Avoid_: ref, target

**Changeset**:
The changes from the base to the files on disk.
_Avoid_: patch, diff (fine in speech; the model's word is changeset)

### Dispatch

**Dispatch**:
Sending the waiting threads to the coding agent, as one run.

**Run**:
One time the coding agent works on a set of threads. It ends replied or failed.
_Avoid_: job, call

**Step**:
One action the coding agent takes during a run, such as reading a file or running a command.
_Avoid_: tool, tool call

**Queued note**:
The note on a thread that became waiting while a run was busy with other threads.

**Progress note**:
The note a run keeps on each of its threads: its steps while it works, then one line that says it finished or failed.
_Avoid_: status comment, checklist

**Watcher**:
The difftate process for one review: it opens the review, watches its threads, and dispatches runs until it is stopped.

### Coding agent

**Coding agent**:
The agent that wrote the code and replies to threads, such as Claude Code or OpenCode.
_Avoid_: agent (alone: a reviewing agent is an agent too), tool, bot, AI, model

**Agent session**:
The coding agent's conversation that each run continues, so replies have the context in which the code was written.
_Avoid_: session (alone), conversation

**Headless**:
Runs with no agent session: the coding agent starts each run with no earlier context.

### Viewing

**Viewer**:
Where the reviewer reads a review and writes comments, such as the browser or a Review tab.
_Avoid_: UI, frontend, client

**Review tab**:
The viewer inside the Herdr app: a code-editor tab for one repository's review.
