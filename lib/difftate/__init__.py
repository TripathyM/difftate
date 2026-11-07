"""difftate's watcher (see difftate-watch.py).

Modules follow the contexts in GLOSSARY.md and ADR 0001:
  watcher   the command: options, start-up, Ctrl+C
  api       the review API that viewers and the progress notes use
  review    the Review: the thread rules and thread state, over a store
  store     the store port and difftate's thread format
  memory    the memory store (tests)
  local     the local store: difftate's own, in the git folder, and the review history
  changes   the base, the review's branch and the changeset, from git
  dispatch  the loop: waiting threads, queued notes, one run at a time
  runfolder the run's folder, where dt-reply leaves the coding agent's replies
  prompt    the prompt for one run
  agent     Claude Code and OpenCode: sessions, models, the command line
  viewer    opening the review in the browser or a Herdr Review tab
  procs     starting and stopping process trees

The new shape (ADR 0003, spec #60) grows beside these modules, slice by slice:
  core      the rules with no technology: review, changes, dispatch
  adapters  inbound (review API, command line) and outbound (stores, git, ...)
"""
