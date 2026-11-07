"""difftate's watcher (see difftate-watch.py), as a core and adapters (ADR 0003).

  core/       the Review, the changes, Dispatch and the prompt: no technology
  adapters/   inbound: the command line (cli/) and the review API (with the
              browser viewer); outbound: the stores, the review history, git,
              the coding agents, the terminal
  main.py     the composition root: it picks the adapters, binds them to the
              core's use cases, and runs the command line
"""
