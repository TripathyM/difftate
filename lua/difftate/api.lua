-- A client of difftate's review API (lib/difftate/adapters/inbound/review_api/server.py),
-- served by the one watcher of the machine (ADR 0008). The watcher writes where it runs to
-- api.json ({port, pid}) and its token to token, in the difftate folder of the home
-- ($DIFFTATE_HOME, else ~/.difftate), as dt-export reads them. Every request names the
-- checked-out folder it is about, which the watcher serves from the first request that
-- names it. Neovim never starts the watcher: `difftate` does.
--
-- Requests go through curl in vim.system, so Neovim never waits for one. The token
-- goes to curl on stdin (a config file, -K -), never in its arguments, which any
-- process can read.
local git = require("difftate.git")

local M = {}

--- What to say when no watcher answers
M.NOT_RUNNING = "No difftate is running: run `difftate` in a terminal"

-- How long a request may take before it counts as failed
local MAX_S = 10

--- The review of the checked-out folder <cwd> is in: on_found({ top }) (its top
--- folder, which requests name), or on_found(nil, why) outside a git repository.
--- It doesn't say whether the watcher runs: a request does.
function M.find(cwd, on_found)
  git.run(cwd, { "rev-parse", "--show-toplevel" }, function(out)
    if not out or out == "" then
      on_found(nil, cwd .. " is not in a git repository")
      return
    end
    on_found({ top = vim.split(out, "\n")[1] })
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

-- The difftate folder of the machine: $DIFFTATE_HOME, else ~/.difftate
local function home()
  local given = vim.env.DIFFTATE_HOME
  if given and given ~= "" then
    return given
  end
  return (vim.uv.os_homedir() or vim.env.HOME or "") .. "/.difftate"
end

-- Where the watcher serves the API now: (port, token), or nil when none wrote it. Read
-- for every request, so a restarted watcher's new port and token are used.
local function address()
  local folder = home()
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

--- Call the review API about the folder of <watcher> (from M.find): on_answer(answer) on the main
--- loop with the decoded JSON, or on_answer(nil, err) where err.missing says no
--- watcher answered (none wrote where it runs, or it doesn't answer there), and
--- err.message what went wrong. <payload> (a Lua table, sent as JSON) is the body of a
--- POST or PATCH, as the browser sends it. With <raw> true the answer is the body as it came (an
--- answer that is text, not JSON: the export); an error is JSON as always.
function M.request(watcher, method, path, on_answer, payload, raw)
  local port, token = address()
  if not port then
    vim.schedule(function()
      on_answer(nil, { missing = true, message = M.NOT_RUNNING })
    end)
    return
  end
  path = path .. (path:find("?", 1, true) and "&" or "?") .. "folder=" .. vim.uri_encode(watcher.top, "rfc3986")
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
    if raw and tonumber(status) == 200 then
      on_answer(body or "")
      return
    end
    local decoded_ok, answer = pcall(vim.json.decode, body or "", { luanil = { object = true, array = true } })
    if not decoded_ok or type(answer) ~= "table" then
      answer = nil
    end
    if tonumber(status) ~= 200 or not answer then
      local said = answer and answer.error or nil
      -- 401: another watcher's token, from a stale file
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
