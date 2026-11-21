-- Export, as text (GLOSSARY.md: Export). Pure: no editor, no request. The words are the browser viewer's
-- (web/app.js exportReview). <text> is what
-- GET /api/export answers (text/plain).
local M = {}

--- The problem with <text> as an export, or nil: an empty answer (an old watcher, or a proxy) is not one.
function M.problem(text)
  if type(text) == "string" and vim.trim(text) ~= "" then
    return nil
  end
  return "The watcher gave no export (is it up to date?)"
end

--- How many threads the export says need an answer (its "## Threads that need an answer (N)" heading),
--- or nil when it has no such heading.
function M.needing(text)
  local n = text:match("\n## Threads that need an answer %((%d+)%)")
  return n and tonumber(n) or nil
end

--- Said after the export is copied: what it holds that matters, in the words of GLOSSARY.md.
function M.copied_message(text)
  local n = M.needing(text)
  local holds = ""
  if n == 0 then
    holds = " (no thread needs an answer)"
  elseif n == 1 then
    holds = " (1 thread needs an answer)"
  elseif n then
    holds = (" (%d threads need an answer)"):format(n)
  end
  return "Export copied" .. holds .. ": paste it into an agent session"
end

--- Said when no clipboard provider is there and the export went to the unnamed register.
function M.in_register_message()
  return "No system clipboard here: the export is in the unnamed register (paste it with p)"
end

--- Said when the export could not be fetched; <message> is what went wrong.
function M.failed_message(message)
  return "Could not export: " .. tostring(message)
end

return M
