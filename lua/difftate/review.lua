-- The review open in this Neovim: at most one, of the checked-out folder Neovim
-- was in when it opened.
local api = require("difftate.api")
local git = require("difftate.git")
local gitsigns = require("difftate.gitsigns")

local M = {}

local current -- the open review, or the one opening: { watcher, base, ... }

local function say(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "difftate" })
end

local function no_watcher(top)
  return ("No difftate is running for %s: start it there, then open the review again"):format(top)
end

-- Point gitsigns at the merge-base of the review's base and HEAD, when it moved
-- since the last time; then on_done(), or on_done(why) when git can't find it.
local function follow_base(review, on_done)
  git.run(review.watcher.top, { "merge-base", review.base, "HEAD" }, function(commit, err)
    if current ~= review then
      return
    end
    if not commit then
      on_done(("git can't find where this branch left %s: %s"):format(review.base, err))
      return
    end
    if commit ~= review.merge_base then
      review.merge_base = commit
      review.signs = gitsigns.point_at(commit)
    end
    on_done()
  end)
end

-- One poll of the open <review>: the review API (the base may change after a
-- checkout), then the merge-base. One at a time: a slow one is skipped over.
-- Later tickets read the threads here too.
local function poll(review)
  if review.polling or current ~= review then
    return
  end
  review.polling = true
  api.request(review.watcher, "GET", "/api/review", function(answer, err)
    if current ~= review then
      return
    end
    if not answer then
      review.polling = false
      if not review.lost then
        review.lost = true
        say(("difftate stopped answering (%s): the review stays open, and git signs on %s"):format(
          err.message, review.base), vim.log.levels.WARN)
      end
      return
    end
    review.lost = false
    review.base = answer.base
    follow_base(review, function(why)
      review.polling = false
      if why and why ~= review.base_error then
        say(why, vim.log.levels.WARN) -- once, not every poll
      end
      review.base_error = why
    end)
  end)
end

local function start_polling(review, every_ms)
  review.timer = vim.uv.new_timer()
  review.timer:start(every_ms, every_ms, vim.schedule_wrap(function()
    poll(review)
  end))
end

local function stop_polling(review)
  if review.timer then
    review.timer:stop()
    review.timer:close()
    review.timer = nil
  end
end

--- Open the review of the checked-out folder <cwd> is in, as `opts` (setup's) say.
function M.open(cwd, opts)
  if current then
    say("The review is already open")
    return
  end
  local review = {}
  current = review
  api.find(cwd, function(watcher, why)
    if current ~= review then
      return
    end
    if not watcher then
      current = nil
      say(why, vim.log.levels.WARN)
      return
    end
    api.request(watcher, "GET", "/api/review", function(answer, err)
      if current ~= review then
        return
      end
      if not answer then
        current = nil
        say(err.missing and no_watcher(watcher.top) or err.message, vim.log.levels.WARN)
        return
      end
      review.watcher, review.base = watcher, answer.base
      follow_base(review, function(why)
        if why then
          current = nil
          gitsigns.restore()
          say(why, vim.log.levels.WARN)
          return
        end
        say(M.status())
        start_polling(review, opts.poll_ms)
      end)
    end)
  end)
end

--- Close the open review: gitsigns' base goes back to what it was.
function M.close()
  if not current then
    say("No review is open")
    return
  end
  stop_polling(current)
  current = nil
  local base = gitsigns.restore()
  say(("Review closed: git signs show changes since %s again"):format(base or "the index"))
end

--- Say whether the review is open, and what git signs show.
function M.say_status()
  say(M.status() ~= "" and M.status() or (current and "The review is opening" or "No review is open"))
end

--- Whether a review is open (or opening).
function M.is_open()
  return current ~= nil
end

--- The note a statusline shows while the review is open; "" when none is.
function M.status()
  if not (current and current.merge_base) then
    return ""
  end
  if not current.signs then
    return ("review open · gitsigns isn't loaded: no git signs for changes since %s"):format(current.base)
  end
  return ("review open · git signs show changes since %s"):format(current.base)
end

return M
