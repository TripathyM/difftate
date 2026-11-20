-- The init of the Neovim the tests drive (tests/test_neovim_viewer.py): a clean
-- Neovim with only the Neovim viewer and, when DIFFTATE_TEST_GITSIGNS names a
-- gitsigns.nvim checkout, gitsigns. It never reads the reviewer's config: the
-- tests start nvim with -u pointing here and every XDG folder in a temporary one.
--
-- DIFFTATE_TEST_OPTS: the JSON given to require("difftate").setup().
-- DIFFTATE_TEST_EXTRA_RTP: more folders for the runtimepath (a fake which-key).
-- DIFFTATE_TEST_BEFORE: Lua run before setup(), as the reviewer's config would
-- (a key mapped by another plugin).

vim.g.mapleader = " " -- LazyVim's leader
vim.opt.runtimepath:prepend(vim.env.DIFFTATE_ROOT)
for folder in (vim.env.DIFFTATE_TEST_EXTRA_RTP or ""):gmatch("[^,]+") do
  vim.opt.runtimepath:prepend(folder)
end
local gitsigns = vim.env.DIFFTATE_TEST_GITSIGNS
if gitsigns and gitsigns ~= "" then
  vim.opt.runtimepath:prepend(gitsigns)
  require("gitsigns").setup({})
end

-- Options and global keys, for the tests that check the plugin only adds
_G.T = {}
function T.snapshot()
  local options = {}
  for name, info in pairs(vim.api.nvim_get_all_options_info()) do
    if info.scope == "global" or info.global_local then
      options[name] = vim.api.nvim_get_option_value(name, { scope = "global" })
    end
    if info.scope == "win" then
      options["w:" .. name] = vim.api.nvim_get_option_value(name, { win = 0 })
    elseif info.scope == "buf" then
      options["b:" .. name] = vim.api.nvim_get_option_value(name, { buf = 0 })
    end
  end
  local keys = {}
  for _, mode in ipairs({ "n", "x", "o", "i", "c", "t" }) do
    for _, map in ipairs(vim.api.nvim_get_keymap(mode)) do
      keys[mode .. " " .. map.lhs] = map.rhs or tostring(map.callback ~= nil)
    end
  end
  return { options = options, keys = keys }
end

-- Run <code> (a Lua chunk) and answer {"ok", "value"} as JSON, for the test to read
function T.eval(code)
  local chunk, err = loadstring(code)
  if not chunk then
    return vim.json.encode({ ok = false, value = err })
  end
  local ok, value = pcall(chunk)
  if not ok then
    value = tostring(value)
  end
  return vim.json.encode({ ok = ok, value = value })
end

if vim.env.DIFFTATE_TEST_BEFORE then
  assert(loadstring(vim.env.DIFFTATE_TEST_BEFORE))()
end
T.before = T.snapshot()
require("difftate").setup(vim.json.decode(vim.env.DIFFTATE_TEST_OPTS or "{}"))
T.after_setup = T.snapshot()
