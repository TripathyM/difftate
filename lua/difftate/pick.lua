-- The chooser of the pickers: Snacks.picker when it is loaded (LazyVim's default), else
-- vim.ui.select. A picker is the reviewer's own tool: the plugin sets no option or key on it.
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

return M
