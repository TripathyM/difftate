---
status: accepted
---

# Reviews happen in the reviewer's own editor

The Herdr viewer imitates Vim inside a Herdr mod, so every motion, picker and jump the reviewer uses in their LazyVim had to be rebuilt there, and some never were. Instead, the reviewer reviews in their own Neovim: the Neovim viewer, a Lua plugin that talks to the review API like any other viewer. It works on the real files, not a diff it draws. gitsigns, which LazyVim ships, compares against the review's base (`git merge-base <base> HEAD`), so the reviewer's own hunk keys move through the changeset. Threads are drawn under their anchors as virtual lines, in full like a pull request page, and comments are written in a floating markdown buffer. The Herdr viewer is frozen; Herdr stays as the host, and the `Review · <folder>` tab that `difftate --open herdr` and the review board open now runs `nvim` with the review open.

## Considered options

- **Teach the Herdr viewer more LazyVim keys.** It never catches up with the reviewer's config, plugins and LSP, and it keeps the review tied to one app.
- **Embed Neovim in the Herdr viewer.** Still tied to Herdr, and the Neovim side has to be built anyway.
- **A diff buffer drawn by the plugin**, as the Herdr viewer draws one. Every view fits, but LSP, go to definition and editing don't work in it, because it isn't the file.
- **A side-by-side diff (diffview.nvim, `:diffthis`).** Real buffers on both sides, but it costs screen space and brings its own keys.
- **The plugin draws its own change signs** from the changeset. It would fit every view, but adds a second set of signs and hunk keys beside gitsigns'.
- **Threads in a float or a side panel only.** Easier to build, but the reviewer wanted to read threads in place, as on a pull request.
- **Hunk (hunk.dev)**, a terminal diff viewer for agent review. Another standalone viewer with its own keys and no Neovim plugin, notes that vanish when the window closes, and an extension API that still breaks between minor releases.

## Consequences

- The review opens in Neovim only when the reviewer asks (`<leader>rr`), since gitsigns compares against the base while it is open; coding outside a review keeps gitsigns on the index. While it is open, a note on screen says that git signs show changes since the base. Apart from that switch, the plugin only adds keys and commands that LazyVim's core doesn't use: the reviewer is learning stock LazyVim, and nothing outside a review may differ from its docs.
- The staged-only view doesn't fit: gitsigns always compares the file on disk. It stays in the browser.
- A deleted line is not in any buffer, so the Neovim viewer shows threads on the old side but can't start one there.
- A comment is anchored to the file on disk, so commenting on a buffer with unsaved changes is refused until it is saved.
- The plugin sits at the top level of the repository (`lua/`, `plugin/`) so lazy.nvim can load it from GitHub; one pull request changes the review API and the plugin together.
