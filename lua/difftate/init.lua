-- The Neovim viewer (GLOSSARY.md): difftate's review in the reviewer's own Neovim
-- (ADR 0007). A client of the review API, like the browser and the Herdr viewer.
--
-- Modules: review (the open review: opening, polling, closing, writing), api (the review
-- API through curl), compose (the float comments are written in), gitsigns (its base while the review is open), git, draw (the
-- threads in the buffers), threads (their text), wrap, diff (the changeset's diff),
-- float (the read float).
--
-- Additive only (spec #124): it maps only the keys in opts.keys, never one that is
-- mapped already, and sets no option. Keys are under <leader>r, which LazyVim's core
-- doesn't use (only its refactoring extra does: pick other keys with it).
local review = require("difftate.review")

local M = {}

local defaults = {
  -- How often the open review asks the review API, as the Herdr viewer does
  poll_ms = 2000,
  -- action = key (false: none). Later actions (comment, reply, ...) come here too.
  keys = {
    toggle = "<leader>rr",
    expand = "<leader>re",
    thread = "<leader>rt",
    comment = "<leader>rc", -- on the line, or on the visual selection
    reply = "<leader>ra",
    resolve = "<leader>rR",
    reopen = "<leader>rO",
    general = "<leader>rG",
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
  reply = { function() review.reply() end, "Reply to the thread on this line" },
  resolve = { function() review.set_status("resolved") end, "Resolve the thread on this line" },
  reopen = { function() review.set_status("open") end, "Reopen the thread on this line" },
  general = { function() review.general() end, "Write a general thread" },
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
