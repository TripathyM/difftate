-- The review path's drawing (GLOSSARY.md, Review path): the rows of the changed files picker
-- when the coding agent wrote a review path. One entry point, M.entries, turns what
-- GET /api/review-path answers into rows, so a pane or virtual lines can replace the
-- picker later without touching the rest. It also writes what the picker's preview shows for a
-- row, and the line a row opens at. Pure: no editor.
local nav = require("difftate.nav")

local M = {}

local MARK = { [true] = "✓ ", [false] = "  " }

-- A file the path names that has no changes (in_changeset false): the path is out of date. Its row
-- says so and is coloured DifftateNoChanges; the text matches review_path.js
local NO_CHANGES = " — no changes"
local function gone(entry)
  return entry.in_changeset == false
end
local function no_changes(entry)
  return gone(entry) and NO_CHANGES or ""
end
local function hl_of(entry)
  return gone(entry) and "DifftateNoChanges" or nil
end

-- <path>'s folder, which a row ends with (the picker dims it); nil at the top of the repository
local function folder_of(path)
  local _, folder = nav.name_and_folder(path)
  return folder ~= "" and folder or nil
end

-- A row: the viewed mark, the tree's drawing (<prefix>), then <label>.
local function row(viewed, prefix, label)
  return MARK[viewed and true or false] .. prefix .. label
end

-- "5-6" or "5-6, 9": the ranges ({ { first, last } }) of a stop or a side file, "" for none
local function ranges_text(ranges)
  local parts = {}
  for _, r in ipairs(ranges or {}) do
    table.insert(parts, r[1] == r[2] and tostring(r[1]) or ("%d-%d"):format(r[1], r[2]))
  end
  return table.concat(parts, ", ")
end

local function lines_note(ranges)
  local text = ranges_text(ranges)
  return text == "" and "" or ("lines " .. text)
end

-- The text of <stop> in the preview: its heading, ranges, questions with their answers, specs, side
-- files, and the path sections it points to, in markdown
local function stop_preview(stop, sections)
  local out = { ("# %s %s%s"):format(stop.number, stop.file, stop.key and " ★" or "") }
  local note = lines_note(stop.ranges)
  if note ~= "" then
    table.insert(out, (note:gsub("^l", "L")))
  end
  for _, q in ipairs(stop.questions or {}) do
    vim.list_extend(out, { "", "## " .. q.question, q.answer })
  end
  if #(stop.specs or {}) > 0 then
    table.insert(out, "")
    table.insert(out, "## " .. (#stop.specs > 1 and "Specs" or "Spec"))
    for _, spec in ipairs(stop.specs) do
      table.insert(out, "- " .. spec.file .. (spec.name ~= "" and (' "' .. spec.name .. '"') or ""))
    end
  end
  if #(stop.side_files or {}) > 0 then
    table.insert(out, "")
    table.insert(out, "## " .. (#stop.side_files > 1 and "Side files" or "Side file"))
    for _, side in ipairs(stop.side_files) do
      local range = lines_note(side.ranges)
      table.insert(out, "- " .. side.file .. (range ~= "" and (" (" .. range .. ")") or "")
        .. ((side.text or "") ~= "" and (": " .. side.text:gsub("\n", " ")) or ""))
    end
  end
  for _, name in ipairs(stop.see or {}) do
    local section = sections[name]
    if section then
      vim.list_extend(out, { "", "## " .. section.name, section.text })
    end
  end
  return table.concat(out, "\n")
end

local function side_preview(side, stop)
  local range = lines_note(side.ranges)
  local out = { "# " .. side.file .. (range ~= "" and (" (" .. range .. ")") or ""),
    ("Side file of %s %s"):format(stop.number, stop.file) }
  if (side.text or "") ~= "" then
    vim.list_extend(out, { "", side.text })
  end
  return table.concat(out, "\n")
end

-- The label of <stop> ({ number, file, key }): "1 util.py ★  src". Its questions are the preview's:
-- after a long path they were cut off to a word or two.
local function stop_label(stop)
  local name = nav.name_and_folder(stop.file)
  return nav.with_folder(("%s %s%s%s"):format(stop.number, name, stop.key and " ★" or "", no_changes(stop)), stop.file)
end

--- The entries of the changed files picker ({ { text, folder, value } }, value a file of
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
  -- the file's entry in the changeset (a copy), with <line>: where Enter opens it. A file with no
  -- range opens at its first change.
  local function value_of(path, ranges)
    local file = vim.deepcopy(by_path[path] or { path = path })
    file.line = ranges and ranges[1] and ranges[1][1] or file.first_change
    return file
  end
  local sections = {}
  for _, section in ipairs(written.sections or {}) do
    sections[section.name] = section
  end
  local entries = {}

  -- <stop>'s rows, then its side files' and children's below it, <prefix> being the drawing so far
  local function add_stop(stop, prefix, connector)
    table.insert(entries, { text = row(stop.viewed, prefix .. connector, stop_label(stop)),
      folder = folder_of(stop.file), value = value_of(stop.file, stop.ranges), preview = stop_preview(stop, sections),
      hl = hl_of(stop) })
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
        table.insert(entries, { text = row(item.side.viewed, below .. last,
            nav.with_folder((nav.name_and_folder(item.side.file)) .. no_changes(item.side), item.side.file)),
          folder = folder_of(item.side.file), value = value_of(item.side.file, item.side.ranges),
          preview = side_preview(item.side, stop), hl = hl_of(item.side) })
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
      table.insert(entries, { text = row(item.viewed, i == #items and "└─ " or "├─ ", text_of(item)),
        folder = folder_of(item.value.path), value = item.value, preview = item.preview, hl = item.hl })
    end
  end
  local skipped = {}
  for _, one in ipairs(written.skipped or {}) do
    table.insert(skipped, { value = value_of(one.file), one = one, hl = hl_of(one),
      preview = ("# %s\nSkipped: %s"):format(one.file, one.reason ~= "" and one.reason or "no reason given") })
  end
  add_group("Skipped", skipped, function(item)
    local name = nav.name_and_folder(item.one.file)
    return nav.with_folder(name .. (item.one.reason ~= "" and (" — " .. item.one.reason) or "") .. no_changes(item.one),
      item.one.file)
  end)

  local off = {}
  if written.not_on_the_path then
    for _, path in ipairs(written.not_on_the_path) do
      if by_path[path] then
        table.insert(off, { value = value_of(path), viewed = viewed[path],
          preview = ("# %s\nNot on the review path: the coding agent named it nowhere."):format(path) })
      end
    end
  end
  add_group("Not on the path", off, function(item)
    return nav.file_label(item.value, item.viewed)
  end)
  return entries
end

return M
