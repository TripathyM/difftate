-- git, run asynchronously: Neovim never waits for it.
local M = {}

--- Run `git -C <cwd> <args>`. on_done(stdout, nil) runs on the main loop when it
--- succeeds, with its output trimmed; on_done(nil, why) when it fails or git
--- can't start.
function M.run(cwd, args, on_done)
  local cmd = vim.list_extend({ "git", "-C", cwd }, args)
  local ok, err = pcall(vim.system, cmd, { text = true }, vim.schedule_wrap(function(r)
    if r.code == 0 then
      on_done(vim.trim(r.stdout or ""), nil)
    else
      on_done(nil, vim.trim(r.stderr or ""))
    end
  end))
  if not ok then
    vim.schedule(function()
      on_done(nil, tostring(err))
    end)
  end
end

return M
