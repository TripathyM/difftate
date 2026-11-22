-- Moving through a review: the order its threads are visited in (]r, [r) and listed in
-- (the threads picker), and the rows of the pickers. Pure: no editor, so each is
-- tested through the keys that use it. The order (the deleted Herdr viewer's, ADR 0008): general threads first, then the files' threads in the
-- changeset's order and by line.
local diff = require("difftate.diff")
local threads = require("difftate.threads")
local wrap = require("difftate.wrap")

local M = {}

local AFTER_THE_CHANGESET = 1e6
local FIRST_LINE_MAX = 60

local function is_general(thread)
  return thread.anchor == nil
end

--- The files of the changeset (the review API's diff text), in its order:
--- { { path, additions, deletions, deleted } }.
function M.files(diff_text)
  local out = {}
  for _, file in ipairs(diff.parse(diff_text)) do
    local additions, deletions = 0, 0
    for _, hunk in ipairs(file.hunks) do
      for _, c in ipairs(hunk.body) do
        additions = additions + (c == "+" and 1 or 0)
        deletions = deletions + (c == "-" and 1 or 0)
      end
    end
    table.insert(out, { path = file.new or file.old, additions = additions, deletions = deletions,
                        deleted = file.new == nil })
  end
  return out
end

local function order_of(files)
  local order = {}
  for i, file in ipairs(files) do
    order[file.path] = i
  end
  return order
end

-- Sort <items> ({ path, line, index }) as the review reads: changed files first, in
-- the changeset's order, then the others by name; by line inside a file
local function sort_in_review(items, order)
  table.sort(items, function(a, b)
    local oa, ob = order[a.path] or AFTER_THE_CHANGESET, order[b.path] or AFTER_THE_CHANGESET
    if oa ~= ob then
      return oa < ob
    end
    if a.path ~= b.path then
      return a.path < b.path
    end
    if a.line ~= b.line then
      return a.line < b.line
    end
    return a.index < b.index
  end)
end

--- The open threads the motions visit, in review order: general threads first (as the
--- API lists them), then those with a place in a file. <files>: M.files; <where>(thread)
--- is { path, row } where the thread is drawn, or nil when it is on no line (the code on
--- disk is another branch's). Each entry: { thread, path, row } (a general thread has none).
function M.sequence(all, files, where)
  local out, placed = {}, {}
  for index, thread in ipairs(all) do
    if thread.status == "open" then
      if is_general(thread) then
        table.insert(out, { thread = thread })
      else
        local at = where(thread)
        if at then
          table.insert(placed, { thread = thread, path = at.path, line = at.row, index = index, row = at.row })
        end
      end
    end
  end
  sort_in_review(placed, order_of(files))
  return vim.list_extend(out, placed)
end

-- Compare two positions { rank, path, line, index }
local function before(a, b)
  for i = 1, 4 do
    if a[i] ~= b[i] then
      return a[i] < b[i]
    end
  end
  return false
end

--- The entry of <sequence> a step of <direction> (1 or -1) from <here> goes to, and whether
--- it wrapped round: nil when the sequence is empty. <here>: nil (not in the review: start
--- at its first or last thread), { general = id of a general thread } or
--- { path, line, thread = id of the thread last visited, when the cursor is still on it }.
function M.step(sequence, files, here, direction)
  if #sequence == 0 then
    return nil
  end
  if not here then
    return sequence[direction > 0 and 1 or #sequence], false
  end
  local order = order_of(files)
  local function position(entry, i)
    if not entry.path then
      return { -1, "", i, 0 }
    end
    return { order[entry.path] or AFTER_THE_CHANGESET, entry.path, entry.row, i }
  end
  local me
  if here.general then
    local at = 0.5 -- a general thread that is not listed: before them all
    for i, entry in ipairs(sequence) do
      if entry.thread.id == here.general then
        at = i
      end
    end
    me = { -1, "", at, 0 }
  else
    -- Where the cursor is on a line with threads, the thread last visited tells which of them it is
    local index = direction > 0 and math.huge or -math.huge
    for i, entry in ipairs(sequence) do
      if entry.thread.id == here.thread and entry.path == here.path and entry.row == here.line then
        index = i
      end
    end
    me = { order[here.path] or AFTER_THE_CHANGESET, here.path, here.line, index }
  end
  local found
  if direction > 0 then
    for i, entry in ipairs(sequence) do
      if before(me, position(entry, i)) then
        found = entry
        break
      end
    end
    return found or sequence[1], found == nil
  end
  for i = #sequence, 1, -1 do
    if before(position(sequence[i], i), me) then
      found = sequence[i]
      break
    end
  end
  return found or sequence[#sequence], found == nil
end

local function open_first(list)
  local open, closed = {}, {}
  for _, thread in ipairs(list) do
    table.insert(thread.status == "open" and open or closed, thread)
  end
  return vim.list_extend(open, closed)
end

--- Every thread, as the threads picker lists them: the general ones at the top, then
--- those on files in review order; the open ones first in each group.
function M.picker_threads(all, files)
  local general, on_files = {}, {}
  for index, thread in ipairs(all) do
    if is_general(thread) then
      table.insert(general, thread)
    else
      table.insert(on_files, { thread = thread, path = thread.anchor.file, line = thread.anchor.endLine, index = index })
    end
  end
  sort_in_review(on_files, order_of(files))
  return vim.list_extend(open_first(general), open_first(vim.tbl_map(function(item)
    return item.thread
  end, on_files)))
end

local function first_line(thread)
  local first = thread.comments and thread.comments[1] and thread.comments[1].body or ""
  return wrap.truncate(vim.trim(first:match("[^\n]*")), FIRST_LINE_MAX)
end

--- The row of <thread> in the threads picker: "● app.py:2 · open · agent working · Why this?".
function M.thread_row(thread)
  local a = thread.anchor
  local place = "general"
  if a then
    place = a.file .. ":" .. (a.startLine == a.endLine and a.startLine or ("%d-%d"):format(a.startLine, a.endLine))
    if a.side == "old" then
      place = place .. " (deleted)"
    end
  end
  local parts = { place, threads.status_label(thread) }
  if thread.outdated then
    table.insert(parts, "outdated")
  elseif thread.inView == false then
    table.insert(parts, "not in this view")
  end
  table.insert(parts, first_line(thread))
  return threads.sign(thread) .. " " .. table.concat(parts, " · ")
end

--- What a row of the changed files picker says of <file> (M.files): "app.py  +3 −1 · viewed", the
--- viewed mark not included.
function M.file_label(file, viewed)
  return ("%s  +%d −%d%s"):format(file.path, file.additions, file.deletions, viewed and " · viewed" or "")
end

--- The row of <file> in the changed files picker, <viewed> when the reviewer marked it viewed:
--- "✓ app.py  +3 −1 · viewed".
function M.file_row(file, viewed)
  return (viewed and "✓ " or "  ") .. M.file_label(file, viewed)
end

return M
