# difftate shell functions: difftate / dtc (Claude Code), dto (OpenCode).
# Source this file from ~/.zshrc. See README.md in this folder.

# ── difftate ─────────────────────────────────────────────────────────────────
# Polls diffity for review comments and dispatches to an AI coding session.
# Defaults: --ref master, --interval 1s. Auto-attaches latest session.
#
# Usage:
#   difftate                       # Claude, diff vs master (default) + auto-attach session
#   dtc                            # same as difftate
#   difftate HEAD~1                # diff last commit
#   difftate HEAD~3                # diff last 3 commits
#   dto                            # opencode + auto-attach latest session
#   difftate --session <uuid>      # use a specific session (skip auto-detect)
#   difftate --no-session          # force headless (skip auto-detect)
#   difftate --model <model>       # force the agent's model (default: session's model)
#   difftate --cmd <binary>        # run the agent through another command or alias
#
# Claude sessions are looked up in $CLAUDE_CONFIG_DIR (default ~/.claude).
# Your own shortcuts go in ~/.zshrc, e.g. for a wrapper with its own config:
#   dtcw() { CLAUDE_CONFIG_DIR=~/.claude-work difftate --cmd my-claude-wrapper "$@"; }
#
# Helpers:
#   _dt_latest_claude_session      # prints latest session UUID for cwd
#   _dt_latest_opencode_session    # prints latest opencode session ID

# Folder this file lives in, so the repo works from any clone location
_DT_DIR="${${(%):-%x}:A:h}"

_dt_latest_claude_session() {
  local config_dir="${1:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}"
  # Claude names the folder after the path with every non-alphanumeric char
  # turned into "-" (so ~/.agents → -Users-me--agents)
  local project_hash=$(pwd | sed 's|[^A-Za-z0-9]|-|g')
  local latest=$(ls -t "${config_dir}/projects/${project_hash}/"*.jsonl 2>/dev/null | head -1)
  [[ -n "$latest" ]] && basename "$latest" .jsonl
}

_dt_latest_opencode_session() {
  opencode session list 2>/dev/null | awk 'NR>2 {print $1; exit}'
}

_dt_run() {
  local tool="$1" cmd="$2"
  shift 2
  local ref="master"
  local no_session=false
  local has_explicit_session=false
  local extra_args=()
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--no-session" ]]; then
      no_session=true; shift
    elif [[ "$1" == "--session" ]]; then
      has_explicit_session=true
      extra_args+=("$1" "$2"); shift 2
    elif [[ "$1" == "--model" ]]; then
      extra_args+=("$1" "$2"); shift 2
    elif [[ "$1" == "--cmd" ]]; then
      cmd="$2"; shift 2
    elif [[ "$1" != --* ]]; then
      ref="$1"; shift
    else
      extra_args+=("$1"); shift
    fi
  done

  local session_args=()
  if [[ "$no_session" == "false" && "$has_explicit_session" == "false" ]]; then
    local session_id=""
    case "$tool" in
      claude)
        session_id=$(_dt_latest_claude_session)
        ;;
      opencode) session_id=$(_dt_latest_opencode_session) ;;
    esac
    if [[ -n "$session_id" ]]; then
      echo "Auto-attached session: $session_id"
      session_args=(--session "$session_id")
    else
      echo "No session found — running headless"
    fi
  fi

  "$_DT_DIR/difftate-watch.sh" --tool "$tool" --cmd "$cmd" --ref "$ref" --interval 1 "${session_args[@]}" "${extra_args[@]}"
}

difftate() { _dt_run claude claude "$@"; }
dtc()      { difftate "$@"; }
dto()      { _dt_run opencode opencode "$@"; }
