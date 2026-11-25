---
status: accepted
---

# Viewers are built by the reviewer's own agent

Spec: #228. difftate can't write and maintain a viewer for every editor (VS Code, JetBrains, Zed…), and a viewer someone uses every day ends up as their own, with their own keys and layout. So difftate ships the means to build one instead: `difftate --guide` prints, for the installed version, the review API, difftate's **capabilities** (each one with what it is, its calls and its rules, plus one "start here" line), and how to check the work against `difftate demo`, a throwaway review with one example of each capability. A reviewer tells their own coding agent (Claude Code, OpenCode…) "run `difftate --guide`, then build me a difftate viewer for VS Code"; the viewer that comes out lives in their own folder, never in this repository. The browser and the Neovim viewer are **bundled viewers**: they use the same public API as any other viewer and get nothing it can't get. The review API only grows: calls and fields can be added but never renamed or removed, and a test checks each change against a saved schema; a real break would be a new version of the API, beside the old one. This amends ADR 0007, where one pull request could change the review API and the Neovim plugin together.

## Considered options

- **Build and maintain a VS Code viewer ourselves.** Every editor then becomes difftate's job, and it still wouldn't be anyone's own viewer.
- **A recipe for each editor** (a brief for VS Code, another for JetBrains), as Herdr shares mods. Almost all of a recipe is the same for every editor; the part that differs ("built from") is what the reviewer's agent knows better than we could write it.
- **A fixed "must" list of features** every viewer has. It decides for the reviewer what their viewer is; capabilities with rules ("if you use batched mode, offer submit") leave the choice to them.
- **Editor notes for traps someone hit**, and a line asking agents to report them. Nobody would write them, and most viewer problems are the editor's, not difftate's.
- **No API promise**: rebuild a viewer whenever the API changes. Cheaper for us, but every difftate update could break every viewer someone built.
- **The Neovim plugin in a repository of its own.** It would show a break at once, at the cost of two repositories and two pull requests for one feature; the saved schema catches the same break.
- **A call log in the watcher** that flags calls and fields it doesn't know. Deferred until outside viewers actually break.
- **A config of viewer commands** (`viewers.toml`, `--open vscode`). An editor opens itself and its viewer finds the watcher, so a shell alias does the same job; ADR 0009 also has difftate open no host.

## Consequences

- A viewer built this way is opened by the reviewer, not by difftate: they run `difftate` so the watcher runs, then open their editor, and the viewer finds the watcher from `api.json` in the difftate folder of the home. difftate needs a way to start the watcher and open the review without opening a viewer for this, which the spec of ADR 0009 (#201) rejected when no viewer needed it.
- `difftate --guide` and a copy in the repository come from one source, and a test checks that the guide names every call of the API.
- The demo review also serves the hand checks of the bundled viewers.
- A popular viewer can become bundled later, as VS Code may when we build our own from the guide.
