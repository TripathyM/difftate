-- What a thread looks like, as text: the lines drawn under its anchor, the one line it
-- shrinks to, and the markdown of the read float. Thread JSON is the review API's
-- (lib/difftate/adapters/inbound/review_api/json_format.py); the words are the
-- Herdr viewer's (herdr/mods/difftate/batched.js, main.js layoutThread).
local wrap = require("difftate.wrap")

local M = {}

-- Where an open thread stands in the loop (the API's thread state)
local STATE_LABEL = {
  held = "held until you submit", waiting = "waiting for agent", queued = "queued", working = "agent working",
  replied = "agent replied", failed = "failed: no reply",
}

local BAR = "│ "
local INDENT = "  "
local QUOTED_MAX = 8 -- lines of quoted code
local NOTE_MAX = 6 -- lines of a note: its steps while it works can be long
local MIN_COLUMNS = 20

-- Who wrote a comment, as a thread shows it, and how: the reviewer's name (or "reviewer"
-- for a comment written before reviewer names), "agent", or "note" for difftate's own
local function who_of(comment)
  if comment.author == "agent" then
    return "agent", "DifftateAgent"
  elseif comment.author == "difftate" then
    return "note", "DifftateNote"
  end
  return comment.by or "reviewer", "DifftateReviewer"
end

--- Whether the thread is on a deleted line (the old side).
function M.is_old(thread)
  return thread.anchor ~= nil and thread.anchor.side == "old"
end

--- Whether the thread shrinks to one line unless the reviewer expands them all:
--- resolved, dismissed and outdated threads do.
function M.is_collapsible(thread)
  return thread.status ~= "open" or thread.outdated == true
end

--- How many comments and replies the thread holds (notes are not counted).
function M.count(thread)
  local n = 0
  for _, c in ipairs(thread.comments or {}) do
    if c.kind == "comment" or c.kind == "reply" then
      n = n + 1
    end
  end
  return n
end

-- "open · agent working", "resolved by security-bot", "dismissed"
local function status_label(thread)
  if thread.status == "open" then
    return "open · " .. (STATE_LABEL[thread.state or "waiting"] or thread.state or "waiting for agent")
  end
  local by = thread.statusBy and (" by " .. thread.statusBy) or ""
  return thread.status .. by
end

-- "lines 3-5", "deleted line 4", or nil for one line of the new side
local function place(thread)
  local a = thread.anchor
  if not a then
    return nil
  end
  local range = a.startLine == a.endLine and tostring(a.startLine) or ("%d-%d"):format(a.startLine, a.endLine)
  if a.side == "old" then
    return (a.startLine == a.endLine and "deleted line " or "deleted lines ") .. range
  end
  return a.startLine ~= a.endLine and ("lines " .. range) or nil
end

local function head_text(thread)
  local parts = { (thread.status == "open" and "●" or "○") .. " " .. status_label(thread) }
  if thread.outdated then
    table.insert(parts, "outdated")
  end
  table.insert(parts, place(thread))
  return table.concat(parts, " · ")
end

local function plural(n, word)
  return ("%d %s%s"):format(n, word, n == 1 and "" or "s")
end

local function first_words(thread)
  local first = (thread.comments and thread.comments[1] and thread.comments[1].body) or ""
  return vim.trim((first:gsub("%s+", " ")))
end

--- The one line a resolved, dismissed or outdated thread shrinks to, in <columns>:
--- its status, its comment count and the first words of its first comment.
function M.summary(thread, columns)
  local line = ("%s · %s"):format(head_text(thread), plural(M.count(thread), "comment"))
  local words = first_words(thread)
  local room = columns - vim.fn.strdisplaywidth(line) - vim.fn.strdisplaywidth(" · “”")
  if words ~= "" and room >= 8 then
    line = ("%s · “%s”"):format(line, wrap.truncate(words, room))
  end
  return wrap.truncate(line, columns)
end

