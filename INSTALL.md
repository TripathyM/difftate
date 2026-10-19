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
- Don't start `difftate` itself: it launches a server and an agent. The user does that.

## 1. Check requirements

Run each check. Report all results together, then stop if anything **required** is missing.

| Need | Check | If missing |
|---|---|---|
| zsh (required) | `command -v zsh` | difftate is zsh-only; stop |
| git (required) | `git --version` | macOS: `xcode-select --install` |
| python3 (required) | `python3 --version` | macOS: `xcode-select --install`, or `brew install python` |
| Node.js + npm (required, for diffity) | `node --version && npm --version` | Install Node 18+ (e.g. via nvm or `brew install node`) |
| An agent CLI (one is required) | `zsh -c 'whence -p claude'` and `zsh -c 'whence -p opencode'`, run separately | Install [Claude Code](https://docs.claude.com/en/docs/claude-code) or [OpenCode](https://opencode.ai) |

The agent CLI check passes when at least one of the two prints a path. Use `whence -p`, not `command -v`: `command -v` also reports aliases and functions, and difftate needs the real program.

Tell the user which commands will work: `difftate` / `dtc` need `claude`, `dto` needs `opencode`. Both are defined either way; only the installed one is usable.

## 2. Install diffity 0.9.5

difftate is tested with diffity **0.9.5**, the last CLI release. Later versions of the upstream project are a Mac app, not this CLI.

1. Check: `diffity --version`
2. If it prints `0.9.5`, skip to step 3.
3. If it prints another version, tell the user and ask before replacing it.
4. Install: `npm install -g diffity@0.9.5`
   - `EACCES` / permission error: stop. Tell the user their global npm folder needs fixing (nvm avoids this); don't use `sudo`.
5. Verify: `diffity --version` prints `0.9.5`.

diffity uses a native module (`better-sqlite3`). If it later fails after a Node upgrade, the fix is `npm rebuild -g diffity`.

## 3. Clone the repo

Use the folder from question 1 (default `~/difftate`). Call it `DT_HOME` below, and write it with `~` when it is under the home folder (e.g. `~/difftate`).

1. If `DT_HOME/difftate.zsh` already exists and `git -C DT_HOME remote get-url origin` points at `TripathyM/difftate`: run `git -C DT_HOME pull --ff-only` and go to step 4.
2. If `DT_HOME` exists but is something else: stop and ask for another folder.
3. Otherwise: `git clone https://github.com/TripathyM/difftate.git DT_HOME`

## 4. Add difftate to `~/.zshrc`

Build one block of lines to add, back up once, confirm once.

1. If `~/.zshrc` doesn't exist, create it empty (`touch ~/.zshrc`) and skip the backup in step 4.
2. Check for an existing install: `grep -n '^[^#]*difftate\.zsh' ~/.zshrc` (ignores commented-out lines).
   - It finds a `source` line for `DT_HOME/difftate.zsh` (as `~/…` or the full path): leave it out of the block.
   - It finds a line with a **different** path: show it, and ask whether to replace it. Don't add a second one.
   - It finds nothing: the block starts with:

     ```zsh
     # difftate: review agent diffs in diffity (https://github.com/TripathyM/difftate)
     source DT_HOME/difftate.zsh
     ```

3. Only if question 2 was yes, add one line per Claude setup (see [Shortcuts](#shortcuts-for-several-claude-setups)). First check each name: `grep -n '^<name>()' ~/.zshrc`. If it is already defined, leave it out.
4. If the block is empty, skip to step 5. Otherwise back up: `cp ~/.zshrc ~/.zshrc.bak-difftate-$(date +%Y%m%d%H%M%S)` and tell the user the backup path.
5. Show the user the full block, with `DT_HOME` filled in, and wait for a yes.
6. Append the block to the end of `~/.zshrc`. Shortcut lines must come after the `source` line.

### Shortcuts for several Claude setups

One line per setup, using the user's answers to question 2:

```zsh
dtcw() { difftate --cmd ccw "$@"; }                                         # default config (~/.claude)
dtcp() { CLAUDE_CONFIG_DIR=~/.claude-personal difftate --cmd ccp "$@"; }   # own config dir
```

- Set `CLAUDE_CONFIG_DIR` only when the setup uses a non-default dir. Never set it to `~/.claude`: leave it unset for the default.
- For each shortcut being added (not ones already defined), check its command with `zsh -ic 'type <cmd>'` (an alias or wrapper is fine here). If it prints "not found", tell the user and ask for the right command. Don't write that line until they answer.

## 5. Verify

1. `zsh -ic 'type difftate dtc dto'`: each output line contains "is a shell function".
2. `diffity --version`: prints `0.9.5`.
3. If shortcuts were added: `zsh -ic 'type <name>'` for each, and the output contains "is a shell function".

Report what passed. Then show the user the quick guide below, as written. If shortcuts were added, also show one line per shortcut (e.g. `dtcw HEAD~1`): shortcuts take the same arguments as `difftate`.

## Quick guide (show after install)

First, open a new terminal (or run `source ~/.zshrc`). Then `cd` into a git repo, on the branch you want reviewed.

| To review | Run |
|---|---|
| The whole branch, against master | `difftate` |
| The whole branch, against main | `difftate main` |
| The last commit | `difftate HEAD~1` |
| The last 3 commits (any number) | `difftate HEAD~3` |
| Only uncommitted changes | `difftate HEAD` |

- Each diff also includes uncommitted changes: it compares the given commit with the files on disk.
- Use `dto` in place of `difftate` for OpenCode, with the same arguments.
- The diff opens in the browser. Comment on a line, and the agent replies in the same thread.
- Refresh the page to see new changes.
- To review a different range, stop the watcher (Ctrl+C) and run the new command.

## Questions

Ask these, together, before step 3. If `~/.zshrc` already sources `difftate.zsh` (an earlier install), ask only question 1, unless the user asked to add shortcuts.

1. **Where should difftate be cloned?** Default: `~/difftate`.
2. **Do you run more than one Claude Code setup** (for example separate work and personal accounts, with different commands or config dirs)? Default: no. If yes, for each setup ask for:
   - a shortcut name (e.g. `dtcw`)
   - the command that starts that Claude (e.g. an alias or wrapper like `ccw`)
   - its config dir, if it isn't the default `~/.claude`

## Uninstall

1. Remove the difftate lines (the `source` line and any shortcuts) from `~/.zshrc`.
2. `rm -rf ~/difftate` (or your `DT_HOME`).
3. Optional: `npm uninstall -g diffity`.
