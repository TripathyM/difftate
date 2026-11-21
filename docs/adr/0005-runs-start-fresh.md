---
status: accepted
---

# Runs start fresh: context comes from commits and threads, not the agent session that wrote the code

difftate used to continue the agent session that wrote the code, found as the newest session where the watcher started. That breaks when an orchestrator starts implementers: they may be launched from another folder (a home repository, with `--add-dir` to the worktree), several of them commit to one branch, and they may be Claude Code or OpenCode. So every run starts a fresh agent session, of whichever coding agent the watcher was started with, and gets the context in its prompt instead: the whole review's commit log (`git log <base>..<branch>`, whatever the view) and every thread in full, open, resolved and dismissed. The decisions behind the code live in commit bodies, which implementers write by a user-level rule and a review gate checks; difftate does not enforce them. Any coding agent can then answer any branch, wherever and by whomever it was written, and difftate has no session to find.

## Considered options

- **Find the implementer's session** by folder, by repository and branch (Claude records `gitBranch`), or by which session edited the changeset's files. Each one guesses: the launch folder may not be the worktree, a reviewing agent in the same folder looks like the implementer, and OpenCode records no branch.
- **Exported transcripts**, saved by the orchestrator before it closes a worker and filed by branch. It keeps more context, but it adds a step to every factory and a store to difftate.
- **Committed work only**: drop the uncommitted views so every change has a commit message, with runs committing their fixes. It costs the `HEAD`, `staged` and `unstaged` views, and a run's commit on the base branch would end its own review (ADR 0002).
- **One fresh session per review, continued by later runs.** It remembers earlier runs, but difftate would have to keep and recover it, and it grows with every run.

## Consequences

- `--session`, `--no-session` and the session lookup in `difftate.zsh` go. `dtc`, `dto` and wrappers such as `--cmd ccp` stay: they pick the coding agent and account, not a session.
- A "why?" thread on uncommitted changes is answered from the code alone, and an earlier run's reasoning survives only in its replies.
- One watcher runs per checked-out folder, not per repository, so each worktree can have its own review open. (Superseded 2026-11-21 by ADR 0008: one watcher serves every checked-out folder on the machine, and each folder still has its own review.)
