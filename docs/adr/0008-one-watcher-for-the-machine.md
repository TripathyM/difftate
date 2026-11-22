---
status: accepted
---

# One watcher for the machine

A watcher ran in each checked-out folder, in a terminal of its own, because difftate once continued the agent session that wrote the code there. Since runs start fresh (ADR 0005) and reviews happen in the reviewer's editor (ADR 0007), that terminal only showed a banner and a link. So one watcher now serves every review on the machine. It runs in the background on one port with one token, and each request names the checked-out folder it is about. It serves a folder from the first request that names it, and serves its folders again after a restart. A run still works in the folder where the review's branch is checked out now. If no folder has the branch, the run waits. Only the `difftate` command starts the watcher, and it runs until `difftate stop`. Viewers only read and write reviews: they never start it.

Decided while grilling #146 (2026-11-21).

## Considered options

- **A watcher for each folder, started by the Neovim viewer** (#146 as first written), stopped when that Neovim quits. That ties a process's life to one viewer, when viewers are only clients of the review API. And it leaves open what happens to a run in flight when Neovim quits, and to a second Neovim on the same folder.
- **One process with a port and a token for each folder**, written where each watcher wrote them. No client would have changed, but there are as many ports and tokens as folders. One port is cleaner, and the clients change once.
- **A worktree that difftate makes for each run.** A run could always start, but its edits would not be in the reviewer's folder, it could not see uncommitted changes, and difftate would own git state.
- **Stopping when idle.** Nothing would be left running, but an exported agent session (ADR 0006) asks nothing until it replies, so the watcher could stop under it. One process costs little.
- **Starting at login (launchd).** Always there, but harder to see and to restart while difftate changes often.
- **A token for each folder on one port.** A leaked token would reach one review only, but every file the token protects is already readable only by the user.

## Consequences

- The coding agent and account come from a setting on each repository, with a machine default, from one list of agents on the machine. A review can override it from any viewer, and each run uses the one chosen when it starts. So `dtc`, `dto` and wrappers such as `dtcp` go, replaced by `difftate agent <name>`.
- `difftate [view] [--base <branch>] [--open <viewer>]` starts the watcher if necessary, opens the current folder's review, and ends. `difftate stop`, `restart`, `log` and `browser` manage it. The base is the default branch unless the client names another.
- The watcher's messages go to a log file (`difftate log`). A warning about a review also shows in that review's viewers.
- Runs may not read the one token, as they may not read the folder tokens now.
- The Herdr viewer is deleted, not changed to find the one watcher (amends ADR 0007). `--open` takes `browser`, `nvim` or `both`.
- The review board's `o` runs `difftate --base <base> --open nvim` in the review's folder. It no longer starts a watcher in a tab of its own or checks the watcher's base. (Amended 2026-11-22 by ADR 0009: the board opens the Review tab itself, in a Reviews space, and the tab runs that command.)
- This replaces ADR 0005's consequence of one watcher for each checked-out folder.
