-- The compose float: where the reviewer writes a comment, a reply or a general thread, as
-- a floating markdown buffer the plugin owns, under the lines it is about.
--
-- :w (BufWriteCmd) and <C-s> send the text; q closes the float and keeps the unsent text,
-- which opening the same compose again brings back (the key says which is the same). A
-- failed send keeps the float open with its text, and says why.
--
-- Additive only (spec #124): the float and its buffer are the plugin's own, so their
-- options and keys (q, <C-s>, the write) are set on them alone: LazyVim's global <C-s>
-- (save) stays what it is everywhere else. Every option is set with the float as the
-- current window, since a FileType autocmd of the reviewer (LazyVim's wraps and spell
-- checks markdown) acts on the current window, which must not be theirs.
local M = {}

local MAX_WIDTH = 100
local HEIGHT = 8

local current -- the open float: { win, buf, key, sending, sent }
local drafts = {} -- the text not sent yet, by key: { line, ... }
local count = 0

local function say(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "difftate" })
end

local function blank(lines)
  return vim.trim(table.concat(lines, "\n")) == ""
end

-- Keep the float's text as the unsent text of its key, unless it was sent
local function keep(float)
  if float.sent or not vim.api.nvim_buf_is_valid(float.buf) then
    return
  end
  local lines = vim.api.nvim_buf_get_lines(float.buf, 0, -1, false)
  drafts[float.key] = not blank(lines) and lines or nil
end

--- Close the float, when one is open: what is in it stays as the unsent text.
function M.close()
  local float = current
  current = nil
  if not float then
    return
  end
  keep(float)
  if vim.api.nvim_win_is_valid(float.win) then
    pcall(vim.api.nvim_win_close, float.win, true)
  end
end

--- Whether the compose float is open.
function M.is_open()
  return current ~= nil
end

--- The unsent text of <key> (a list of lines), or nil.
function M.draft(key)
  return drafts[key]
end

-- Where the float goes: under what is drawn under <line> (its threads) of <win>, as
-- { row, col, width, height } in editor cells, kept on the screen
local function place(win, line)
  local columns, rows = vim.o.columns, vim.o.lines
  local info = vim.fn.getwininfo(win)[1]
  local width = math.max(30, math.min(MAX_WIDTH, columns - 4, info.width - info.textoff))
  local height = math.max(3, math.min(HEIGHT, rows - 8))
  local shown = vim.fn.screenpos(win, line, 1)
  local row = shown.row > 0 and (shown.row - 1 + vim.api.nvim_win_text_height(win, { start_row = line - 1, end_row = line - 1 }).all)
    or math.floor((rows - height) / 2)
  local col = info.wincol - 1 + info.textoff
  return {
    row = math.max(0, math.min(row, rows - height - 4)),
    col = math.max(0, math.min(col, columns - width - 2)),
    width = width, height = height,
  }
end

--- Open the compose float and enter it, in insert mode. <opts>: title; key (what its
--- unsent text is kept under); win and line (the window and the line it goes under);
--- send(body, done) posts the trimmed text and calls done(true), or done(false, why).
function M.open(opts)
  M.close()
  local at = place(opts.win, opts.line)
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_set_option_value("bufhidden", "wipe", { buf = buf }) -- the float's own buffer: gone with it
  vim.api.nvim_set_option_value("buftype", "acwrite", { buf = buf }) -- :w is ours: BufWriteCmd
  count = count + 1
  vim.api.nvim_buf_set_name(buf, "difftate://compose/" .. count)
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor", style = "minimal", border = "rounded", focusable = true,
    row = at.row, col = at.col, width = at.width, height = at.height,
    title = " " .. opts.title .. " ", title_pos = "left",
    footer = " :w or <C-s> sends · q keeps the text ", footer_pos = "right",
  })
  local float = { win = win, buf = buf, key = opts.key }
  current = float
  local function set(name, value)
    vim.api.nvim_set_option_value(name, value, { scope = "local", win = win })
  end
  set("wrap", true)
  set("linebreak", true)
  local text = drafts[opts.key] or { "" }
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, text)
  vim.api.nvim_set_option_value("filetype", "markdown", { buf = buf })
  vim.api.nvim_win_set_cursor(win, { #text, #text[#text] })

  local function send()
    if float.sending or current ~= float then
      return
    end
    local body = vim.trim(table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n"))
    if body == "" then
      say("Nothing to send: write something first", vim.log.levels.WARN)
      return
    end
    float.sending = true
    opts.send(body, function(ok, why)
      float.sending = false
      if ok then
        drafts[float.key] = nil
        float.sent = true
        if current == float then
          M.close()
        end
      else
        say(why, vim.log.levels.ERROR) -- the float and its text stay
      end
    end)
  end

  vim.api.nvim_create_autocmd("BufWriteCmd", { buffer = buf, callback = function()
    send()
  end })
  -- Always unmodified: :q closes it, the text is kept (the buffer is the plugin's own)
  vim.api.nvim_create_autocmd({ "TextChanged", "TextChangedI" }, { buffer = buf, callback = function()
    vim.bo[buf].modified = false
  end })
  vim.keymap.set("n", "q", M.close, { buffer = buf, nowait = true, desc = "Close, keeping the text" })
  vim.keymap.set({ "n", "i" }, "<C-s>", function()
    vim.cmd.stopinsert()
    send()
  end, { buffer = buf, nowait = true, desc = "Send" })
  vim.api.nvim_create_autocmd("WinClosed", { pattern = tostring(win), once = true, callback = function()
    if current == float then
      current = nil
      keep(float)
    end
  end })
  vim.api.nvim_create_autocmd("WinLeave", { buffer = buf, once = true, callback = function()
    vim.schedule(function()
      if current == float then
        M.close() -- its text is kept, even while it is being sent
      end
    end)
  end })
  vim.cmd.startinsert({ bang = true })
end

return M
