---
status: accepted
---

# The core knows no technology: ports and adapters

difftate's rules were mixed with the technology they run on. The Review called git through `Code`, its rules raised HTTP status codes, threads were the review API's JSON dicts, and Dispatch started processes and printed to the terminal. So difftate is split into a core and adapters, as hexagonal architecture (ports and adapters) describes. The core holds the Review, a thread following its code, Dispatch, the prompt and the review history. It reaches everything else only through ports that it defines in GLOSSARY words. Adapters plug a technology into a port, and `main.py` is the one place that picks them. We do this to learn the pattern on real code, to test the core with fakes instead of a real repository and real processes, and so that a new store, coding agent or viewer is one new adapter with no change to the core.

## The shape

Ports. Driving (they call the core): **for reviewing** (the reviewer, through a viewer) and **for running the loop** (the timer). Driven (the core calls them): **for keeping the review**, **for recording review history**, **for reading the code**, **for asking the coding agent** and **for reporting**.

```
lib/difftate/
├── core/                    review/, changes/, dispatch/: each has model.py, ports.py
│                            and use_cases/ (one file per use case)
├── adapters/inbound/        review_api/, cli/
├── adapters/outbound/       local_store/, memory_store/, history_files/, git/, terminal/,
│                            coding_agents/ (claude_code/, opencode/, reply_channel/)
└── main.py                  the composition root: builds the adapters and wires the ports
```

- Nothing in `core/` imports `adapters/`, `subprocess` or `http`, or prints. A test checks this.
- Threads, comments, anchors and runs are types in the core. The JSON thread format belongs to the `review_api` adapter. Core errors (such as not allowed, not found, conflict) replace HTTP status codes, and `review_api` maps them to 403, 404 and 409.
- A use case is one plain function in its own file, and it takes only the ports it needs. `main.py` binds the ports. There is no interface or command class per use case: the function is the driving port.
- Ports are `typing.Protocol` classes.

Background: `docs/research/hexagonal-architecture.md`.

## Considered options

- **One folder per context, with its adapters inside it** (`review/`, `changes/`, `dispatch/`, each with its own model, ports and adapters). Each domain is one folder, which we like, and we expect to move to it later. Not now: the review API serves all three contexts, so it would sit outside them as an exception. The move changes no core file: each adapter folder moves into its context.
- **One use-case file per actor** (`for_reviewing.py`, `for_running_the_loop.py`). Fewer files, but a use case is found by searching inside a file, not by its file name, and one file changes for several use cases.
- **Hombergs' layout as in *Get Your Hands Dirty on Clean Architecture***: an interface, a command and a service class per use case, and narrow driven ports. About 54 files for 13 use cases, each interface with one implementation. Too much ceremony for now.
- **Clean architecture's rings as folders** (`entities/`, `use_cases/`, `interface_adapters/`, `frameworks/`). Four layers for about 2,900 lines.

## Consequences

- The coding agent's adapter reads its own event stream and reports steps, replies and the end of the run to Dispatch. Dispatch writes the progress notes through the Review. `stream_fmt.py` no longer edits notes through the review API, so it no longer gets the token. This narrows ADR 0001, which says Dispatch and the coding agent reach the review only through the review API: inside the watcher process they reach it through the core's use cases, and the review API is for what runs outside it (viewers, scripts).
- Each coding agent is one adapter folder: its command line, event stream format, agent session lookup and sandbox settings. Before, these were spread over `agent.py`, `stream_fmt.py` and `difftate.zsh`.
- The review history has its own port, so every store gets it. Before, it was inside the local store.
- The work goes slice by slice. Each pull request keeps difftate working and `tests/test_watcher.py` passing. The first slice is opening a thread, end to end.
