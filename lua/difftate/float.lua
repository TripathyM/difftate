-- The read float: one thread in full, as a read-only markdown buffer in a float the
-- plugin owns, so the reviewer can yank from it and search it like any text.
--
-- Additive only (spec #124): the float and its buffer are the plugin's own, so their
-- options and its keys (q, <Esc>) are set on them alone. Every option is set with the
-- float as the current window: a FileType autocmd of the reviewer (LazyVim's wraps and
-- spell checks markdown) acts on the current window, which must not be theirs.
local threads = require("difftate.threads")

local M = {}

local MAX_WIDTH = 100
local current -- { win, buf } of the open float

--- Close the float, when one is open.
function M.close()
  local float = current
  current = nil
  if float and vim.api.nvim_win_is_valid(float.win) then
    pcall(vim.api.nvim_win_close, float.win, true)
  end
end

--- Open <thread> in a float and enter it: the code of its anchor is fenced as the language
--- of the file the thread is on.
function M.open(thread)
  M.close()
  local a = thread.anchor
  local width = math.max(30, math.min(MAX_WIDTH, vim.o.columns - 8))
  local max_height = math.max(5, vim.o.lines - 8)
  local file_type = a and vim.filetype.match({ filename = a.file }) or nil
  local lines = threads.markdown(thread, file_type)

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_set_option_value("bufhidden", "wipe", { buf = buf }) -- the float's own buffer: gone with it
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor", style = "minimal", border = "rounded", focusable = true,
    width = width, height = 1, row = math.floor((vim.o.lines - 1 - max_height) / 2), col = math.floor((vim.o.columns - width) / 2),
    title = " thread ", title_pos = "center",
  })
  current = { win = win, buf = buf }
  local function set(name, value)
    vim.api.nvim_set_option_value(name, value, { scope = "local", win = win })
  end
  set("wrap", true)
  set("linebreak", true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.api.nvim_set_option_value("filetype", "markdown", { buf = buf })
  vim.api.nvim_set_option_value("modifiable", false, { buf = buf })
  vim.api.nvim_win_set_height(win, math.min(max_height, math.max(1, vim.api.nvim_win_text_height(win, {}).all)))

  for _, key in ipairs({ "q", "<Esc>" }) do
    vim.keymap.set("n", key, M.close, { buffer = buf, nowait = true, desc = "Close the thread" })
  end
  vim.api.nvim_create_autocmd("WinLeave", { buffer = buf, once = true, callback = function()
    vim.schedule(M.close)
  end })
end

return M
