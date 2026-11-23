-- The Neovim viewer (GLOSSARY.md): difftate's review in the reviewer's own Neovim
-- (ADR 0007). A client of the review API, like the browser viewer.
--
-- Modules: agent (who replies, as text), done (Done, as text), export (the export, as text), view (the view, as text), review
-- (the open review: opening, polling, closing, writing), api (the review API through curl), mode (the review mode and Submit, as text), look (the deleted text and
-- the tint of the diff), compose (the float comments are written in), gitsigns (its base
-- while the review is open), git, draw (the threads in the buffers), threads (their text),
-- wrap, diff (the changeset's diff),
-- float (the read float), nav (the order of the threads, the rows of the pickers), review_path (the
-- review path's rows in the changed files picker), pick (Snacks.picker or vim.ui.select; the files sidebar is Snacks only).
--
-- Additive only (spec #124): it maps only the keys in opts.keys, never one that is
-- mapped already, and sets no option. Keys are under <leader>r, which LazyVim's core
-- doesn't use (only its refactoring extra does: pick other keys with it), and ]r and [r,
-- which neither LazyVim nor its default plugins map.
local review = require("difftate.review")

local M = {}

local defaults = {
  -- How often the open review asks the review API
  poll_ms = 2000,
  -- How the review draws what changed against its base (from gitsigns' hunks, in the plugin's own
  -- namespace): the deleted text is always drawn where it was; tint = false leaves the added and
  -- changed lines untinted, to use gitsigns' own (:Gitsigns toggle_linehl) instead
  diff = { tint = true },
  -- action = key (false: none). Later actions (comment, ...) come here too.
  keys = {
    toggle = "<leader>rr",
    expand = "<leader>re",
    thread = "<leader>rt",
    comment = "<leader>rc", -- on the line, or on the visual selection
    add_comment = "<leader>ra", -- a comment in the thread on the line
    resolve = "<leader>rR",
    reopen = "<leader>rO",
    general = "<leader>rG",
    threads = "<leader>rs", -- the threads picker
    files = "<leader>rf", -- the changed files picker
    files_sidebar = "<leader>rF", -- the changed files sidebar on the right: hidden when a review opens; this shows or hides it
    next = "]r", -- the next open thread
    previous = "[r",
    mode = "<leader>rM", -- switch the review between live and batched
    agent = "<leader>rA", -- choose the agent that replies in this review, from the machine's list
    submit = "<leader>rS", -- submit the held threads of a batched review
    done = "<leader>rD", -- mark the review Done at the branch's commit, or undo it
    export = "<leader>rE", -- copy the review's export to the clipboard, for an agent session
    views = "<leader>rV", -- choose the view: all changes, the last commits, uncommitted, unstaged
    viewed = "<leader>rv", -- mark the current file viewed, or not
    browser = "<leader>rB", -- open this folder's review in the browser (a single-use link)
    side_by_side = "<leader>rd", -- the file in this window side by side with its base (gitsigns' diffthis), or back
  },
}

-- What each key does: { function, description, modes } (modes: where it is mapped, "n" when none)
local actions = {
  toggle = { function() M.toggle() end, "Open or close the review" },
  expand = { function() review.toggle_expanded() end, "Expand or collapse all threads" },
  thread = { function() review.read_thread() end, "Read the thread on this line" },
  comment = {
    { n = function() review.comment(false) end, x = function() review.comment(true) end },
    "Comment on this line or selection", { "n", "x" },
  },
  add_comment = { function() review.add_comment() end, "Comment on the thread" },
  resolve = { function() review.set_status("resolved") end, "Resolve the thread on this line" },
  reopen = { function() review.set_status("open") end, "Reopen the thread on this line" },
  general = { function() review.general() end, "Write a general thread" },
  threads = { function() review.pick_thread() end, "Pick a thread of the review" },
  files = { function() review.pick_file() end, "Pick a changed file" },
  files_sidebar = { function() review.toggle_files_sidebar() end, "Show or hide the changed files sidebar" },
  next = { function() review.step_thread(1) end, "Next open thread" },
  previous = { function() review.step_thread(-1) end, "Previous open thread" },
  mode = { function() review.toggle_mode() end, "Switch the review between live and batched" },
  agent = { function() review.pick_agent() end, "Choose the agent that replies in this review" },
  submit = { function() review.submit() end, "Submit the held threads" },
  done = { function() review.toggle_done() end, "Mark the review Done, or undo it" },
  export = { function() review.export() end, "Copy the review's export for an agent session" },
  views = { function() review.pick_view() end, "Choose the view of the review" },
  viewed = { function() review.toggle_viewed() end, "Mark this file viewed, or not" },
  browser = { function() review.browser(vim.fn.getcwd()) end, "Open the review in the browser" },
  side_by_side = { function() review.toggle_side_by_side() end, "Compare this file with its base side by side, or back" },
}

M.config = vim.deepcopy(defaults)

local mapped = {} -- the keys setup() mapped: { lhs, mode }

local function say(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "difftate" })
end

local function map_keys(keys)
  for _, key in ipairs(mapped) do
    pcall(vim.keymap.del, key.mode, key.lhs)
  end
  mapped = {}
  for name, lhs in pairs(keys) do
    local action = actions[name]
    if action and lhs then
      -- Each mode is checked on its own: a key another plugin took in one mode stays theirs there
      for _, mode in ipairs(action[3] or { "n" }) do
        local taken = vim.fn.maparg(lhs, mode, false, true)
        if taken.lhs then
          say(("%s is already mapped (%s): set opts.keys.%s to another key"):format(
            lhs, taken.desc or taken.rhs or "a function", name), vim.log.levels.WARN)
        else
          local run = type(action[1]) == "table" and action[1][mode] or action[1]
          vim.keymap.set(mode, lhs, run, { desc = action[2] })
          table.insert(mapped, { lhs = lhs, mode = mode })
        end
      end
    end
  end
end

local GROUP = "<leader>r"

-- The "review" group in which-key, once which-key is there, when a key is mapped
-- under it (else the prefix may be another plugin's group). Under lazy.nvim
-- which-key loads at VeryLazy: wait for it rather than load it early.
local function add_which_key_group()
  local under = vim.tbl_filter(function(key)
    return vim.startswith(key.lhs, GROUP)
  end, mapped)
  if #under == 0 then
    return
  end
  local function add()
    local ok, wk = pcall(require, "which-key")
    if ok and type(wk.add) == "function" then
      wk.add({ { GROUP, group = "review", mode = { "n", "x" } } })
    end
  end
  if package.loaded["lazy"] and vim.v.vim_did_enter == 0 then
    vim.api.nvim_create_autocmd("User", { pattern = "VeryLazy", once = true, callback = function()
      vim.schedule(add)
    end })
  else
    add()
  end
end

--- Set the plugin up with <opts> (lazy.nvim passes a spec's `opts` here).
function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", vim.deepcopy(defaults), opts or {})
  map_keys(M.config.keys)
  add_which_key_group()
end

--- Open the review of the folder Neovim is in (:DifftateOpen).
function M.open()
  review.open(vim.fn.getcwd(), M.config)
end

--- Close the open review (:DifftateClose).
function M.close()
  review.close()
end

--- Open the review, or close it when it is open (<leader>rr).
function M.toggle()
  if review.is_open() then
    M.close()
  else
    M.open()
  end
end

--- Say whether the review is open (:DifftateStatus), for a statusline without the note.
function M.say_status()
  review.say_status()
end

--- The note a statusline shows while the review is open; "" when none is.
function M.status()
  return review.status()
end

return M
