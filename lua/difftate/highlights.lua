-- The plugin's own highlight groups, each linked (by default) to a group of the colorscheme:
-- a colorscheme or a reviewer that sets one itself wins. Nothing here changes a group that
-- is not the plugin's.
local M = {}

local LINKS = {
  DifftateBar = "Comment", DifftateHead = "Title", DifftateDim = "Comment", DifftateReviewer = "Identifier",
  DifftateAgent = "String", DifftateNote = "Comment", DifftateDeleted = "DiffDelete",
  DifftateCode = "Comment", DifftateSign = "DiagnosticSignInfo", DifftateNumber = "DiagnosticInfo",
  -- A thread is a box: its background, and its text on it (the body too: not the code's colour)
  DifftateBox = "NormalFloat", DifftateBody = "NormalFloat",
  -- The tint of added and changed lines
  DifftateAdd = "DiffAdd",
}

function M.define()
  for name, link in pairs(LINKS) do
    vim.api.nvim_set_hl(0, name, { link = link, default = true })
  end
end

return M
