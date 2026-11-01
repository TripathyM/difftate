"""difftate's Python watcher (opt-in with DT_WATCHER=python; see difftate-watch.py).

Modules follow the contexts in GLOSSARY.md and ADR 0001:
  watcher   the command: options, start-up, Ctrl+C
  api       the review API that viewers and the progress notes use
  review    the Review: the thread rules and thread state, over a store
  store     the store port and difftate's thread format
  diffity   the diffity store (an anti-corruption layer over diffity 0.9.5)
  memory    the memory store (tests)
  dispatch  the loop: waiting threads, queued notes, one run at a time
  prompt    the prompt for one run
  agent     Claude Code and OpenCode: sessions, models, the command line
  viewer    opening the review in the browser or a Herdr Review tab
  procs     starting and stopping process trees
"""
