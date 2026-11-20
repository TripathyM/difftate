-- A stand-in for which-key.nvim in the tests: it keeps what plugins add to it.
local M = { added = {} }

function M.add(spec)
  table.insert(M.added, spec)
end

return M
