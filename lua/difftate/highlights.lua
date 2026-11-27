-- The plugin's own highlight groups, each linked (by default) to a group of the colorscheme:
-- a colorscheme or a reviewer that sets one itself wins. Nothing here changes a group that
-- is not the plugin's.
local M = {}

local LINKS = {
  DifftateBar = "Comment", DifftateHead = "Title", DifftateDim = "Comment", DifftateReviewer = "Identifier",
  DifftateAgent = "String", DifftateNote = "Comment", DifftateDeleted = "DiffDelete",
  DifftateCode = "Comment", DifftateSign = "DiagnosticSignInfo", DifftateNumber = "DiagnosticInfo",
  -- The folder a row of the changed files picker ends with, after the file name
  DifftateFolder = "Comment",
  -- A row of the review path whose file has no changes: the path is out of date
  DifftateNoChanges = "DiagnosticError",
  -- The tint of added and changed lines
  DifftateAdd = "DiffAdd",
}

local BOX_TINT = 0.08 -- how much of the info colour is mixed into the box's background

-- <a> mixed with <amount> of <b>, colours as 0xRRGGBB
local function blend(a, b, amount)
  local out = 0
  for shift = 16, 0, -8 do
    local x, y = bit.band(bit.rshift(a, shift), 0xff), bit.band(bit.rshift(b, shift), 0xff)
    out = out + bit.lshift(math.floor(x + (y - x) * amount + 0.5), shift)
  end
  return out
end

-- A thread is a box: a panel on the editor's background with a tint of the colorscheme's
-- info colour, so it does not read as more code. Its body text has a colour only, so the
-- tint shows under it. Without a background to tint (a transparent editor) the box is the
-- colorscheme's float.
local function define_box()
  local normal = vim.api.nvim_get_hl(0, { name = "Normal", link = false })
  local float = vim.api.nvim_get_hl(0, { name = "NormalFloat", link = false })
  local info = vim.api.nvim_get_hl(0, { name = "DiagnosticInfo", link = false })
  if normal.bg and info.fg then
    vim.api.nvim_set_hl(0, "DifftateBox", { bg = blend(normal.bg, info.fg, BOX_TINT), default = true })
  else
    vim.api.nvim_set_hl(0, "DifftateBox", { link = "NormalFloat", default = true })
  end
  vim.api.nvim_set_hl(0, "DifftateBody", { fg = float.fg or normal.fg, default = true })
end

function M.define()
  for name, link in pairs(LINKS) do
    vim.api.nvim_set_hl(0, name, { link = link, default = true })
  end
  define_box()
end

return M
