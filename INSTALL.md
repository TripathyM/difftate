# Installing difftate

This file is written so a coding agent (Claude Code, OpenCode, …) can follow it step by step. A human can follow it by hand too.

To install with an agent, paste this into it:

```
Install difftate by following https://raw.githubusercontent.com/TripathyM/difftate/main/INSTALL.md
```

## Rules for the agent

- Run each check before acting. If a step is already done, say so and skip it. Running this file twice must change nothing.
- Ask the user only the questions in [Questions](#questions). Use the defaults for everything else.
- Before editing `~/.zshrc`: back it up, show the exact lines you will add, and wait for the user's yes.
- Never use `sudo`. Never read or edit Claude or OpenCode settings files (`~/.claude*/settings.json` etc.).
- If a step fails, stop, show the error, and suggest the fix listed here. If no fix is listed, ask the user. Don't improvise workarounds.
- Don't start `difftate` itself: it launches the watcher, which runs the agent. The user does that.

## 1. Check requirements

Run each check. Report all results together, then stop if anything **required** is missing.

| Need | Check | If missing |
|---|---|---|
| git (required) | `git --version` | macOS: `xcode-select --install` |
| latest python3 (required, for the watcher and the `difftate` program) | `python3 --version`, and `command -v python3` should be Homebrew's (`/opt/homebrew/bin/python3`) | macOS: `brew install python`. The built-in `/usr/bin/python3` (Command Line Tools, 3.9) is no longer supported |
| An agent CLI (one is required) | `command -v claude` and `command -v opencode`, run separately (in `zsh -ic '…'` if your shell's config sets up the `PATH`) | Install [Claude Code](https://docs.claude.com/en/docs/claude-code) or [OpenCode](https://opencode.ai) |

The agent CLI check passes when at least one of the two prints a path to a real program, not an alias or function.

Tell the user which agent will reply: `claude` unless they list others in the agent list (section 4).

## 2. Clone the repo

Use the folder from question 1 (default `~/difftate`). Call it `DT_HOME` below, and write it with `~` when it is under the home folder (e.g. `~/difftate`).

1. If `DT_HOME/bin/difftate` already exists and `git -C DT_HOME remote get-url origin` points at `TripathyM/difftate`: run `git -C DT_HOME pull --ff-only` and go to section 3.
2. If `DT_HOME` exists but is something else: stop and ask for another folder.
3. Otherwise: `git clone https://github.com/TripathyM/difftate.git DT_HOME`

## 3. Put difftate on the `PATH`

`difftate`, `dt-export` and `dt-reply` are programs in `DT_HOME/bin`, so the shell, scripts and the review board all run them. Build one block of lines to add to `~/.zshrc`, back up once, confirm once.

1. If `~/.zshrc` doesn't exist, create it empty (`touch ~/.zshrc`) and skip the backup in step 4.
2. Check for an existing install: `grep -n '^[^#]*difftate' ~/.zshrc` (ignores commented-out lines).
   - It finds a `PATH` line for `DT_HOME/bin` (as `~/…`, `$HOME/…` or the full path): leave it out of the block.
   - It finds a `source …/difftate.zsh` line from an earlier install: tell the user that `difftate.zsh` and its `difftate`, `dtc` and `dto` functions are gone, and that it must be replaced by the `PATH` line below. Show the line, and ask whether to replace it. Don't leave both.
   - It finds nothing: the block starts with:

     ```zsh
     # difftate: review agent diffs (https://github.com/TripathyM/difftate)
     export PATH="DT_HOME/bin:$PATH"
     ```

3. If the block is empty, skip to step 4. Otherwise back up: `cp ~/.zshrc ~/.zshrc.bak-difftate-$(date +%Y%m%d%H%M%S)` and tell the user the backup path.
4. Show the user the full block, with `DT_HOME` filled in, and wait for a yes.
5. Append the block to the end of `~/.zshrc`.

Which coding agent and account reply is not a shell function or a `difftate` option: it is the agent list (section 4). Don't add shell functions for it.

## 4. The agent list (optional)

Without a list, `claude` replies. To choose agents, write `~/.difftate/agents.toml` (`$DIFFTATE_HOME/agents.toml`): ask which coding agents and accounts they use, then write one `[agents.<name>]` table for each (`tool` = `claude` or `opencode`, `cmd` = the command or shell alias, `env` = what it needs, such as `{ CLAUDE_CONFIG_DIR = "~/.claude-personal" }`, optional `model`) and a `default`. A personal and a work account:

```toml
default = "personal"

[agents.personal]
tool = "claude"
cmd = "ccp"
env = { CLAUDE_CONFIG_DIR = "~/.claude-personal" }

[agents.work]
tool = "claude"
cmd = "ccw"
```

Then, in each repository, `difftate agent <name>` says which of them replies there (for its worktrees too); the default replies in a repository with none. The file is read for each run: no restart.

## 5. The review path skill (optional)

The skill `write-review-path` tells a coding agent how to write `review-path.md`, the reading order that difftate's viewers follow. It needs no difftate to run. To let every agent session on this machine use it, link it into the agent's skills folder. For each agent the user has (Claude Code: `~/.claude/skills`; OpenCode: `~/.config/opencode/skills`):

1. If `<skills folder>/write-review-path` exists, say so and skip.
2. Otherwise: `mkdir -p <skills folder> && ln -s DT_HOME/skills/write-review-path <skills folder>/write-review-path`

Inside a difftate checkout, `bin/setup` links the skill already.

## 6. Verify

1. `zsh -ic 'command -v difftate dt-export dt-reply'`: each prints a path under `DT_HOME/bin`.
2. `zsh -ic 'difftate --help | head -1'` prints a line starting with `difftate`.

Report what passed. Then show the user the quick guide below, as written.

## Quick guide (show after install)

First, open a new terminal (or run `source ~/.zshrc`). Then `cd` into a git repo, on the branch you want reviewed.

| To review | Run |
|---|---|
| The whole branch, against the default branch (`origin/HEAD`) | `difftate` |
| The whole branch, against main | `difftate main` |
| The last commit | `difftate HEAD~1` |
| The last 3 commits (any number) | `difftate HEAD~3` |
| Only uncommitted changes (staged, unstaged, new files) | `difftate HEAD` |
| Only unstaged changes | `difftate unstaged` |
| Only staged changes | `difftate staged` |
| Stop the watcher | `difftate stop` |

- `difftate` starts one watcher for the whole machine, in the background, the first time; later runs (in this folder, or in a worktree) use it. It opens the review and ends, so the terminal is free. The log is `~/.difftate/log`.
- Write `HEAD` in capitals. In a worktree on macOS, `head` points to the main checkout's HEAD and shows the wrong diff.
- Each diff except `unstaged` and `staged` also includes uncommitted changes: it compares the given commit with the files on disk.
- The diff opens in the browser (`difftate --open nvim` opens the Neovim viewer instead). Comment on a line, and the agent replies in the same thread.
- New changes show up by themselves, in the browser and in Neovim.
- To look at a different view, run the new command: it switches the folder's view and opens the viewer again. Every view is the same review, so threads stay. The browser's **View** menu and Neovim's `<leader>rV` switch views too.
- Use `difftate agent <name>` in a repository to change which listed agent replies there (no restart); `difftate agent` says which it uses.

## Questions

Ask these, together, before section 2. If `~/.zshrc` already has the `PATH` line for difftate (an earlier install), ask only question 1.

1. **Where should difftate be cloned?** Default: `~/difftate`.

## Uninstall

1. Run `difftate stop`. Remove the difftate lines (the `PATH` line, or an old `source` line and shortcuts, and `DT_OPEN`) from `~/.zshrc`.
2. If an earlier install linked the removed Herdr viewer: `rm ~/.config/herdr-app/mods/difftate` (the link only), and the `cmd-shift-r` line from `~/.config/herdr-app/keys.json` if you added it.
3. `rm -rf ~/difftate` (or your `DT_HOME`). `~/.difftate` holds the review history: keep it, or remove it too.
