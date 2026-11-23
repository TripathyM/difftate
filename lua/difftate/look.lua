-- What changed against the review's base, drawn in the reviewer's buffers while the review
-- is open, from the hunks gitsigns already has (it compares every buffer with the base the
-- review set): the deleted text as virtual lines where it was, in the delete colour (GitHub's
-- "unified" look), and the added and changed lines tinted. A changed line is its old text
-- deleted and its new text added.
--
-- Additive only (spec #124): it draws in a namespace of its own with highlight groups of its
-- own, and sets no option, no key and nothing in gitsigns (not linehl, word_diff or
-- show_deleted: it only reads get_hunks). The tint is at the lowest priority, so gitsigns'
-- own line highlight (:Gitsigns toggle_linehl, at its sign priority) wins over it when both are on.
local gap = require("difftate.gap")
local width_of = require("difftate.columns").width_of
local highlights = require("difftate.highlights")

local M = {}

local ns = vim.api.nvim_create_namespace("difftate_diff")
local group = "DifftateDiff"
local TEXT_DEBOUNCE_MS = 150

-- What is drawn: the open review's top folder, whether to tint, and the signature of what each
-- buffer shows (so that an unchanged buffer is not drawn again)
local state -- { top, tint, sigs = { [buf] = string } }

local function real(path)
  return vim.uv.fs_realpath(path) or path
end

local function in_review(buf)
  if not (vim.api.nvim_buf_is_loaded(buf) and vim.bo[buf].buftype == "") then
    return false
  end
  local name = vim.api.nvim_buf_get_name(buf)
  return name ~= "" and vim.startswith(real(name), state.top .. "/")
end

-- gitsigns' hunks of <buf>, or nil when it isn't attached (or gitsigns isn't there)
local function hunks_of(buf)
  local ok, gs = pcall(require, "gitsigns")
  if not (ok and type(gs.get_hunks) == "function") then
    return nil
  end
  local got, hunks = pcall(gs.get_hunks, buf)
  return got and hunks or nil
end

-- <text> with its tabs as the spaces the buffer would show (virtual text has no tab stops)
local function expand_tabs(text, tabstop)
  if not text:find("\t", 1, true) then
    return text
  end
  local out, column = {}, 0
  for _, char in ipairs(vim.fn.split(text, "\\zs")) do
    if char == "\t" then
      local spaces = tabstop - column % tabstop
      table.insert(out, (" "):rep(spaces))
      column = column + spaces
    else
      table.insert(out, char)
      column = column + vim.fn.strdisplaywidth(char)
    end
  end
  return table.concat(out)
end

-- The deleted text of <hunk> as virtual lines <width> columns wide, in the delete colour. The
-- window's whole width: what passes its text area is cut off, and the sign column
-- (signcolumn=auto) may widen after the draw, which would leave a stripe at the edge.
local function deleted_lines(hunk, width, tabstop)
  local out = {}
  for _, line in ipairs(hunk.lines or {}) do
    if line:sub(1, 1) == "-" then
      local text = expand_tabs((line:sub(2):gsub("\r$", "")), tabstop)
      local chunks = { { text, "DifftateDeleted" } }
      local room = width - vim.fn.strdisplaywidth(text)
      if room > 0 then
        table.insert(chunks, { (" "):rep(room), "DifftateDeleted" })
      end
      table.insert(out, chunks)
    end
  end
  return out
end

-- Extmarks belong to a buffer, not a window: a buffer shown in any window in diff mode (side by
-- side) gets no look, as Neovim's diff colours and the old text in the other pane show the change.
local function in_diff(buf)
  for _, win in ipairs(vim.fn.win_findbuf(buf)) do
    if vim.wo[win].diff then
      return true
    end
  end
  return false
end

local function draw_buffer(buf)
  local hunks = in_review(buf) and not in_diff(buf) and hunks_of(buf) or {}
  local width, tabstop = width_of(buf), vim.bo[buf].tabstop
  local sig = vim.json.encode({ hunks, width, tabstop, state.tint })
  if state.sigs[buf] == sig then
    return
  end
  state.sigs[buf] = sig
  vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  local last = vim.api.nvim_buf_line_count(buf)
  for _, hunk in ipairs(hunks) do
    local virt = hunk.removed and hunk.removed.count > 0 and deleted_lines(hunk, width, tabstop) or {}
    if #virt > 0 then
      -- Above the line after the change (the first added line), not under the line before it: the
      -- threads of the line before and of the deleted lines are under that one, and virtual lines
      -- of marks at one position come in no promised order. In a gap the order is then the line
      -- before, its threads, the threads on the deleted lines (which quote their code), and this.
      -- After the last line there is no line to be above: under it (the column orders it then).
      local after = (hunk.added.count == 0 and hunk.added.start or hunk.added.start - 1) + 1
      local fits = after <= last
      vim.api.nvim_buf_set_extmark(buf, ns, (fits and after or last) - 1, gap.deleted_text, {
        virt_lines = virt, virt_lines_above = fits, strict = false,
      })
    end
    if state.tint then
      for line = hunk.added.start, hunk.added.start + hunk.added.count - 1 do
        if line >= 1 and line <= last then
          -- The lowest priority: syntax colours and gitsigns' own line highlight sit over it
          vim.api.nvim_buf_set_extmark(buf, ns, line - 1, 0, { line_hl_group = "DifftateAdd", priority = 1, strict = false })
        end
      end
    end
  end
end

--- Draw every buffer of the review again (an unchanged one is left as it is).
function M.redraw()
  if not state then
    return
  end
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_valid(buf) and (in_review(buf) or state.sigs[buf]) then
      draw_buffer(buf)
    end
  end
end

local scheduled = false
local function redraw_soon()
  if scheduled then
    return
  end
  scheduled = true
  vim.schedule(function()
    scheduled = false
    M.redraw()
  end)
end

local waiting = false
-- gitsigns finds a buffer's new hunks a moment after an edit, and says so only when their counts
-- change: look again after it had time to
local function redraw_after_typing()
  if waiting then
    return
  end
  waiting = true
  vim.defer_fn(function()
    waiting = false
    M.redraw()
  end, TEXT_DEBOUNCE_MS)
end

--- Draw the look of the review of <top> (a folder) in its buffers, and keep it drawn as buffers,
--- windows and gitsigns' hunks change, until clear(). <opts>.tint: tint added and changed lines.
function M.show(top, opts)
  M.clear()
  highlights.define()
  state = { top = real(top), tint = not opts or opts.tint ~= false, sigs = {} }
  local id = vim.api.nvim_create_augroup(group, { clear = true })
  vim.api.nvim_create_autocmd({ "WinResized", "VimResized", "WinNew", "WinClosed", "TabEnter", "BufWinEnter",
                                "BufReadPost" }, { group = id, callback = redraw_soon })
  vim.api.nvim_create_autocmd("OptionSet", { group = id, pattern = "diff", callback = redraw_soon })
  vim.api.nvim_create_autocmd("User", { group = id, pattern = "GitSignsUpdate", callback = redraw_soon })
  vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, { group = id, callback = redraw_after_typing })
  vim.api.nvim_create_autocmd("ColorScheme", { group = id, callback = highlights.define })
  vim.api.nvim_create_autocmd({ "BufUnload", "BufWipeout" }, { group = id, callback = function(event)
    if state then
      state.sigs[event.buf] = nil -- a reloaded buffer keeps its extmarks: clear them with the next draw
    end
  end })
  M.redraw()
end

--- Remove the look from every buffer and stop watching.
function M.clear()
  if not state then
    return
  end
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_valid(buf) then
      vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
    end
  end
  pcall(vim.api.nvim_del_augroup_by_name, group)
  state = nil
end

return M
