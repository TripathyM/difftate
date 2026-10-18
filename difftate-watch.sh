#!/usr/bin/env bash
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
TOOL=""
REF=""
SESSION_ID=""
# Model override. Empty = Claude with --session uses the session's own model.
MODEL=""
CWD=""
INTERVAL=1
CMD=""
DIFFITY_PID=""
LAST_HASH=""
# Prefix on the agent's answers. Threads ending in one are waiting on the user.
DT_REPLY_MARKER="[dt-reply]"
# Prefix on the live status comment (checklist → "✅ Done"). Never sent to the model.
DT_STATUS_MARKER="[dt-status]"
# Status comment the watcher posts on threads that arrive while the agent is busy.
# Deliberately NOT DT_REPLY_MARKER, so those threads still get dispatched next.
DT_QUEUED_MARKER="[dt-queued]"
AGENT_PID=""
# Turns the agent's JSON event stream into live progress lines
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STREAM_FMT="$SCRIPT_DIR/lib/stream_fmt.py"
# Pending-thread filter and prompt builder
THREADS_PY="$SCRIPT_DIR/lib/threads.py"

# ── Usage ─────────────────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
difftate-watch.sh — Start diffity and poll for comments, dispatching to an AI coding session.
(Normally run via the difftate / dtc / dto shell functions.)

Usage:
  difftate-watch.sh --ref <git-ref> --tool <claude|opencode> [options]

Required:
  --ref <ref>            Git ref for diffity (master, HEAD~3, branch-name)
  --tool <tool>          AI tool to dispatch to (claude, opencode)

Optional:
  --session <id>         Resume an existing session (full conversation context)
  --cwd <path>           Repo path for headless mode (default: current directory)
  --interval <seconds>   Polling interval in seconds (default: 1)
  --cmd <binary>         Override the CLI binary or shell alias (e.g. a wrapper around claude)
  --model <model>        Model for the agent (default: Claude with --session matches the
                         session's latest interactive model)
  --help                 Show this help

Examples:
  # Claude Code — headless (no session context)
  difftate-watch.sh --ref master --tool claude --interval 1

  # Claude Code — resume mode (full session context)
  difftate-watch.sh --ref master --tool claude --session <full-uuid> --interval 1

  # OpenCode — headless
  difftate-watch.sh --ref master --tool opencode --interval 1

  # OpenCode — resume mode
  difftate-watch.sh --ref master --tool opencode --session <session-id> --interval 1
EOF
  exit 0
}

# ══════════════════════════════════════════════════════════════════════════════
# TOOL ADAPTERS
#
# Each tool implements three functions:
#   default_cmd_<tool>      → echo the default CLI binary name
#   validate_session_<tool> → return 0 if session exists, 1 if not
#   send_<tool>             → send a prompt to the tool ($1 = prompt)
#
# To add a new tool:
#   1. Implement the three functions below
#   2. Add the tool name to SUPPORTED_TOOLS
#   3. That's it — arg parsing, dispatch, and validation are automatic
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_TOOLS="claude opencode"

# ── Claude Code ───────────────────────────────────────────────────────────────

default_cmd_claude() {
  echo "claude"
}

validate_session_claude() {
  local session_found=false
  for dir in "$CLAUDE_HOME"/projects/*/; do
    if [[ -f "${dir}${SESSION_ID}.jsonl" ]]; then
      session_found=true
      break
    fi
  done
  [[ "$session_found" == "true" ]]
}

# The model isn't stored with a session: each `claude -p` picks the current
# default, which changes whenever /model is used in ANY session. Read the model
# from the session's latest interactive (cli) turn so replies come from the same
# model and keep its thinking blocks (other models drop them).
session_model_claude() {
  local file
  file=$(ls "$CLAUDE_HOME"/projects/*/"${SESSION_ID}.jsonl" 2>/dev/null | head -1)
  [[ -z "$file" ]] && return 0
  python3 - "$file" <<'PY' 2>/dev/null || true
import json, sys
interactive = any_model = ""
for line in open(sys.argv[1]):
    if '"assistant"' not in line:
        continue
    try:
        e = json.loads(line)
    except ValueError:
        continue
    model = (e.get("message") or {}).get("model") or ""
    if e.get("type") != "assistant" or not model or model.startswith("<"):
        continue
    any_model = model
    if e.get("entrypoint") == "cli":
        interactive = model
print(interactive or any_model)
PY
}

