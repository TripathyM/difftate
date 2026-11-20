-- The review's threads drawn in the reviewer's buffers, with extmarks in a namespace of
-- the plugin's own: a sign at the first line of the anchor and virtual lines under
-- its last. Extmarks move with edits, so a thread follows the code before it is
-- saved; a redraw leaves a thread where its extmark is unless the review API
-- placed it on other lines (the file was saved, or the branch moved).
--
-- Additive only (spec #124): it sets no option and no key. Highlight groups are the
-- plugin's own, linked (by default) to the colorscheme's.
local diff = require("difftate.diff")
local threads = require("difftate.threads")

local M = {}

local ns = vim.api.nvim_create_namespace("difftate_threads")
local group = "DifftateThreads"
local DEFAULT_COLUMNS = 80

-- What is drawn: the open review's top folder, its threads (the API's JSON), the files
-- of its diff (for threads on deleted lines), and every drawn thread by buffer
local drawn -- { top, threads, files, expanded, marks = { [buf] = { [thread id] = mark } } }

local LINKS = {
  DifftateBar = "Comment", DifftateHead = "Title", DifftateDim = "Comment", DifftateReviewer = "Identifier",
  DifftateAgent = "String", DifftateNote = "Comment", DifftateBody = "Normal", DifftateDeleted = "DiffDelete",
  DifftateCode = "Comment", DifftateSign = "DiagnosticSignInfo", DifftateNumber = "DiagnosticInfo",
}

local function define_highlights()
  for name, link in pairs(LINKS) do
    vim.api.nvim_set_hl(0, name, { link = link, default = true })
  end
end

local function real(path)
  return vim.uv.fs_realpath(path) or path
end

-- The loaded buffers of files, by real path
local function buffers_by_path()
  local out = {}
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    if vim.api.nvim_buf_is_loaded(buf) and vim.bo[buf].buftype == "" then
      local name = vim.api.nvim_buf_get_name(buf)
      if name ~= "" then
        out[real(name)] = buf
      end
    end
  end
  return out
end

-- The text columns the thread has in <buf>: those of the narrowest window showing it, so
-- that it never needs a sideways scroll
local function columns_of(buf)
  local columns
  for _, win in ipairs(vim.fn.win_findbuf(buf)) do
    if vim.api.nvim_win_get_config(win).relative == "" then
      local info = vim.fn.getwininfo(win)[1]
      local text = vim.api.nvim_win_get_width(win) - (info and info.textoff or 0)
      columns = math.min(columns or text, text)
    end
  end
  return columns or DEFAULT_COLUMNS
end

-- Where the thread is drawn, as the review API places it: { row (1-based, 0: above the
-- first line), first (line of its sign) }, or nil when it is on no line of a file we know
local function placement(thread, top_files)
  local a = thread.anchor
  if not a or thread.inView == false then
    return nil
  end
  if a.side == "old" then
    local file = diff.file_of_old(top_files, a.file)
    if not file or not file.new then
      return nil
    end
    local row = diff.new_line_of_old(file, a.endLine)
    return { path = file.new, row = row, first = math.max(1, row) }
  end
  return { path = a.file, row = a.endLine, first = a.startLine }
end

local function mark_exists(buf, id)
  return id and #vim.api.nvim_buf_get_extmark_by_id(buf, ns, id, {}) > 0
end

local function row_of(buf, id)
  return vim.api.nvim_buf_get_extmark_by_id(buf, ns, id, {})[1]
end

local function clear_buffer(buf)
  if vim.api.nvim_buf_is_valid(buf) then
    vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  end
  if drawn then
    drawn.marks[buf] = nil
  end
end