-- The code of the anchor as quoted lines, with a mark: at most QUOTED_MAX of them
local function quoted(code, mark, columns)
  local out = {}
  local lines = vim.split((code or ""):gsub("\n$", ""), "\n", { plain = true })
  for i, text in ipairs(lines) do
    if i > QUOTED_MAX then
      table.insert(out, { text = ("… %d more lines"):format(#lines - QUOTED_MAX), hl = "DifftateDim" })
      break
    end
    table.insert(out, { text = wrap.truncate(mark .. " " .. text:gsub("\t", "  "), columns),
                        hl = mark == "-" and "DifftateDeleted" or "DifftateCode" })
  end
  return out
end

--- The lines drawn for <thread> in <columns> columns (after the bar): { { text, hl } }.
--- <expanded>: a resolved, dismissed or outdated thread is drawn in full too.
function M.lines(thread, columns, expanded)
  columns = math.max(columns, MIN_COLUMNS)
  if M.is_collapsible(thread) and not expanded then
    return { { text = M.summary(thread, columns), hl = "DifftateDim" } }
  end
  local out = { { text = head_text(thread), hl = thread.status == "open" and "DifftateHead" or "DifftateDim" } }
  local anchor = thread.anchor
  if anchor and anchor.side == "old" and anchor.code then
    vim.list_extend(out, quoted(anchor.code, "-", columns))
  elseif anchor and thread.outdated and anchor.code then
    table.insert(out, { text = "code when written (it changed since)", hl = "DifftateDim" })
    vim.list_extend(out, quoted(anchor.code, ">", columns))
  end
  for _, c in ipairs(thread.comments or {}) do
    local who, hl = who_of(c)
    local body = c.body or ""
    if who == "note" then
      local note = vim.split(body, "\n", { plain = true })
      body = table.concat(vim.list_slice(note, 1, NOTE_MAX), "\n")
      if #note > NOTE_MAX then
        body = body .. ("\n… %d more lines"):format(#note - NOTE_MAX)
      end
    end
    table.insert(out, { text = who, hl = hl })
    for _, text in ipairs(wrap.wrap(body, columns - #INDENT)) do
      table.insert(out, { text = INDENT .. text, hl = hl == "DifftateNote" and "DifftateNote" or "DifftateBody" })
    end
  end
  return out
end

--- <thread>'s virtual lines for an extmark: { { { bar }, { text } } } (a bar, then the line).
function M.virt_lines(thread, columns, expanded)
  local out = {}
  for _, line in ipairs(M.lines(thread, columns - #BAR, expanded)) do
    table.insert(out, { { BAR, "DifftateBar" }, { line.text, line.hl } })
  end
  return out
end

--- The sign text of <thread>: filled while it is open.
function M.sign(thread)
  return thread.status == "open" and "●" or "○"
end

--- The read float's lines: <thread> in full, as markdown. <file_type>: the language of
--- the anchor's code, for its fence.
function M.markdown(thread, file_type)
  local out = { "# " .. head_text(thread) }
  local a = thread.anchor
  if a then
    table.insert(out, "")
    table.insert(out, ("`%s` %s"):format(a.file, a.startLine == a.endLine and ("line " .. a.startLine)
      or ("lines %d-%d"):format(a.startLine, a.endLine)))
  end
  if a and a.code and (thread.outdated or a.side == "old") then
    table.insert(out, "")
    table.insert(out, a.side == "old" and "Deleted code:" or "Code when written (it changed since):")
    table.insert(out, "```" .. (file_type or ""))
    vim.list_extend(out, vim.split((a.code:gsub("\n$", "")), "\n", { plain = true }))
    table.insert(out, "```")
  end
  for _, c in ipairs(thread.comments or {}) do
    local who = who_of(c)
    table.insert(out, "")
    -- "2026-11-20T17:17:31.381Z" is written "2026-11-20 17:17 UTC"
    local day, minute = tostring(c.time or ""):match("^(%d+%-%d+%-%d+)T(%d+:%d+)")
    table.insert(out, "## " .. who .. (day and (" · %s %s UTC"):format(day, minute) or ""))
    table.insert(out, "")
    vim.list_extend(out, vim.split((c.body or ""):gsub("\r", ""), "\n", { plain = true }))
  end
  return out
end

return M