send_claude() {
  local prompt="$1"
  local args=(--allowedTools Edit Write Read Bash --output-format stream-json --verbose)
  local model="$MODEL" source="--model"
  if [[ -z "$model" && -n "$SESSION_ID" ]]; then
    model=$(session_model_claude)
    source="session"
  fi
  if [[ -n "$model" ]]; then
    echo "  Model: $model (from $source)"
    args+=(--model "$model")
  else
    echo "  Model: CLI default"
  fi
  [[ -n "$SESSION_ID" ]] && args+=(--resume "$SESSION_ID")
  (cd "$CWD" && "$CMD" -p "$prompt" "${args[@]}" < /dev/null) | python3 -u "$STREAM_FMT" claude
}

# ── OpenCode ──────────────────────────────────────────────────────────────────

default_cmd_opencode() {
  echo "opencode"
}

validate_session_opencode() {
  opencode session list 2>&1 | grep -q "$SESSION_ID"
}

send_opencode() {
  local prompt="$1"
  local args=(--auto --format json)
  [[ -n "$MODEL" ]] && args+=(--model "$MODEL")
  [[ -n "$SESSION_ID" ]] && args+=(--session "$SESSION_ID")
  (cd "$CWD" && "$CMD" run "$prompt" "${args[@]}" < /dev/null) | python3 -u "$STREAM_FMT" opencode
}

# ── Adapter template (copy this to add a new tool) ────────────────────────────
#
# default_cmd_NEWTOOL() {
#   echo "newtool"
# }
#
# validate_session_NEWTOOL() {
#   newtool session list 2>&1 | grep -q "$SESSION_ID"
# }
#
# send_NEWTOOL() {
#   local prompt="$1"
#   if [[ -n "$SESSION_ID" ]]; then
#     (cd "$CWD" && "$CMD" run "$prompt" --session "$SESSION_ID")
#   else
#     (cd "$CWD" && "$CMD" run "$prompt")
#   fi
# }
#
# Then add "NEWTOOL" to SUPPORTED_TOOLS above.

# ══════════════════════════════════════════════════════════════════════════════
# GENERIC DISPATCH — no tool-specific logic below this line
# ══════════════════════════════════════════════════════════════════════════════

dispatch() {
  local prompt="$1"
  "send_${TOOL}" "$prompt"
}

validate_session() {
  "validate_session_${TOOL}"
}

