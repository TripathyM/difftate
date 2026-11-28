-- The view, as text (GLOSSARY.md: View). Pure: no editor, no request. The words follow the browser viewer's
-- (lib/difftate/adapters/inbound/review_api/web/d/views.js) and the deleted Herdr
-- viewer's (ADR 0008). A view is what GET /api/view answers: "" for all changes, a commit such as HEAD~2 for the
-- commits after it, HEAD for the uncommitted changes, "staged" or "unstaged".
--
-- gitsigns compares the file on disk with one base, so it can show every view but the staged one
-- (ADR 0007): that stays in the browser, and here the review shows all changes meanwhile.
local M = {}

--- Whether <view> is the staged one, which only the browser shows.
function M.is_staged(view)
  return view == "staged"
end

--- The view the Neovim viewer shows when the review's view is <view>: the same, but all changes for the
--- staged one.
function M.shown(view)
  return M.is_staged(view) and "" or (view or "")
end

--- How many commits back HEAD~<n> goes (a number), or nil for any other view.
local function last(view)
  local n = (view or ""):match("^HEAD~(%d+)$")
  return n and tonumber(n) or nil
end

--- The view in words: "all changes", "the last 2 commits", "the commits after 3f2a1bc".
function M.label(view)
  view = view or ""
  local n = last(view)
  if view == "" then
    return "all changes"
  elseif view == "HEAD" then
    return "uncommitted changes"
  elseif view == "staged" or view == "unstaged" then
    return view .. " changes"
  elseif n == 1 then
    return "the last commit"
  elseif n then
    return ("the last %d commits"):format(n)
  end
  return "the commits after " .. view
end

--- What the statusline note says of the view: nil for all changes.
function M.status_part(view)
  if M.is_staged(view) then
    return "showing all changes: staged changes are only in the browser"
  elseif (view or "") ~= "" then
    return "showing " .. M.label(view)
  end
  return nil
end

--- What git signs show in <view>, after "git signs show" ("changes since main"); <base> is the review's.
function M.signs_phrase(view, base)
  view = M.shown(view)
  if view == "" then
    return "changes since " .. base
  elseif view == "unstaged" then
    return "unstaged changes"
  end
  return "changes since " .. view
end

--- The request path of <path> in <view>: the review API places every thread in it.
function M.query(path, view)
  return ("%s?view=%s"):format(path, vim.uri_encode(M.shown(view), "rfc3986"))
end

--- The entries of the views picker, { { text, value } }: <commits> are the lines of `git log --format="%h %s"`
--- of the branch, newest first, <view> the view shown now (marked), <base> the review's base.
function M.entries(commits, view, base)
  local entries = {
    { text = ("All changes · against %s"):format(base or "the base"), value = "" },
    { text = "Uncommitted changes", value = "HEAD" },
    { text = "Unstaged changes", value = "unstaged" },
  }
  for n, commit in ipairs(commits) do
    local text = n == 1 and ("Last commit · %s"):format(commit)
      or ("Last %d commits · down to %s"):format(n, commit)
    table.insert(entries, { text = text, value = "HEAD~" .. n })
  end
  local shown = M.shown(view)
  for _, entry in ipairs(entries) do
    if entry.value == shown then
      entry.text = entry.text .. " · shown"
    end
  end
  return entries
end

return M
