# difftate

A review loop: a reviewer comments on lines of a changeset, and a coding agent replies in the same thread, with the decisions recorded in the review's commits.

## Language

### Review

**Review**:
The review of one branch in one repository, against its base, like a pull request: its threads, and where each one stands. Commits don't end it, and every view shows the same review.
_Avoid_: session (that word belongs to the coding agent), diff, pull request

**View**:
The part of a review's changes that the reviewer looks at: all of them, one commit, the last few commits, or only the staged or unstaged changes. A thread written in any view belongs to the review. A thread whose code the view doesn't show is listed, but not placed on a line.
_Avoid_: range, filter, review (a view is not a separate review)

**Review history**:
The record of every thread, comment and reply, and every Done mark, from every review on this machine. It is never deleted, and outlives the repositories it came from.
_Avoid_: log, archive

**Outdated**:
A thread whose anchored code changed after the thread was written. It stays in the review, and shows the code it was written on.

**Viewed file**:
A file of the changeset that the reviewer marked as read. It stays viewed in every view, across reloads and commits, until the file's diff changes; then the mark is cleared.
_Avoid_: seen, reviewed, read

**Review mode**:
How a review sends the reviewer's comments to the coding agent: live or batched. Each review has one, live until the reviewer changes it.
_Avoid_: setting, flag

**Live**:
The review mode in which each comment is dispatched as soon as the reviewer writes it.

**Batched**:
The review mode in which comments are held until the reviewer submits the review, like a pending review on a pull request.
_Avoid_: draft, pending

**Submit**:
The reviewer sends a batched review's held threads to the coding agent, as one run. Changing a review from batched to live submits it too.
_Avoid_: publish, send, finish

**Done**:
A reviewer has finished a review at one commit, whether they went through the code or skipped it. A new commit on the branch, or the reviewer undoing it, makes the review not done again. Only a reviewer marks it. Each Done keeps the text of the review path as it was then (none, with no file) in the review and its review history.
_Avoid_: approved (it gates nothing), finished, closed, reviewed

**Thread**:
A conversation about one anchor, or about the changeset as a whole (a general thread).
_Avoid_: comment (a thread holds comments), issue

**Anchor**:
Where a thread is attached: a file, a side, a line range, and the code on those lines when the thread was opened. When only the line numbers of its code change, the anchor moves with it; when the code itself changes, the thread is outdated.
_Avoid_: location, position, follow (that is what the Watcher does with the branch)

**Side**:
The version of a file that an anchor points into: old (before the change) or new (after it).

**Reviewer**:
Whoever writes comments that the coding agent must answer: the user, or a separate reviewing agent. It is the role the rules check.
_Avoid_: user (as a role)

**Reviewer name**:
Which reviewer wrote a comment or changed a thread status, such as `security-bot`: the name the reviewer gives, or the user's git name when they give none. A comment written before reviewer names has none.
_Avoid_: author (that is the role: reviewer, coding agent or difftate), user name

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
Where an open thread stands in the loop: **held** (it has a reviewer's comment that waits for the reviewer to submit a batched review), **waiting** (it has a reviewer's comment that no run has been sent yet), **queued** (waiting while a run handles other threads), **working** (a run has it), **replied** (the coding agent spoke last) or **failed** (its run ended with no reply to it).
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
The one difftate process on a machine. For each checked-out folder it is asked about (a repository itself, or one of its worktrees), it opens the review of the branch checked out there, watches its threads, and dispatches runs in that folder. It follows each folder's branch: between runs, it moves to that branch's review.
_Avoid_: server, daemon, watcher of a folder

### Coding agent

**Coding agent**:
The agent that replies to threads and changes the code, such as Claude Code or OpenCode: in a run, or in an agent session the reviewer started with an export. It need not be the agent that wrote the code: it learns the decisions behind the code from the review's commit messages.
_Avoid_: agent (alone: a reviewing agent is an agent too), implementer, tool, bot, AI, model

**Agent list**:
The machine's list of coding agents that can reply, in `agents.toml` in the difftate folder: each a name, the coding agent (Claude Code or OpenCode), the command with the environment it needs, and an optional model, plus the default. The repository's agent (`difftate agent <name>`, in its git config) is one of them; a run uses the review's agent override, else the repository's, else the default, as they are when it starts.
_Avoid_: agents file, config (alone)

**Agent override**:
The agent from the agent list a reviewer chose for one review, from any viewer; they can clear it. It is a review event, kept in the review and its review history like the review mode, and only a reviewer sets it. A run in flight keeps its agent: the next run uses the override.
_Avoid_: agent setting (that is the repository's), account switch

**Agent session**:
The coding agent's conversation: during one run, which it starts fresh with the review's threads and commit messages and ends with; or one the reviewer runs, given an export.
_Avoid_: session (alone), conversation

**Export**:
A copy of a review for an agent session that the reviewer starts: its commit messages, every thread in full with its thread status and thread state, which threads need an answer (open ones no reply answers yet), and how to reply. It says nothing about what to do: the reviewer says that in the session. Exporting changes no thread.
_Avoid_: handoff, dump, snapshot

### Review path

**Review path**:
The coding agent's reading order for a review's changed files: a tree of stops, each with questions and answers, in `review-path.md` at the worktree root. The coding agent writes it; a viewer follows it.
_Avoid_: tour, walkthrough, guide

**Stop**:
A numbered file on the review path, with its questions and optional line ranges. The numbers are the reading order.
_Avoid_: step (that is one action in a run), node

**Key stop**:
A stop marked ★: one that matters most, where the reviewer should slow down.
_Avoid_: important, starred

**Side file**:
A file read together with its stop. It has no number of its own.
_Avoid_: child, sub-stop

**Question**:
One question on a stop, with its answer. A stop's text is its questions; the word *note* stays difftate's own message in a thread.
_Avoid_: note, summary, description

**Spec**:
A test the coding agent names under a stop (`Spec: file "test name"`) because it shows the stop's behaviour. The preview lists it; difftate does not run or open it.
_Avoid_: test case

**Path section**:
Named text after the stops (such as "State flow") that a stop can point to by name.
_Avoid_: appendix

**Skipped file**:
A changed file the review path names as not worth reading, with a reason (such as "lockfile only" or "generated"). It is on the path, listed after the stops.
_Avoid_: ignored, excluded (and not the same as skipping a whole review, which Done allows)

**Not on the path**:
The changed files the review path does not name, listed after the last stop.
_Avoid_: uncovered, missing

### Viewing

**Viewer**:
Where the reviewer reads a review and writes comments: the browser or the Neovim viewer. A viewer never starts the watcher.
_Avoid_: UI, frontend, client

**Neovim viewer**:
The viewer inside the reviewer's own Neovim: the review's threads shown on the real files, which the reviewer reads, edits and moves through with their own editor.
_Avoid_: Review tab (a tab is the board's idea, not difftate's: difftate opens no host), nvim plugin