list_sessions() {
  case "$TOOL" in
    claude)
      local files=("$CLAUDE_HOME"/projects/*/*.jsonl)
      if [[ -e "${files[0]}" ]]; then
        for f in "${files[@]}"; do basename "$f" .jsonl; done | tail -5
      else
        echo "    (none found)"
      fi
      ;;
    opencode) opencode session list 2>&1 || echo "    (none found)" ;;
    *)        echo "    (session listing not implemented for $TOOL)" ;;
  esac
}

# ── Arg parsing ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)          REF="$2"; shift 2 ;;
    --tool)         TOOL="$2"; shift 2 ;;
    --session)      SESSION_ID="$2"; shift 2 ;;
    --model)        MODEL="$2"; shift 2 ;;
    --cwd)          CWD="$2"; shift 2 ;;
    --interval)     INTERVAL="$2"; shift 2 ;;
    --cmd)          CMD="$2"; shift 2 ;;
    --help|-h)      usage ;;
    *)              echo "Unknown flag: $1"; usage ;;
  esac
done

# ── Validation ────────────────────────────────────────────────────────────────
[[ -z "$REF" ]] && { echo "Error: --ref is required"; exit 1; }
[[ -z "$TOOL" ]] && { echo "Error: --tool is required"; exit 1; }
[[ -z "$CWD" ]] && CWD="$(pwd)"

# Check tool is supported
if ! echo "$SUPPORTED_TOOLS" | grep -qw "$TOOL"; then
  echo "Error: unsupported tool '$TOOL'. Supported: $SUPPORTED_TOOLS"
  exit 1
fi

# Default CMD from the tool adapter if not overridden
if [[ -z "$CMD" ]]; then
  CMD=$("default_cmd_${TOOL}")
fi

# Where Claude keeps sessions/transcripts: same rule as claude itself. A wrapper
# that sets its own config dir needs CLAUDE_CONFIG_DIR exported for the watcher too.
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

if ! command -v diffity &>/dev/null; then
  echo "Error: diffity not found. Install with: npm install -g diffity"
  exit 1
fi

# Resolve shell aliases/functions to their underlying binary
if ! command -v "$CMD" &>/dev/null; then
  raw=$(zsh -ic "which $CMD" 2>/dev/null | tail -1 || true)
  if [[ "$raw" == *"aliased to "* ]]; then
    resolved=$(echo "$raw" | sed 's/.*aliased to //')
  elif [[ "$raw" == /* ]]; then
    resolved="$raw"
  else
    resolved=""
  fi
  if [[ -n "$resolved" && -x "$resolved" ]]; then
    CMD="$resolved"
  else
    echo "Error: command '$CMD' not found (not in PATH, not a shell alias)"
    exit 1
  fi
fi

# Validate session exists if --session was provided
if [[ -n "$SESSION_ID" ]]; then
  if ! validate_session; then
    echo "Error: session '$SESSION_ID' not found for $TOOL."
    echo "  Make sure the $TOOL session is running in this project directory ($CWD)."
    echo "  Available sessions:"
    list_sessions
    exit 1
  fi
fi

# ── Hash helper (dedup) ──────────────────────────────────────────────────────
compute_hash() {
  if command -v md5 &>/dev/null; then
    echo -n "$1" | md5
  elif command -v md5sum &>/dev/null; then
    echo -n "$1" | md5sum | cut -d' ' -f1
  else
    echo -n "$1" | cksum | cut -d' ' -f1
  fi
}

# ── Cleanup on exit ──────────────────────────────────────────────────────────
kill_tree() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$child"; done
  kill "$1" 2>/dev/null || true
}

cleanup() {
  echo ""
  echo "Stopping watcher..."
  if [[ -n "$AGENT_PID" ]] && kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "Stopping running agent (pid $AGENT_PID)..."
    kill_tree "$AGENT_PID"
  fi
  if [[ "$OWNS_DIFFITY" == "true" && -n "$DIFFITY_PID" ]] && kill -0 "$DIFFITY_PID" 2>/dev/null; then
    echo "Killing diffity (pid $DIFFITY_PID)..."
    kill "$DIFFITY_PID" 2>/dev/null || true
    wait "$DIFFITY_PID" 2>/dev/null || true
  fi
  echo "Done."
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── Start diffity ────────────────────────────────────────────────────────────
OWNS_DIFFITY=false

# Check if diffity is already running for this repo
existing_port=$(diffity list --json 2>/dev/null | python3 -c "
import json, sys, os
cwd = os.path.realpath('$CWD')
for inst in json.load(sys.stdin):
    if os.path.realpath(inst.get('repoRoot','')) == cwd:
        print(inst['port'])
        break
" 2>/dev/null || true)

if [[ -n "$existing_port" ]]; then
  echo "Diffity already running for this repo on port $existing_port"
  port="$existing_port"
else
  echo "Starting diffity --base $REF ..."

  diffity_output=$(mktemp)
  diffity --base "$REF" --no-open > "$diffity_output" 2>&1 &
  DIFFITY_PID=$!
  OWNS_DIFFITY=true

  # Wait for diffity to print the URL (up to 10 seconds)
  port=""
  for i in $(seq 1 20); do
    if grep -qo 'localhost:[0-9]*' "$diffity_output" 2>/dev/null; then
      port=$(grep -o 'localhost:[0-9]*' "$diffity_output" | head -1 | grep -o '[0-9]*$')
      break
    fi
    sleep 0.5
  done
  rm -f "$diffity_output"

  if [[ -z "$port" ]]; then
    echo "Error: diffity failed to start. Check if the ref '$REF' is valid."
    kill "$DIFFITY_PID" 2>/dev/null || true
    exit 1
  fi
fi

echo "Diffity running on port $port"
echo "  → http://localhost:${port}/diff?ref=${REF}"
open "http://localhost:${port}/diff?ref=${REF}" 2>/dev/null || true
echo ""
echo "Watching for comments every ${INTERVAL}s"
echo "  Tool: $TOOL (cmd: $CMD)"
if [[ -n "$SESSION_ID" ]]; then
  echo "  Session: $SESSION_ID (resume mode)"
else
  echo "  Headless mode (cwd: $CWD)"
fi
echo ""
echo "Press Ctrl+C to stop"
echo ""

# ── Pending threads ──────────────────────────────────────────────────────────
# All open threads, as JSON
fetch_open_threads() {
  diffity agent list --status open --json 2>/dev/null || echo "[]"
}

# Open threads that need the agent: the last real comment is the user's, not
# our own reply or status (those mean we're waiting on the user). A comment
# from a different agent (e.g. a separate reviewer) has no marker and still
# counts. $1 = open threads JSON (default: fetch now). On parse failure, fall
# back to the unfiltered list.
fetch_pending_threads() {
  local threads="${1:-$(fetch_open_threads)}"
  echo "$threads" | python3 "$THREADS_PY" pending 2>/dev/null || echo "$threads"
}

# Post "🕒 Queued" on pending threads that arrived while the agent is busy.
# $1 = comma-separated thread ids the running agent is already handling.
post_queued_status() {
  fetch_pending_threads | DT_PORT="$port" BUSY_IDS="$1" DT_QUEUED_MARKER="$DT_QUEUED_MARKER" python3 -c "
import json, os, sys, urllib.request
busy = set(os.environ['BUSY_IDS'].split(','))
marker = os.environ['DT_QUEUED_MARKER']
for t in json.load(sys.stdin):
    comments = t.get('comments') or []
    if t['id'] in busy or (comments and (comments[-1].get('body') or '').startswith(marker)):
        continue
    body = marker + ' 🕒 **Queued** — agent is busy with another comment, will pick this up next.'
    req = urllib.request.Request(
        'http://localhost:%s/api/threads/%s/reply' % (os.environ['DT_PORT'], t['id']), method='POST',
        data=json.dumps({'body': body, 'author': {'name': 'Agent', 'type': 'agent'}}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=3).read()
        print(t['id'][:8])
    except Exception:
        pass
" 2>/dev/null || true
}

# ── Poll loop ────────────────────────────────────────────────────────────────
while true; do
  # Health check: only check PID if we own the diffity process
  if [[ "$OWNS_DIFFITY" == "true" ]]; then
    if ! kill -0 "$DIFFITY_PID" 2>/dev/null; then
      echo "Diffity process died. Exiting."
      exit 1
    fi
  else
    # We didn't start diffity — verify it's still reachable
    if ! diffity agent list --status open --json &>/dev/null; then
      echo "Diffity is no longer reachable. Exiting."
      exit 1
    fi
  fi

  open_threads=$(fetch_open_threads)
  threads=$(fetch_pending_threads "$open_threads")

  if [[ "$threads" == "[]" || -z "$threads" ]]; then
    sleep "$INTERVAL"
    continue
  fi

  current_hash=$(compute_hash "$threads")
  if [[ "$current_hash" == "$LAST_HASH" ]]; then
    sleep "$INTERVAL"
    continue
  fi

  echo "[$(date +%H:%M:%S)] New/changed threads detected — dispatching to $TOOL"
  LAST_HASH="$current_hash"

  # STREAM_FMT posts a live status comment (checklist → "✅ Done") on each of
  # these threads. It carries DT_STATUS_MARKER, so the filter above won't
  # re-dispatch the thread if the agent never replies.
  export DT_PORT="$port" DT_REPLY_MARKER DT_STATUS_MARKER
  DT_THREAD_IDS=$(echo "$threads" | python3 -c "
import json, sys
print(','.join(t['id'] for t in json.load(sys.stdin) if t.get('id')))
" 2>/dev/null || true)
  export DT_THREAD_IDS DT_QUEUED_MARKER
  export DT_THREADS_JSON="$threads"

  # Threads and rules go in as plain text, with watcher status comments
  # removed, so the agent has everything it needs without running
  # `diffity agent list` itself.
  thread_text=$(echo "$open_threads" | python3 "$THREADS_PY" prompt "$DT_THREAD_IDS" 2>/dev/null) \
    || thread_text="Open threads (JSON):
$threads"

  prompt="New diffity review comments. Everything you need is below — do NOT run 'diffity agent list'.

${thread_text}

Rules:
- Reply to EVERY thread under 'Reply to these threads', with: diffity agent reply <id> --body \"${DT_REPLY_MARKER} <answer>\"
  The body MUST start with '${DT_REPLY_MARKER} ' — that's how the watcher knows the thread is answered.
- 'Other open threads' are context only, to spot related comments. Reply there only if what you do in this run also addresses it.
- Change code ONLY when the user explicitly asks ('fix this', 'rename X to Y', 'add X'). Then reply with what you changed (file:line).
- Questions: answer. Suggestions, 'should we…?', nits: give your take and ask before changing anything. Unclear: ask for clarification. Never skip a thread silently.
- NEVER resolve or dismiss threads. Never edit or delete comments starting with '${DT_STATUS_MARKER}' or '${DT_QUEUED_MARKER}' (watcher status).
- Lines starting 'you:' are your earlier replies. Read files as needed for context.
Summarize briefly what you handled."

  # Run the agent in the background so new comments get a "🕒 Queued" status
  # right away instead of silence. Agents still run one at a time.
  dispatch "$prompt" &
  AGENT_PID=$!
  while kill -0 "$AGENT_PID" 2>/dev/null; do
    for q in $(post_queued_status "$DT_THREAD_IDS"); do
      echo "[$(date +%H:%M:%S)] Queued thread $q (agent busy)"
    done
    sleep "$INTERVAL"
  done
  wait "$AGENT_PID" || echo "[$(date +%H:%M:%S)] Warning: dispatch to $TOOL failed (exit $?)"
  AGENT_PID=""

  sleep "$INTERVAL"
done
