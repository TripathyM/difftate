-- The columns a buffer's drawings have: those of the narrowest window showing it.
local M = {}

M.DEFAULT = 80

-- The windows to measure <buf> by: those showing it in this tab page (any tab page, when it isn't
-- shown here), without floats
local function windows_of(buf)
  local here = vim.api.nvim_tabpage_list_wins(0)
  local shown = vim.fn.win_findbuf(buf)
  local nearby = vim.tbl_filter(function(win)
    return vim.tbl_contains(here, win)
  end, shown)
  return vim.tbl_filter(function(win)
    return vim.api.nvim_win_get_config(win).relative == ""
  end, #nearby > 0 and nearby or shown)
end

--- The text columns of <buf>: those of its narrowest window, so that a drawing never needs a
--- sideways scroll.
function M.of(buf)
  local columns
  for _, win in ipairs(windows_of(buf)) do
    local info = vim.fn.getwininfo(win)[1]
    local text = vim.api.nvim_win_get_width(win) - (info and info.textoff or 0)
    columns = math.min(columns or text, text)
  end
  return columns or M.DEFAULT
end

--- The width of the narrowest window of <buf>, signs and numbers included: a line drawn this
--- wide fills the window's rows whatever its sign column is now.
function M.width_of(buf)
  local width
  for _, win in ipairs(windows_of(buf)) do
    width = math.min(width or vim.api.nvim_win_get_width(win), vim.api.nvim_win_get_width(win))
  end
  return width or M.DEFAULT
end

return M
