-- The Neovim viewer's commands, there without setup() so `nvim +DifftateOpen`
-- works. Keys come from setup(opts) (lua/difftate/init.lua).
if vim.g.loaded_difftate then
  return
end
vim.g.loaded_difftate = true

vim.api.nvim_create_user_command("DifftateOpen", function()
  require("difftate").open()
end, { desc = "Open the review of this folder" })
vim.api.nvim_create_user_command("DifftateClose", function()
  require("difftate").close()
end, { desc = "Close the review: git signs go back to the index" })
vim.api.nvim_create_user_command("DifftateStatus", function()
  require("difftate").say_status()
end, { desc = "Say whether the review is open" })
