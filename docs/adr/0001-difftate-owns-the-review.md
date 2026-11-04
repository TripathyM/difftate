---
status: accepted
---

# difftate owns the review; diffity is one store behind an adapter

The review (threads, comments, replies, notes and thread state) was diffity's data: the watcher, the progress code, the agent's prompt and the Review tab each read and wrote it in diffity's own format. diffity 0.9.5 is a dead end (later releases dropped the browser UI), and its model doesn't fit difftate: a review ends at each commit, and only a text prefix tells a reply from a comment. So difftate owns the review model. Every other part (Dispatch, the agent, every viewer) reaches it only through difftate's published language: a local HTTP API that the watcher serves while a review runs, with a JSON thread format. Viewers call the API with a token that only they can read; the agent and scripts use the `difftate review` command, which runs the same operations. diffity sits behind an anti-corruption layer as one store, next to a memory store for tests and, later, difftate's own store.

## Considered options

- **An adapter inside the watcher only** (issue #1 as first written). It worked with one viewer. With the Review tab, every viewer would need its own copy of every store.
- **diffity's HTTP API as difftate's contract.** No code now, but every future store would have to copy an abandoned API, with its flaws.
- **A command only, with an HTTP server later.** Less to build first, but difftate's own browser viewer can't run a command, so the Review tab would move twice: from diffity to the command, then to the server. The watcher already runs for the whole review, so serving from it adds no process.

## Consequences

- diffity is transitional. The design aims at a difftate that doesn't need diffity at all: nothing outside its adapter may depend on it, and the diffity adapter is removed once difftate's own store and viewers replace it. (Done in #26: the local store is the only store, next to the memory store for tests, and difftate's own browser viewer the only browser viewer.)
- The browser viewer is diffity's own UI. We can't change it, so it works only with the diffity store. (Since #25, the watcher also serves difftate's own browser viewer for difftate's own store; diffity's UI stays only as long as the diffity store. Removed with it in #26.)
- A browser page can't read the token file, and a link with the token would leave it in the browser's history, where the coding agent can read it. So the watcher opens difftate's page with a single-use launch code instead; the first visit trades it for an HttpOnly, SameSite=Strict cookie (not the token) and redirects to a clean URL. The page then calls the API with that cookie and its own header, so a used link and the browser's history give nothing.
- The agent writes only replies, through `dt-reply`. It no longer needs write access to diffity's data, so with Claude's sandbox on it can't resolve threads or edit notes.
