---
status: accepted
---

# difftate opens no host

difftate opened the Neovim viewer in a Herdr tab whenever Herdr could be reached, so `difftate --open nvim` typed in iTerm opened a tab in Herdr, and difftate carried Herdr code long after the Herdr viewer was deleted (ADR 0008). Now difftate opens no host: `--open nvim` becomes `nvim +DifftateOpen` in the terminal it runs in, whatever that terminal is (iTerm, tmux, a Herdr tab), and with no terminal it prints that command. Where a review goes in a multiplexer is the job of whatever launches it: the review board, a Herdr mod, opens each review in one "Reviews" space, in a tab that runs `difftate --base <base> --open nvim`. This amends ADR 0007 ("Herdr stays as the host") and ADR 0008 (difftate opening the board's Review tab).

Decided while grilling #201 (2026-11-22).

## Considered options

- **A host for each multiplexer in difftate** (Herdr now, tmux next, one branch each): the seam ADR 0007 planned. Every host is code that breaks when that app changes its CLI, and difftate still has to guess which host the reviewer wants, as it guessed wrong from iTerm.
- **The board tells difftate where to open** (`--group Reviews`). The board decides, but difftate keeps all the Herdr code and gains a flag only Herdr uses.
- **difftate always opens in a Reviews space.** The smallest change, but difftate stays tied to Herdr.
- **`--open nvim` only prints the command.** No host either, but the reviewer runs a second command every time.
- **A space for each review**, which Herdr nests under its repository's space. No space to make, but reviews sit among the work spaces again.

## Consequences

- difftate has no Herdr code, setting (`DT_HERDR`, `DT_HC`) or install step. The rule that opens the review again when Neovim has quit (#199) moves to the board.
- `--open both` opens the browser first: once difftate becomes Neovim, nothing after it runs.
- With no `nvim` on PATH, `--open nvim` fails with an error rather than falling back to the browser.
- Typing `difftate --open nvim` in a Herdr terminal opens Neovim in that terminal, not a Review tab: only the board makes Review tabs.
- The board stays a Herdr mod. Another multiplexer would need its own launcher, not a change to difftate.
