-- gitsigns' base: the one thing the Neovim viewer changes that it doesn't own (spec #124,
-- Additive only). While a review is open, every buffer's base is where the branch left
-- the review's base, so the reviewer's own hunk keys move through the changeset. On
-- close it goes back to the base gitsigns had before (the index, unless the reviewer
-- set another), exactly.
local M = {}

local before -- { base = gitsigns' base before the review } while the review changed it

local function gitsigns()
  local ok, gs = pcall(require, "gitsigns")
  return ok and gs or nil
end

-- The base gitsigns diffs new buffers against: nil for the index
local function base_now()
  local ok, config = pcall(require, "gitsigns.config")
  return ok and config.config and config.config.base or nil
end

--- Point gitsigns at <commit> in every buffer, and in buffers opened later. False
--- when gitsigns isn't there.
function M.point_at(commit)
  local gs = gitsigns()
  if not gs then
    return false
  end
  if not before then
    before = { base = base_now() }
  end
  gs.change_base(commit, true)
  return true
end

--- Put gitsigns' base back as it was before point_at, when it changed it.
function M.restore()
  if not before then
    return
  end
  local base = before.base
  before = nil
  local gs = gitsigns()
  if gs then
    gs.change_base(base, true) -- no base: gitsigns' reset_base, the index
  end
end

return M
