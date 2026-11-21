-- A client of difftate's review API (lib/difftate/adapters/inbound/review_api/server.py),
-- served by the watcher of one checked-out folder: the repository, or one of its
-- worktrees. The watcher writes where it runs to <that folder's own git dir>/difftate/api.json
-- ({port, pid, root}) and its token to .../difftate/token, as dt-export and the Herdr
-- viewer (herdr/mods/difftate/api.js) read them.
--
-- Requests go through curl in vim.system, so Neovim never waits for one. The token
-- goes to curl on stdin (a config file, -K -), never in its arguments, which any
-- process can read.
local git = require("difftate.git")

local M = {}

-- How long a request may take before it counts as failed
local MAX_S = 10

--- The watcher of the checked-out folder <cwd> is in: on_found({ top, git_dir })
--- (its top folder and its own git dir), or on_found(nil, why) outside a git
--- repository. It doesn't say whether a watcher runs there: a request does.
function M.find(cwd, on_found)
  git.run(cwd, { "rev-parse", "--absolute-git-dir", "--show-toplevel" }, function(out)
    local lines = out and vim.split(out, "\n") or {}
    if #lines < 2 then
      on_found(nil, cwd .. " is not in a git repository")
      return
    end
    on_found({ git_dir = lines[1], top = lines[2] })
  end)
end

local function read(path)
  local f = io.open(path)
  if not f then
    return nil
  end
  local text = f:read("*a")
  f:close()
  return text
end

-- Where the watcher of <watcher> serves the API now: (port, token), or nil when none
-- wrote it. Read for every request, so a restarted watcher's new port and token are used.
local function address(watcher)
  local folder = watcher.git_dir .. "/difftate"
  local ok, info = pcall(vim.json.decode, read(folder .. "/api.json") or "")
  local token = vim.trim(read(folder .. "/token") or "")
  if not ok or type(info) ~= "table" or not tonumber(info.port) or token == "" then
    return nil
  end
  return tonumber(info.port), token
end

-- <text> as a double-quoted string of curl's config file: \ and " escaped (a JSON
-- text has no raw control characters, vim.json.encode escapes them)
local function quoted(text)
  return '"' .. text:gsub('[\\"]', "\\%0") .. '"'
end

--- Call the review API of <watcher> (from M.find): on_answer(answer) on the main
--- loop with the decoded JSON, or on_answer(nil, err) where err.missing says no
--- watcher answered (none wrote where it runs, or it doesn't answer there), and
--- err.message what went wrong. <payload> (a Lua table, sent as JSON) is the body of a
--- POST or PATCH, as the browser sends it. With <text> true the answer is the body as it came (an
--- answer that is text, not JSON: the export); an error is JSON as always.
function M.request(watcher, method, path, on_answer, payload, text)
  local port, token = address(watcher)
  if not port then
    vim.schedule(function()
      on_answer(nil, { missing = true, message = "no difftate is running for " .. watcher.top })
    end)
    return
  end
  local cmd = { "curl", "-sS", "--max-time", tostring(MAX_S), "-K", "-", "-X", method,
    "-w", "\n%{http_code}", ("http://127.0.0.1:%d%s"):format(port, path) }
  local config = ('header = "Authorization: Bearer %s"\n'):format(token)
  if payload ~= nil then
    -- In the config on stdin, like the token: a comment is private text too, and argv is readable by any process
    config = config .. 'header = "Content-Type: application/json"\n'
      .. "data-raw = " .. quoted(vim.json.encode(payload)) .. "\n"
  end
  local ok, err = pcall(vim.system, cmd, { text = true, stdin = config }, vim.schedule_wrap(function(r)
    if r.code ~= 0 then
      on_answer(nil, { missing = true, message = vim.trim(r.stderr or "") })
      return
    end
    local body, status = (r.stdout or ""):match("^(.*)\n(%d+)$")
    if text and tonumber(status) == 200 then
      on_answer(body or "")
      return
    end
    local decoded_ok, answer = pcall(vim.json.decode, body or "", { luanil = { object = true, array = true } })
    if not decoded_ok or type(answer) ~= "table" then
      answer = nil
    end
    if tonumber(status) ~= 200 or not answer then
      local said = answer and answer.error or nil
      -- 401: another watcher's token, from a stale file (as the Herdr viewer reads it)
      on_answer(nil, { missing = status == "401", message = said or ("%s %s: %s"):format(method, path, status) })
      return
    end
    on_answer(answer)
  end))
  if not ok then
    vim.schedule(function()
      on_answer(nil, { message = "can't run curl: " .. tostring(err) })
    end)
  end
end

return M
