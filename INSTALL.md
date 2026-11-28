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
- In the Neovim config, only add a new file, after showing it and getting a yes. Never edit a file that is already there.
- Never use `sudo`. Never read or edit Claude or OpenCode settings files (`~/.claude*/settings.json` etc.): for the agent list, aliases come from the shell only.
- If a step fails, stop, show the error, and suggest the fix listed here. If no fix is listed, ask the user. Don't improvise workarounds.
- Don't start `difftate` itself: it launches the watcher, which runs the agent. The user does that.

## 1. Check requirements

Run each check. Report all results together, then stop if anything **required** is missing.

| Need | Check | If missing |
|---|---|---|
| git (required) | `git --version` | macOS: `xcode-select --install` |
| latest python3 (required, for the watcher and the `difftate` program) | `python3 --version`, and `command -v python3` should be Homebrew's (`/opt/homebrew/bin/python3`) | macOS: `brew install python`. The built-in `/usr/bin/python3` (Command Line Tools, 3.9) is no longer supported |
| An agent CLI (one is required) | `command -v claude` and `command -v opencode`, run separately (in `zsh -ic '…'` if your shell's config sets up the `PATH`) | Install [Claude Code](https://docs.claude.com/en/docs/claude-code) or [OpenCode](https://opencode.ai) |

The agent CLI check passes when at least one of the two is a real program, or an alias or shell function (section 5 writes the program it starts, never the alias or function). Keep what it found: question 4 uses it.

Only if the user chose **Browser + Neovim** (question 2), also check:

| Need | Check | If missing |
|---|---|---|
| Neovim 0.10 or later (required for the Neovim viewer) | `nvim --version \| head -1` | macOS: `brew install neovim` |
| gitsigns.nvim (required: the viewer moves through the changes with it) | `nvim --headless "+lua io.write(pcall(require, 'gitsigns') and 'ok' or 'missing')" +qa` prints `ok` | LazyVim has it. Otherwise tell the user to add `lewis6991/gitsigns.nvim` with their plugin manager, and stop the Neovim part until it is there |
| Which plugin manager (for section 4; not required) | `nvim --headless "+lua io.write(pcall(require, 'lazy') and 'lazy' or 'other')" +qa` | `other` is fine: section 4 installs it as a Neovim package |

LazyVim is not needed: any Neovim 0.10 with gitsigns works. LazyVim, which-key, Snacks and lualine only add to it (a key list, the pickers' previews and files sidebar, the statusline note).

If Neovim is missing or too old, say so and go on with **Browser only**: the browser viewer still works.

Tell the user that no coding agent replies until the agent list names it: there is no default (question 4, section 5). Tell them too that the agent may edit files and run commands in the repository to answer a comment, as it does in their own sessions.

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

   - If the user said yes to question 3 (open Neovim by default) and `grep -n '^[^#]*DT_OPEN' ~/.zshrc` finds nothing, add to the block:

     ```zsh
     export DT_OPEN=nvim
     ```

3. If the block is empty, skip to step 4. Otherwise back up: `cp ~/.zshrc ~/.zshrc.bak-difftate-$(date +%Y%m%d%H%M%S)` and tell the user the backup path.
4. Show the user the full block, with `DT_HOME` filled in, and wait for a yes.
5. Append the block to the end of `~/.zshrc`.

Which coding agent and account reply is not a shell function or a `difftate` option: it is the agent list (section 5). Don't add shell functions for it.

## 4. The Neovim viewer (only for Browser + Neovim)

Skip this section if the user chose **Browser only**. The browser viewer needs nothing more.

The plugin is loaded from the clone (`dir = "DT_HOME"`), so one `git pull` updates the plugin and the watcher together. Never install it a second time from GitHub (`"TripathyM/difftate"`): two copies can be at different versions.

1. Check for an existing install: `grep -rln 'difftate' ~/.config/nvim 2>/dev/null` and `ls ~/.local/share/nvim/site/pack/difftate/start/difftate 2>/dev/null`. If either finds something, say so and skip to step 4.
2. **With lazy.nvim** (the check in section 1 printed `lazy`) and a `~/.config/nvim/lua/plugins/` folder (LazyVim, or any lazy.nvim setup that imports `plugins`): show the user this file, with `DT_HOME` filled in, wait for a yes, then write it to `~/.config/nvim/lua/plugins/difftate.lua`. With lazy.nvim but no such folder: show it and tell the user to add the spec to their own lazy.nvim setup. Then go to step 4.

   ```lua
   return {
     {
       dir = "DT_HOME",
       name = "difftate",
       main = "difftate",
       opts = {},
     },
     -- The note "review open · live · ..." in the statusline while a review is open
     {
       "nvim-lualine/lualine.nvim",
       optional = true,
       opts = function(_, opts)
         table.insert(opts.sections.lualine_x, 1, { function() return require("difftate").status() end })
       end,
     },
   }
   ```

3. **With any other plugin manager, or none** (vim-plug, packer, mini.deps, a plain `init.lua`): install it as a Neovim package, which Neovim loads by itself at start-up:
   1. `mkdir -p ~/.local/share/nvim/site/pack/difftate/start && ln -s DT_HOME ~/.local/share/nvim/site/pack/difftate/start/difftate`
   2. Show the user this line, wait for a yes, then append it to the end of `~/.config/nvim/init.lua` (back it up first, as for `~/.zshrc`). It maps the keys; without it only the `:Difftate…` commands work. If they have `init.vim` instead, append it as `lua require("difftate").setup({})`.

      ```lua
      require("difftate").setup({}) -- difftate's Neovim viewer: keys under <leader>r
      ```
4. Check it loads: `nvim --headless "+DifftateStatus" +qa` prints no error.
5. Tell the user: the keys are under `<leader>r`, the leader key of their own config (Space in LazyVim, `\` in plain Neovim), so `<leader>rr` opens the review; `:DifftateOpen` does too. Any key can be renamed in `keys` (`setup({ keys = { toggle = "<F5>" } })`, or `opts.keys` with lazy.nvim). With LazyVim's refactoring extra, `<leader>rs` and `<leader>rf` are already taken: rename those two.

## 5. The agent list

The agent list, `~/.difftate/agents.toml` (`$DIFFTATE_HOME/agents.toml`), is the only thing that says which coding agents can reply. Without it, difftate opens reviews and takes comments, but nothing replies.

**If the file exists:** show it and leave it as it is. Check it, and show the lines to change for what is wrong. An entry with no `tool`, or a list of two or more with no `default`, makes difftate refuse the whole list: nothing replies. A `cmd` that is not a program by the check in step 2 gets that entry's runs refused. The user edits the file. Go to step 5.

1. **Collect the names.** Start from what the requirements check found (`claude`, `opencode`). Look for aliases that start them, `zsh -ic 'alias' | grep -E 'claude|opencode'`, and ask the user for any other command they start a coding agent or an account with.
2. **Check each name** with `zsh -ic 'whence -w <name>'`. **`cmd` must be a real program, on `PATH` or a full path, never a shell alias or function**: difftate does not read your shell config.
   - `command` (or `hashed`): it can be `cmd` as is.
   - `alias`: read its text with `zsh -ic 'alias <name>'`. Write its program as `cmd` and its `VAR=value` parts as `env`. For example, `ccw='CLAUDE_CONFIG_DIR=~/.claude-work claude'` becomes `cmd = "claude"`, `env = { CLAUDE_CONFIG_DIR = "~/.claude-work" }`. Show the result and ask whether it is right. `zsh -ic 'whence -p <program>'` must find the program (or it is a full path); if `whence -w` says the program is itself an alias too, read that one as well, unless it is the same name. In `env`, difftate expands only a leading `~`, so write `$HOME/…` as `~/…` and ask for the value of any other variable. In `cmd` it expands nothing: write a full path out, without `~`. An entry can't pass arguments: if the alias has any, say that they are left out.
   - `function`: show it to the user (`zsh -ic 'whence -f <name>'`) and ask which program it starts, and with what environment.
   - `none`: say that it was not found, and ask for the program's full path.
3. **Suggest the list** (question 4). Each entry is an `[agents.<name>]` table: `tool` (`claude` or `opencode`, required), `cmd` (required), `env` (what it needs, optional) and `model` (optional).
   - Only `claude`, or only `opencode`, found: suggest a list with that one agent. A list of one needs no `default` line.

     ```toml
     [agents.claude]
     tool = "claude"
     cmd = "claude"
     ```

   - Both found, or more than one account: suggest one entry for each real command, and ask for their names and which one is the `default`. A list of two or more needs `default`. An example, for a personal account started by a program `ccp` and a work account started by the alias `ccw` above:

     ```toml
     default = "personal"

     [agents.personal]
     tool = "claude"
     cmd = "ccp"
     env = { CLAUDE_CONFIG_DIR = "~/.claude-personal" }

     [agents.work]
     tool = "claude"
     cmd = "claude"
     env = { CLAUDE_CONFIG_DIR = "~/.claude-work" }
     ```

4. Show the user the full `agents.toml`, wait for a yes, then write it. The file is read for each run: no restart.
5. With two or more agents, tell the user to run `difftate agent <name>` once in each repository that should use one that is not the default (it covers the repository's worktrees too).

## 6. The review path skill (optional)

The skill `write-review-path` tells a coding agent how to write `review-path.md`, the reading order that difftate's viewers follow. It needs no difftate to run. To let every agent session on this machine use it, link it into the agent's skills folder. For each agent the user has (Claude Code: `~/.claude/skills`; OpenCode: `~/.config/opencode/skills`):

1. If `<skills folder>/write-review-path` exists, say so and skip.
2. Otherwise: `mkdir -p <skills folder> && ln -s DT_HOME/skills/write-review-path <skills folder>/write-review-path`

Inside a difftate checkout, `bin/setup` links the skill already.

## 7. Verify

1. `zsh -ic 'command -v difftate dt-export dt-reply'`: each prints a path under `DT_HOME/bin`.
2. `zsh -ic 'difftate --help | head -1'` prints a line starting with `difftate`.
3. Browser + Neovim only: `nvim --headless "+DifftateStatus" +qa` prints no error.

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
- The diff opens in the browser (`difftate --open nvim` opens the Neovim viewer instead; with `DT_OPEN=nvim` it is the other way round, and `--open browser` opens the browser). In Neovim, `<leader>rr` opens and closes the review. Comment on a line, and the agent replies in the same thread.
- New changes show up by themselves, in the browser and in Neovim.
- To look at a different view, run the new command: it switches the folder's view and opens the viewer again. Every view is the same review, so threads stay. The browser's view picker and Neovim's `<leader>rV` switch views too.
- Use `difftate agent <name>` in a repository to change which listed agent replies there (no restart); `difftate agent` says which it uses.

## Questions

Ask these, together, before section 2 (question 4 needs the results of section 1). If `~/.zshrc` already has the `PATH` line for difftate (an earlier install), skip question 1: the clone is where that line points.

1. **Where should difftate be cloned?** Default: `~/difftate`.
2. **Which viewer do you want?**
   - **Browser only** (default): reviews open in a browser tab. Nothing more to install.
   - **Browser + Neovim**: also adds the Neovim viewer, to review in your own Neovim (any Neovim 0.10 with gitsigns; LazyVim not needed). The browser still works.
3. Only for **Browser + Neovim**: **Should `difftate` open Neovim instead of the browser by default?** Default: no (`difftate --open nvim` opens it each time).
4. **Which coding agents should reply to your comments?** Skip it if the agent list already exists (section 5). Suggest an answer from what the requirements check found, by steps 1 to 3 of section 5 (their follow-up questions are part of this one, and may be asked after the others): one agent when only `claude` or only `opencode` was found; with both, or more than one account, one entry for each real command, and ask for their names and the default. The file is written only after the user has seen all of it (section 5, step 4).

## Uninstall

1. Run `difftate stop`. Remove the difftate lines (the `PATH` line, or an old `source` line and shortcuts, and `DT_OPEN`) from `~/.zshrc`.
2. Remove the Neovim viewer: `~/.config/nvim/lua/plugins/difftate.lua` (lazy.nvim), or the link `~/.local/share/nvim/site/pack/difftate` and the `require("difftate").setup` line in `init.lua` (other plugin managers).
3. If an older install linked the removed Herdr viewer: `rm ~/.config/herdr-app/mods/difftate` (the link only), and the `cmd-shift-r` line from `~/.config/herdr-app/keys.json` if you added it.
4. `rm -rf ~/difftate` (or your `DT_HOME`). `~/.difftate` holds the review history: keep it, or remove it too.
