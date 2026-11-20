-- Word wrapping to a number of display columns, for the text a thread draws.
local M = {}

local function width(text)
  return vim.fn.strdisplaywidth(text)
end

-- <word> cut into pieces of at most <columns> display columns: a word longer than a
-- line is broken wherever the line ends, as the window itself would
local function pieces(word, columns)
  local out, piece, piece_width = {}, "", 0
  for _, char in ipairs(vim.fn.split(word, "\\zs")) do
    local w = width(char)
    if piece_width + w > columns and piece ~= "" then
      table.insert(out, piece)
      piece, piece_width = "", 0
    end
    piece, piece_width = piece .. char, piece_width + w
  end
  table.insert(out, piece)
  return out
end

-- One line of text as lines of at most <columns> columns. Its indentation stays on
-- every line (a list or a quoted line wraps under itself); spaces between words are
-- single, as the reader sees them wrapped.
local function wrap_line(line, columns)
  local indent = line:match("^ *")
  local room = math.max(1, columns - #indent)
  local out, current, current_width = {}, "", 0
  for word in line:gmatch("%S+") do
    for _, piece in ipairs(width(word) > room and pieces(word, room) or { word }) do
      local w = width(piece)
      if current ~= "" and current_width + 1 + w > room then
        table.insert(out, indent .. current)
        current, current_width = "", 0
      end
      if current == "" then
        current, current_width = piece, w
      else
        current, current_width = current .. " " .. piece, current_width + 1 + w
      end
    end
  end
  table.insert(out, indent .. current)
  return out
end

--- <text> as lines of at most <columns> display columns. Line breaks stay, blank
--- lines too; a tab counts as two spaces.
function M.wrap(text, columns)
  local out = {}
  for _, line in ipairs(vim.split((text or ""):gsub("\r", ""):gsub("\t", "  "), "\n", { plain = true })) do
    vim.list_extend(out, wrap_line(line, columns))
  end
  return out
end

--- <text> cut to at most <columns> display columns, with … where it was cut.
function M.truncate(text, columns)
  if width(text) <= columns then
    return text
  end
  local cut = pieces(text, math.max(1, columns - 1))[1]
  return vim.trim(cut) .. "…"
end

return M
