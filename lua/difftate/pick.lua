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
--- one is picked, never when the picker is dismissed. <title> names the picker.
function M.choose(entries, title, on_choice)
  local picker = snacks_picker()
  if picker then
    local items = {}
    for i, entry in ipairs(entries) do
      items[i] = { idx = i, text = entry.text, value = entry.value }
    end
    picker.pick({
      title = title,
      items = items,
      format = function(item)
        return { { item.text } }
      end,
      preview = false,
      layout = { preset = "select" },
      confirm = function(self, item)
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
    if entry then
      on_choice(entry.value)
    end
  end)
end

return M
