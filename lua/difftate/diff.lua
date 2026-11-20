-- The review API's changeset diff (a unified diff, as `git diff` writes it), read for
-- one thing: where a line of the old side sits in the new file, which is where a
-- thread on a deleted line is drawn.
local M = {}

local function path_of(raw, prefix)
  local path = raw:gsub("\t.*$", "")
  if path == "/dev/null" then
    return nil
  end
  if path:sub(1, 1) == '"' then
    path = path:sub(2, -2)
  end
  return path:sub(1, #prefix) == prefix and path:sub(#prefix + 1) or path
end

--- The files of the diff <text>: { { old = path or nil, new = path or nil, hunks = {...} } }.
--- A hunk: { old_start, old_count, new_start, new_count, body = the lines' first
--- characters: " " (both sides), "-" (old only), "+" (new only) }.
function M.parse(text)
  local files, file, hunk, old_left, new_left = {}, nil, nil, 0, 0
  for line in ((text or "") .. "\n"):gmatch("(.-)\n") do
    if line:sub(1, 11) == "diff --git " then
      file, hunk = { hunks = {} }, nil
      table.insert(files, file)
    elseif file and not hunk and line:sub(1, 4) == "--- " then
      file.old = path_of(line:sub(5), "a/")
    elseif file and not hunk and line:sub(1, 4) == "+++ " then
      file.new = path_of(line:sub(5), "b/")
    elseif file and line:sub(1, 3) == "@@ " then
      local os_, oc, ns, nc = line:match("^@@ %-(%d+),?(%d*) %+(%d+),?(%d*) @@")
      if os_ then
        hunk = { old_start = tonumber(os_), old_count = oc == "" and 1 or tonumber(oc),
                 new_start = tonumber(ns), new_count = nc == "" and 1 or tonumber(nc), body = {} }
        table.insert(file.hunks, hunk)
        old_left, new_left = hunk.old_count, hunk.new_count
      end
    elseif hunk and (old_left > 0 or new_left > 0) then
      local c = line:sub(1, 1)
      if c == "-" and old_left > 0 then
        old_left = old_left - 1
        table.insert(hunk.body, "-")
      elseif c == "+" and new_left > 0 then
        new_left = new_left - 1
        table.insert(hunk.body, "+")
      elseif (c == " " or line == "") and old_left > 0 and new_left > 0 then
        old_left, new_left = old_left - 1, new_left - 1
        table.insert(hunk.body, " ")
      end
    end
  end
  return files
end

--- The file of <files> (parse) whose old path is <path>, or nil.
function M.file_of_old(files, path)
  for _, file in ipairs(files) do
    if file.old == path then
      return file
    end
  end
end

--- The line of the new file that old line <n> of <file> sits under: its own place when
--- the line is still there, and for a deleted line the new line before it (0: at the
--- top of the file), so the thread of a deleted line is drawn where it was deleted.
function M.new_line_of_old(file, n)
  local shift = 0 -- new line number minus old, before the hunk
  for _, hunk in ipairs(file.hunks) do
    -- a hunk with no old lines names the line it follows
    local old_first = hunk.old_count == 0 and hunk.old_start + 1 or hunk.old_start
    local new_first = hunk.new_count == 0 and hunk.new_start + 1 or hunk.new_start
    if n < old_first then
      break
    end
    if n < old_first + hunk.old_count then
      local old, new = old_first, new_first
      for _, c in ipairs(hunk.body) do
        if c == "-" then
          if old == n then
            return new - 1
          end
          old = old + 1
        elseif c == "+" then
          new = new + 1
        else
          if old == n then
            return new
          end
          old, new = old + 1, new + 1
        end
      end
    end
    shift = (new_first + hunk.new_count) - (old_first + hunk.old_count)
  end
  return n + shift
end

return M
