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
function T.snapshot(win)
  win = win or 0
  local buf = vim.api.nvim_win_get_buf(win)
  local options = {}
  for name, info in pairs(vim.api.nvim_get_all_options_info()) do
    if info.scope == "global" or info.global_local then
      options[name] = vim.api.nvim_get_option_value(name, { scope = "global" })
    end
    if info.scope == "win" then
      options["w:" .. name] = vim.api.nvim_get_option_value(name, { win = win })
    elseif info.scope == "buf" then
      options["b:" .. name] = vim.api.nvim_get_option_value(name, { buf = buf })
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

-- The virtual lines of one extmark, as { text, width, hls }: <text> without the padding chunk
-- the plugin ends a line with (spaces up to the window's width), <width> with it, <hls> the
-- highlight of every chunk (a list of groups joined with "+")
local function virt_lines_of(details)
  local out = {}
  for _, chunks in ipairs(details.virt_lines) do
    local text, hls, full = {}, {}, {}
    for i, chunk in ipairs(chunks) do
      local hl = type(chunk[2]) == "table" and table.concat(chunk[2], "+") or chunk[2] or ""
      table.insert(full, chunk[1])
      table.insert(hls, hl)
      if not (i >= 2 and i == #chunks and chunk[1]:match("^ *$")) then
        table.insert(text, chunk[1])
      end
    end
    table.insert(out, { text = table.concat(text), width = vim.fn.strdisplaywidth(table.concat(full)), hls = hls })
  end
  return out
end

-- What the plugin drew in buffer <buf>: its virtual lines as text and its signs
function T.drawn(buf)
  local ns = vim.api.nvim_get_namespaces()["difftate_threads"]
  local out = { threads = {}, signs = {} }
  if not ns then
    return out
  end
  for _, m in ipairs(vim.api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true })) do
    local d = m[4]
    if d.virt_lines then
      local lines = {}
      for _, line in ipairs(virt_lines_of(d)) do
        table.insert(lines, line.text)
      end
      table.insert(out.threads, { row = m[2] + 1, above = d.virt_lines_above or false, lines = lines })
    end
    if d.sign_text then
      table.insert(out.signs, { m[2] + 1, vim.trim(d.sign_text) })
    end
  end
  return out
end

-- The boxes of the threads drawn in buffer <buf>: for each, its lines as { width, hls }
function T.boxes(buf)
  local ns = vim.api.nvim_get_namespaces()["difftate_threads"]
  local out = {}
  for _, m in ipairs(ns and vim.api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true }) or {}) do
    if m[4].virt_lines then
      table.insert(out, virt_lines_of(m[4]))
    end
  end
  return out
end

-- The diff look drawn in buffer <buf> (the plugin's namespace difftate_diff): the deleted
-- text as { row (1-based), above, lines, widths, hls, priority } and the tinted lines as { row, hl }
function T.look(buf)
  local ns = vim.api.nvim_get_namespaces()["difftate_diff"]
  local out = { deleted = {}, tinted = {} }
  for _, m in ipairs(ns and vim.api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true }) or {}) do
    local d = m[4]
    if d.virt_lines then
      local lines, widths, hls = {}, {}, {}
      for _, line in ipairs(virt_lines_of(d)) do
        table.insert(lines, line.text)
        table.insert(widths, line.width)
        table.insert(hls, line.hls)
      end
      table.insert(out.deleted, { row = m[2] + 1, above = d.virt_lines_above or false, lines = lines, widths = widths,
                                  hls = hls, priority = d.priority })
    end
    if d.line_hl_group then
      table.insert(out.tinted, { m[2] + 1, d.line_hl_group })
    end
  end
  return out
end

-- The screen's text, one string per row (trailing spaces cut): what the reviewer reads
function T.screen()
  vim.cmd("redraw")
  local rows = {}
  for row = 1, vim.o.lines do
    local text = {}
    for col = 1, vim.o.columns do
      table.insert(text, vim.fn.screenstring(row, col))
    end
    table.insert(rows, (table.concat(text):gsub("%s+$", "")))
  end
  return rows
end

-- Every extmark of buffer <buf> in a namespace that is neither the plugin's nor gitsigns': the
-- plugin must draw in its own namespaces only
function T.foreign_extmarks(buf)
  local out = {}
  for name, ns in pairs(vim.api.nvim_get_namespaces()) do
    if not (vim.startswith(name, "difftate") or vim.startswith(name, "gitsigns")) then
      out[name] = vim.api.nvim_buf_get_extmarks(buf, ns, 0, -1, { details = true })
    end
  end
  return out
end

-- gitsigns' settings that draw the diff itself, and the highlight groups the plugin links to
function T.settings()
  local config = require("gitsigns.config").config
  local hls = {}
  for _, name in ipairs({ "DiffAdd", "DiffDelete", "DiffChange", "NormalFloat", "Normal", "CursorLine" }) do
    hls[name] = vim.api.nvim_get_hl(0, { name = name })
  end
  return { gitsigns = { linehl = config.linehl, numhl = config.numhl, word_diff = config.word_diff,
                        show_deleted = config.show_deleted, signcolumn = config.signcolumn }, hls = hls }
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
