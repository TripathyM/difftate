# difftate shell functions: difftate / dtc (Claude Code), dto (OpenCode).
# Source this file from ~/.zshrc. See README.md in this folder.

# ── difftate ─────────────────────────────────────────────────────────────────
# Starts the watcher (difftate-watch.py): it serves the review and dispatches
# waiting threads to the coding agent. Each run starts a fresh agent session,
# whichever coding agent or account wrote the code.
# Defaults: the base is the repository's default branch (origin/HEAD), --interval 1s.
# The review is kept in the repository's git folder.
#
# Usage:
#   difftate                       # Claude, the branch vs its base
#   dtc                            # same as difftate
#   difftate HEAD~1                # diff last commit
#   difftate HEAD~3                # diff last 3 commits
#   difftate HEAD / staged / unstaged  # uncommitted, staged or unstaged changes
#   (run again while a watcher runs here: it switches that watcher's view and exits)
#   difftate --base develop        # compare against another branch
#   dto                            # opencode
#   difftate --model <model>       # the coding agent's model (default: its own default)
#   difftate --cmd <binary>        # run the coding agent through another command or alias
#   difftate --open herdr          # open the review in Herdr (browser|herdr|both; default $DT_OPEN, else browser)
#
# Your own shortcuts go in ~/.zshrc, e.g. to reply with another account or wrapper:
#   dtcw() { CLAUDE_CONFIG_DIR=~/.claude-work difftate --cmd my-claude-wrapper "$@"; }

# Folder this file lives in, so the repo works from any clone location
_DT_DIR="${${(%):-%x}:A:h}"

_dt_run() {
  local tool="$1" cmd="$2"
  shift 2
  local ref=""
  local extra_args=()
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "--model" || "$1" == "--open" || "$1" == "--base" ]]; then
      extra_args+=("$1" "$2"); shift 2
    elif [[ "$1" == "--cmd" ]]; then
      cmd="$2"; shift 2
    elif [[ "$1" != --* ]]; then
      ref="$1"; shift
    else
      extra_args+=("$1"); shift
    fi
  done

  local ref_args=()
  [[ -n "$ref" ]] && ref_args=(--ref "$ref")
  "$_DT_DIR/difftate-watch.py" --tool "$tool" --cmd "$cmd" "${ref_args[@]}" --interval 1 "${extra_args[@]}"
}

difftate() { _dt_run claude claude "$@"; }
dtc()      { difftate "$@"; }
dto()      { _dt_run opencode opencode "$@"; }
