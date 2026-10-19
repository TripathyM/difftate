# difftate

Annotate an agent's diff, and the agent answers or fixes the code.

Review a diff in [diffity](https://www.npmjs.com/package/diffity), comment on any line, and Claude Code or OpenCode replies or edits the code, with the session's full context. Progress shows live in the diffity UI and in the terminal.

## Requirements

- [diffity](https://www.npmjs.com/package/diffity) CLI, tested with `0.9.5`: `npm install -g diffity@0.9.5`
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (`claude`) or [OpenCode](https://opencode.ai) (`opencode`)
- `zsh`, `python3` (standard library only), `git`

## Install

**With an agent:** paste this into Claude Code (or any coding agent):

```
Install difftate by following https://raw.githubusercontent.com/TripathyM/difftate/main/INSTALL.md
```

It checks requirements, installs diffity, clones the repo, and asks before editing `~/.zshrc`. See [INSTALL.md](INSTALL.md).

**By hand:**

```bash
git clone https://github.com/TripathyM/difftate.git ~/difftate   # any folder works
echo 'source ~/difftate/difftate.zsh' >> ~/.zshrc
source ~/.zshrc
```

`difftate.zsh` finds the watcher next to itself. After editing it, run `source ~/.zshrc` (or open a new terminal).

## Quick start

Run from inside the repo, **on the branch you want reviewed**:

```bash
difftate                    # Claude Code, diff vs master (short: dtc)
dto                         # OpenCode
difftate HEAD~3             # diff the last 3 commits instead of master
difftate --session <uuid>   # attach a specific session
difftate --no-session       # headless, no session context
difftate --model <model>    # force the agent's model (default: the session's model)
difftate --cmd <command>    # run Claude through another command or alias
```

Without `--session`, it attaches the latest agent session for the current folder, so comments are answered with that session's full context.

**Always run from the branch's checkout.** The agent edits files in the current directory. There is deliberately no "source branch" option: it would let the agent write fixes onto the wrong branch. To review another branch without switching, use a worktree (`git worktree add ../repo-x feature-x`, `cd` there, run `difftate master`).

## Example: several Claude setups

Shortcuts go in `~/.zshrc`, after the `source` line. Say `ccw` runs Claude with the default config and `ccp` is a wrapper that sets its own config dir:

```zsh
dtcw() { difftate --cmd ccw "$@"; }                                         # uses ~/.claude, the default
dtcp() { CLAUDE_CONFIG_DIR=~/.claude-personal difftate --cmd ccp "$@"; }   # same dir the wrapper uses
```

Sessions are found in `$CLAUDE_CONFIG_DIR` (default `~/.claude`), the same rule `claude` itself follows. If a wrapper sets a different config dir internally, set `CLAUDE_CONFIG_DIR` in its shortcut as above, or the watcher looks in the wrong place. Don't set it to `~/.claude` explicitly: leave it unset for the default.

## Files

| File | What it does |
|---|---|
| `difftate.zsh` | Shell functions `difftate` / `dtc` / `dto`: pick the session, then call `difftate-watch.sh` |
| `difftate-watch.sh` | Starts (or reuses) diffity, polls for open comment threads, dispatches them to the agent, posts "🕒 Queued" status while the agent is busy |
| `lib/threads.py` | Picks the threads waiting on the agent, and turns open threads into the prompt text (status comments removed) |
| `lib/stream_fmt.py` | Reads the agent's JSON event stream; prints live progress lines and keeps the diffity status comment updated |

## What you see

**In the diffity UI**, each thread gets one status comment, edited in place (UI refreshes every ~2s):

```
[dt-queued] 🕒 Queued — agent is busy with another comment…   ← arrived while agent was busy
[dt-status] ⏳ Thinking… (4s)
[dt-status] ⏳ Working… (12s) · 🧠 context 84k / 1M (8%)
- ✅ `Read src/app.ts`
- ⏳ `Edit src/app.ts`
[dt-status] ✅ Done in 42s · 🧠 context 90k / 1M (9%)       ← checklist removed when done
[dt-status] ❌ Failed after 30s  (+ checklist and reason)
```

The agent's real answer follows as a separate `[dt-reply]` comment. Status comments are never sent to the model (see [What the agent gets](#what-the-agent-gets)).

**In the watcher terminal**:

```
[07:40:23] New/changed threads detected — dispatching to claude
  Model: claude-opus-5-5 (from session)
[07:40:24] 🚀 session 3f1c9a20 started · model claude-opus-5-5
[07:40:25] 🔧 Read  src/app.ts
[07:40:26] 💬 <agent text>
[07:40:26] ✅ done in 8s, $0.1429 · 🧠 context 28k / 1M (3%)
[07:40:37] Queued thread b2c07211 (agent busy)
```

## Context size and when to compact

`🧠 context` is the token count of the agent's latest model call. In session mode that includes the resumed session's full history, so it is the session's current size.

- Claude reports its window, so you get a percentage.
- OpenCode shows tokens only, unless you set `DT_CONTEXT_WINDOW`.
- With the same model as your session (see below), it should be close to `/context` in that session (not exact: `-p` may load a slightly different system prompt and tool set). A big gap usually means a different model answered.
- At **70%+** it adds `⚠️ consider /compact`. The agent can't compact itself: run `/compact` in your own Claude session.

## Which model answers

A Claude session doesn't store its model. Each `claude -p` the watcher starts uses the **current default**, and running `/model` in *any* session changes that default. Without a fix, your Opus session could get its comments answered by Sonnet, which also drops Opus's thinking blocks (its unstated reasoning) and makes 🧠 context disagree with `/context`.

| Tool | Model used |
|---|---|
| `difftate` with a session | Read from the session file: the model of your latest interactive turn (e.g. `claude-opus-5-5`), passed as `--model` |
| `difftate --no-session` | CLI default |
| `dto` (OpenCode) | OpenCode keeps the session's own model on resume, so no detection is needed |
| Any, with `--model` | `--model` always wins |

The watcher prints `Model: <name> (from session)` on every dispatch, and the 🚀 line shows the model the agent actually ran.

**Cost note:** prompt caches are per model and expire after ~1h idle. The first comment after a model switch or a long break re-caches the whole session (roughly $1 for a ~120k-token Opus session at list price; cloud providers' pricing differs). Later comments within the hour are cents. Switching models back and forth costs more than staying on one.

## Settings you can change

### Environment variables (set before `difftate` / `dto`)

| Variable | Default | Effect |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | unset (`~/.claude`) | Where Claude sessions are looked up; also read by `claude` itself |
| `DT_CONTEXT_WINDOW` | unset (Claude auto-detects) | Context window in tokens, for the % when the tool doesn't report it. E.g. `export DT_CONTEXT_WINDOW=200000` for OpenCode |

### Constants (edit the file)

| Name | File | Default | Effect |
|---|---|---|---|
| `COMPACT_WARN_PCT` | `lib/stream_fmt.py` | `70` | % of context window that triggers `⚠️ consider /compact` |
| `MAX_STEPS_SHOWN` | `lib/stream_fmt.py` | `8` | Checklist steps shown; older ones collapse to "…N earlier steps" |
| `STATUS_REFRESH_S` | `lib/stream_fmt.py` | `3` | Seconds between status comment refreshes while the agent is quiet |
| `TEXT_MAX` | `lib/stream_fmt.py` | `300` | Max characters of agent text per terminal line |
| `ANCHOR_MAX_LINES` | `lib/threads.py` | `20` | Lines of the commented code included per thread |
| `SUMMARY_MAX` | `lib/threads.py` | `200` | Characters per comment in "Other open threads" |
| `DT_REPLY_MARKER` | `difftate-watch.sh` | `[dt-reply]` | Prefix on the agent's answers. Threads ending in it are **not** re-dispatched |
| `DT_STATUS_MARKER` | `difftate-watch.sh` | `[dt-status]` | Prefix on the live status comment. Not re-dispatched, never sent to the model |
| `DT_QUEUED_MARKER` | `difftate-watch.sh` | `[dt-queued]` | Prefix on "Queued" status. Threads ending in it **are** dispatched next |

### Watcher flags (`difftate-watch.sh --help`)

`--ref`, `--tool`, `--session`, `--model`, `--cwd`, `--interval` (poll seconds, default 1), `--cmd`.

### Internal env vars (set by the watcher, don't set yourself)

| Variable | Purpose |
|---|---|
| `DT_PORT` | diffity port, for the status-comment API |
| `DT_THREAD_IDS` | Comma-separated threads the current agent run handles |
| `DT_THREADS_JSON` | Those threads as JSON, used to reuse "Queued" comments |
| `DT_REPLY_MARKER`, `DT_STATUS_MARKER`, `DT_QUEUED_MARKER` | Passed through to `lib/stream_fmt.py` |

## How it works

1. Every `--interval` seconds the watcher lists open threads. A thread is **pending** when its last comment is yours (or another reviewer's). Ones ending in `[dt-reply]` or `[dt-status]` are waiting on you; a trailing `[dt-queued]` doesn't count.
2. Pending threads → one agent run, in the background, with the prompt below. Agents run **one at a time**; comments that queue up during a run all go into the next one.
3. While it runs, the watcher keeps polling; new threads get `🕒 Queued` within ~1s and go in the next run.
4. `lib/stream_fmt.py` posts or reuses the status comment, then edits it via diffity's local API (`POST /api/threads/:id/reply`, `PATCH /api/comments/:id`).
5. Ctrl+C stops the watcher, the running agent and its child processes, and diffity (if the watcher started it).

### What the agent gets

`lib/threads.py` builds the prompt as plain text, without status comments or JSON metadata, so the agent doesn't need to run `diffity agent list` itself:

```
## Reply to these threads (1)

### Thread 94beac30 — src/user.ts:42-44
Code:
<the commented lines>
user: rename this to fetchUser
you: Should I also rename the test?        ← the agent's earlier [dt-reply]
user: yes

## Other open threads (2) — context only
- 824f35ef — src/api.ts:10
  user: why is this retry here?
  you: It handles flaky 502s from the gateway.
```

followed by the rules (reply format, change code only when asked, never resolve). "Other open threads" lets the agent see a related comment elsewhere ("this also fixes your comment on api.ts") at a fraction of the full JSON's size.

Agent invocation:
- Claude: `claude -p … --resume <session> --model <model> --settings <sandbox allow> --output-format stream-json --verbose < /dev/null`
  - `--settings '{"sandbox":{"filesystem":{"allowWrite":["~/.diffity/"]}}}'` lets the agent's `diffity agent reply` write to diffity's database when Claude's sandbox is on. It's added to your own settings for these runs only, and ignored when the sandbox is off.
- OpenCode: `opencode run … --session <session> [--model <model>] --auto --format json < /dev/null`

`< /dev/null` matters: `opencode run` hangs waiting on stdin otherwise.

## Known limitations

- A follow-up you post on a thread **while the agent is working on that same thread** can be missed (the agent's reply lands after it, so the thread looks answered). Reply again after the agent's answer. Tracked in [#3](https://github.com/TripathyM/difftate/issues/3).
- `diffity` already running for the repo is reused as-is, including its old refs. Run `diffity kill` first to change refs.
- An open Claude/OpenCode terminal on the same session doesn't live-refresh with the watcher's turns.

## Troubleshooting

| Symptom | Check |
|---|---|
| No status comment appears | Watcher terminal for `could not post status comment`; is diffity on the port shown? |
| Agent never finishes | Run the agent command by hand with `< /dev/null`; look for auth or stdin hangs |
| Wrong diff shown | `diffity kill`, then rerun `difftate <ref>` |
| Answer from the wrong model / 🧠 far from `/context` | Check the `Model:` line; force it with `difftate --model <model>` |
| Thread ignored | Its last comment starts with `[dt-reply]` or `[dt-status]`; reply again to re-trigger |

## Roadmap

Planned work and known bugs are tracked in [GitHub issues](https://github.com/TripathyM/difftate/issues).

## License

MIT, see [LICENSE](LICENSE).
