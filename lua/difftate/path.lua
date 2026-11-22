-- The review path's drawing (GLOSSARY.md, Review path): the rows of the changed files picker
-- when the coding agent wrote a review path. One entry point, M.entries, turns what
-- GET /api/review-path answers into rows, so a pane or virtual lines can replace the
-- picker later without touching the rest. Pure: no editor.
local nav = require("difftate.nav")

local M = {}

-- The row of <stop> ({ number, file, viewed, questions }): "✓ 1 util.py · What does shout do?"
local function stop_row(stop)
  local first = stop.questions and stop.questions[1]
  return ("%s%s %s%s"):format(stop.viewed and "✓ " or "  ", stop.number, stop.file,
    first and (" · " .. first.question) or "")
end

--- The entries of the changed files picker ({ { text, value } }, value a file of
--- nav.files) for the review path <path> (the "path" of GET /api/review-path) over the
--- changeset's <files>, <viewed> { [path] = true }: a row per stop in reading order,
--- then the changed files the path doesn't name, in the changeset's order. A file the
--- path skips on purpose is left out.
function M.entries(path, files, viewed)
  local by_path, named = {}, {}
  for _, file in ipairs(files) do
    by_path[file.path] = file
  end
  local entries = {}
  for _, stop in ipairs(path.stops or {}) do
    named[stop.file] = true
    table.insert(entries, { text = stop_row(stop), value = by_path[stop.file] or { path = stop.file } })
  end
  for _, skipped in ipairs(path.skipped or {}) do
    named[skipped.file] = true
  end
  for _, file in ipairs(files) do
    if not named[file.path] then
      table.insert(entries, { text = nav.file_row(file, viewed[file.path]), value = file })
    end
  end
  return entries
end

return M
