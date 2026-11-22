-- The review path's drawing (GLOSSARY.md, Review path): the rows of the changed files picker
-- when the coding agent wrote a review path. One entry point, M.entries, turns what
-- GET /api/review-path answers into rows, so a pane or virtual lines can replace the
-- picker later without touching the rest. Pure: no editor.
local nav = require("difftate.nav")

local M = {}

local MARK = { [true] = "✓ ", [false] = "  " }

-- A row: the viewed mark, the tree's drawing (<prefix>), then <label>.
local function row(viewed, prefix, label)
  return MARK[viewed and true or false] .. prefix .. label
end

-- The label of <stop> ({ number, file, key, questions }): "1 util.py ★ · What does shout do?"
local function stop_label(stop)
  local first = stop.questions and stop.questions[1]
  return ("%s %s%s%s"):format(stop.number, stop.file, stop.key and " ★" or "",
    first and (" · " .. first.question) or "")
end

--- The entries of the changed files picker ({ { text, value } }, value a file of
--- nav.files; none for a heading) for the review path <written> (the "path" of
--- GET /api/review-path) over the changeset's <files>, <viewed> { [path] = true }: the stops in
--- reading order as a tree (side files, then the stops under a stop, below it with ├─ and └─),
--- then a "Skipped" heading with the files the path skips and their reasons, then a "Not on the
--- path" heading with the changed files the path names nowhere, in the changeset's order.
function M.entries(written, files, viewed)
  local by_path = {}
  for _, file in ipairs(files) do
    by_path[file.path] = file
  end
  local function value_of(path)
    return by_path[path] or { path = path }
  end
  local entries = {}

  -- <stop>'s rows, then its side files' and children's below it, <prefix> being the drawing so far
  local function add_stop(stop, prefix, connector)
    table.insert(entries, { text = row(stop.viewed, prefix .. connector, stop_label(stop)), value = value_of(stop.file) })
    local below = prefix .. (connector == "├─ " and "│  " or connector == "└─ " and "   " or "")
    local items = {}
    for _, side in ipairs(stop.side_files or {}) do
      table.insert(items, { side = side })
    end
    for _, child in ipairs(stop.children or {}) do
      table.insert(items, { child = child })
    end
    for i, item in ipairs(items) do
      local last = i == #items and "└─ " or "├─ "
      if item.side then
        table.insert(entries, { text = row(item.side.viewed, below .. last, item.side.file), value = value_of(item.side.file) })
      else
        add_stop(item.child, below, last)
      end
    end
  end
  for _, stop in ipairs(written.stops or {}) do
    add_stop(stop, "", "")
  end

  local function add_group(heading, items, text_of)
    if #items == 0 then
      return
    end
    table.insert(entries, { text = heading })
    for i, item in ipairs(items) do
      table.insert(entries, { text = row(item.viewed, i == #items and "└─ " or "├─ ", text_of(item)), value = item.value })
    end
  end
  local skipped = {}
  for _, one in ipairs(written.skipped or {}) do
    table.insert(skipped, { value = value_of(one.file), one = one })
  end
  add_group("Skipped", skipped, function(item)
    return item.one.file .. (item.one.reason ~= "" and (" — " .. item.one.reason) or "")
  end)

  local off = {}
  if written.not_on_the_path then
    for _, path in ipairs(written.not_on_the_path) do
      if by_path[path] then
        table.insert(off, { value = by_path[path], viewed = viewed[path] })
      end
    end
  end
  add_group("Not on the path", off, function(item)
    return nav.file_label(item.value, item.viewed)
  end)
  return entries
end

return M
