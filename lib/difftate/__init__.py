"""difftate's watcher (see difftate-watch.py), as a core and adapters (ADR 0003).

  core/       the Review, the changes, Dispatch and the prompt: no technology
  adapters/   inbound: the review API (and the browser viewer); outbound: the
              stores, the review history, git, the coding agents, the terminal
  watcher     the command: options, start-up, Ctrl+C; it picks the adapters
              and polls Dispatch (until main.py, #68)
  changes     the base and the review's branch, from git
  viewer      opening the review in the browser or a Herdr Review tab
"""
