-- The chooser of the pickers: Snacks.picker when it is loaded (LazyVim's default), else
-- vim.ui.select; the files sidebar, a list that stays open, is Snacks only. A picker is the reviewer's own tool: the plugin sets no option or key on it.
local M = {}

local function snacks_picker()
  local snacks = rawget(_G, "Snacks") or package.loaded["snacks"]
  local ok, pick = pcall(function()
    return snacks and snacks.picker and snacks.picker.pick
  end)
  return ok and type(pick) == "function" and snacks.picker or nil
end

--- Let the reviewer choose among <entries> ({ { text, value } }): on_choice(value) once
--- one is picked, never when the picker is dismissed. An entry with no value is a heading: picking
--- it does nothing. <title> names the picker. <opts>: `current`, a function of an entry's value that is
--- true for the row the cursor starts on (Snacks only), and an entry's `preview`, markdown shown beside
--- the rows when Snacks is there (vim.ui.select shows rows only).
function M.choose(entries, title, on_choice, opts)
  opts = opts or {}
  local picker = snacks_picker()
  if picker then
    local items, previewed, current = {}, false, nil
    for i, entry in ipairs(entries) do
      previewed = previewed or entry.preview ~= nil
      items[i] = { idx = i, text = entry.text, value = entry.value,
        preview = { text = entry.preview or "", ft = "markdown", loc = false } }
      if not current and entry.value ~= nil and opts.current and opts.current(entry.value) then
        current = i
      end
    end
    picker.pick({
      title = title,
      items = items,
      format = function(item)
        return { { item.text } }
      end,
      preview = previewed and "preview" or false,
      -- long answers wrap at word breaks, in this picker's own preview window only
      win = previewed and { preview = { wo = { wrap = true, linebreak = true } } } or nil,
      layout = { preset = previewed and "default" or "select" },
      on_show = current and function(shown)
        -- the rows come in a moment after the picker shows: wait for them, a few times at most
        local tries = 0
        local function move()
          tries = tries + 1
          if shown.list:count() >= current then
            shown.list:move(current, true)
          elseif tries < 20 then
            vim.defer_fn(move, 10)
          end
        end
        move()
      end or nil,
      confirm = function(self, item)
        if item and item.value == nil then
          return
        end
        self:close()
        if item then
          vim.schedule(function()
            on_choice(item.value)
          end)
        end
      end,
    })
    return
  end
  vim.ui.select(entries, {
    prompt = title,
    format_item = function(entry)
      return entry.text
    end,
  }, function(entry)
    if entry and entry.value ~= nil then
      on_choice(entry.value)
    end
  end)
end

--- A list that stays down the right side of the screen (Snacks only; nil when it is not there), with
--- the rows of <entries> as `choose` shows them, but no preview: like LazyVim's explorer, it stays
--- open when a row is picked. on_choose(value) runs in the window the list was opened from. <opts>:
--- `focus`, whether the cursor goes into the list (else it stays in the window it was in), and
--- `current`, as for `choose`. Gives { update(entries), close(), is_open() }: update changes the
--- rows when their text changed.
function M.sidebar(entries, title, on_choose, opts)
  opts = opts or {}
  local picker = snacks_picker()
  if not picker then
    return nil
  end
  local function items_of(list)
    local items = {}
    for i, entry in ipairs(list) do
      items[i] = { idx = i, text = entry.text, value = entry.value }
    end
    return items
  end
  local function texts_of(list)
    return vim.tbl_map(function(entry)
      return entry.text
    end, list)
  end
  local items, texts = items_of(entries), texts_of(entries)
  local current
  for i, entry in ipairs(entries) do
    if entry.value ~= nil and opts.current and opts.current(entry.value) then
      current = i
      break
    end
  end
  local shown = picker.pick({
    source = "difftate_files",
    title = title,
    finder = function()
      return items
    end,
    format = function(item)
      return { { item.text } }
    end,
    preview = false,
    layout = { preset = "right", preview = false },
    auto_close = false,
    focus = opts.focus and "list" or false,
    on_show = current and function(list_picker)
      local tries = 0
      local function move()
        tries = tries + 1
        if list_picker.list:count() >= current then
          list_picker.list:move(current, true)
        elseif tries < 20 then
          vim.defer_fn(move, 10)
        end
      end
      move()
    end or nil,
    confirm = function(self, item)
      if not (item and item.value ~= nil) then
        return
      end
      if self.main and vim.api.nvim_win_is_valid(self.main) then
        vim.api.nvim_set_current_win(self.main)
      end
      vim.schedule(function()
        on_choose(item.value)
      end)
    end,
  })
  local handle = {}
  function handle.is_open()
    return shown ~= nil and not shown.closed
  end
  function handle.close()
    if handle.is_open() then
      shown:close()
    end
  end
  function handle.update(list)
    local new = texts_of(list)
    if handle.is_open() and not vim.deep_equal(new, texts) then
      items, texts = items_of(list), new
      shown:find({ refresh = true })
    end
  end
  return handle
end

return M
