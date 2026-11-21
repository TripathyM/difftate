-- Done, as text (GLOSSARY.md: Done). Pure: no editor, no request. The words are those of the deleted Herdr viewer (ADR 0008). <status> is what GET /api/done answers:
-- { done, commit, time, head, lastMark, openThreads, runsInFlight }.
local M = {}

local function plural(n, one, many)
  return ("%d %s"):format(n, n == 1 and one or many)
end

--- The commit as the reviewer reads it: its first seven characters.
function M.short(commit)
  return (commit or ""):sub(1, 7)
end

--- Whether <status> says the review is Done.
function M.is_done(status)
  return status ~= nil and status.done == true
end

--- What the statusline note says of Done: "Done at 0123456"; nil when it isn't Done or isn't known.
function M.label(status)
  if M.is_done(status) then
    return "Done at " .. M.short(status.commit)
  end
  return nil
end

--- What is still going on in the review: the open threads, and the runs still working; {} when nothing is.
function M.warnings(status)
  local out = {}
  if status and (status.openThreads or 0) > 0 then
    table.insert(out, plural(status.openThreads, "thread", "threads") .. " still open")
  end
  if status and (status.runsInFlight or 0) > 0 then
    table.insert(out, plural(status.runsInFlight, "run", "runs") .. " still working")
  end
  return out
end

--- The question before marking Done, or nil when nothing is open.
function M.question(status)
  local warnings = M.warnings(status)
  if #warnings == 0 then
    return nil
  end
  return table.concat(warnings, " · ") .. ". Mark Done anyway?"
end

--- Said after the review was marked Done.
function M.marked_message(status)
  return ("%s. A new commit clears it."):format(M.label(status) or "Done")
end

--- Said after the reviewer undid Done at <before> (the status it had).
function M.undone_message(before)
  if M.is_done(before) then
    return ("Done at %s undone"):format(M.short(before.commit))
  end
  return "Done undone"
end

return M