-- Draw <thread> in <buf> as <where> places it (a redraw keeps where its extmarks are)
local function draw_thread(buf, thread, where, columns)
  local marks = drawn.marks[buf]
  local mark = marks[thread.id]
  local last = vim.api.nvim_buf_line_count(buf)
  local virt_id = mark and mark_exists(buf, mark.virt) and mark.virt or nil
  local sign_id = mark and mark_exists(buf, mark.sign) and mark.sign or nil
  local same_place = virt_id and sign_id and mark.row == where.row and mark.first == where.first
  local row0, first0, above
  if same_place then
    row0, first0, above = row_of(buf, mark.virt), row_of(buf, mark.sign), mark.above
  else
    above = where.row < 1
    row0 = math.min(math.max(where.row, 1), last) - 1
    first0 = math.min(where.first, last) - 1
  end
  local sig = vim.json.encode({ thread, columns, drawn.expanded })
  if same_place and mark.sig == sig then
    return
  end
  mark = mark or {}
  mark.row, mark.first, mark.above, mark.sig = where.row, where.first, above, sig
  mark.virt = vim.api.nvim_buf_set_extmark(buf, ns, row0, 0, {
    id = virt_id,
    virt_lines = threads.virt_lines(thread, columns, drawn.expanded),
    virt_lines_above = above,
    strict = false,
  })
  -- At the lowest priority: the sign of a thread never hides one of git or diagnostics
  mark.sign = vim.api.nvim_buf_set_extmark(buf, ns, first0, 0, {
    id = sign_id,
    sign_text = threads.sign(thread),
    sign_hl_group = "DifftateSign",
    number_hl_group = "DifftateNumber",
    priority = 1,
    strict = false,
  })
  marks[thread.id] = mark
end

--- Draw every thread of the open review in the buffers of its files, again: after a
--- change of the threads, of a window's size, or of the buffers. Threads that went
--- are removed.
function M.redraw()
  if not drawn then
    return
  end
  local buffers = buffers_by_path()
  local wanted = {} -- buf -> { thread id = true }
  for _, thread in ipairs(drawn.threads) do
    local where = placement(thread, drawn.files)
    local buf = where and buffers[real(drawn.top .. "/" .. where.path)]
    if buf then
      drawn.marks[buf] = drawn.marks[buf] or {}
      wanted[buf] = wanted[buf] or {}
      wanted[buf][thread.id] = true
      draw_thread(buf, thread, where, columns_of(buf))
    end
  end
  for buf, marks in pairs(drawn.marks) do
    for id, mark in pairs(marks) do
      if not (wanted[buf] and wanted[buf][id]) then
        for _, extmark in ipairs({ mark.virt, mark.sign }) do
          pcall(vim.api.nvim_buf_del_extmark, buf, ns, extmark)
        end
        marks[id] = nil
      end
    end
  end
end

local scheduled = false
-- Draw again when the main loop is free: a resize or a new window comes in bursts
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

local function watch_the_editor()
  local id = vim.api.nvim_create_augroup(group, { clear = true })
  vim.api.nvim_create_autocmd({ "WinResized", "VimResized", "WinNew", "WinClosed", "BufWinEnter", "BufReadPost" }, {
    group = id,
    callback = redraw_soon,
  })
  vim.api.nvim_create_autocmd({ "BufUnload", "BufWipeout" }, {
    group = id,
    callback = function(event)
      if drawn then
        drawn.marks[event.buf] = nil
      end
    end,
  })
end

--- Draw <thread_list> (the review API's threads of the review of <top>) and, for the
--- threads on deleted lines, the changeset's <diff_text>.
function M.show(top, thread_list, diff_text)
  if not drawn then
    define_highlights()
    drawn = { top = real(top), expanded = false, marks = {} }
    watch_the_editor()
    vim.api.nvim_create_autocmd("ColorScheme", { group = group, callback = define_highlights })
  end
  drawn.threads = thread_list
  drawn.files = diff_text and diff.parse(diff_text) or {}
  M.redraw()
end

--- Remove every thread from every buffer and stop watching.
function M.clear()
  if not drawn then
    return
  end
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    clear_buffer(buf)
  end
  pcall(vim.api.nvim_del_augroup_by_name, group)
  drawn = nil
end

--- Expand every collapsible thread, or collapse them again: whether they are expanded now.
function M.toggle_expanded()
  if not drawn then
    return false
  end
  drawn.expanded = not drawn.expanded
  M.redraw()
  return drawn.expanded
end

--- The threads whose anchor holds the line <line> (1-based) of buffer <buf>, where
--- they are drawn now (an edit moves them): the thread JSON, open ones first.
function M.threads_at(buf, line)
  local found = {}
  for _, thread in ipairs(drawn and drawn.threads or {}) do
    local mark = drawn.marks[buf] and drawn.marks[buf][thread.id]
    if mark and mark_exists(buf, mark.virt) and mark_exists(buf, mark.sign) then
      local last, first = row_of(buf, mark.virt) + 1, row_of(buf, mark.sign) + 1
      if line >= math.min(first, last) and line <= math.max(first, last) then
        table.insert(found, thread)
      end
    end
  end
  local open, closed = {}, {}
  for _, thread in ipairs(found) do
    table.insert(thread.status == "open" and open or closed, thread)
  end
  return vim.list_extend(open, closed)
end

return M
