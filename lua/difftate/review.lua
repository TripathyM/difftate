-- The review open in this Neovim: at most one, of the checked-out folder Neovim
-- was in when it opened.
local api = require("difftate.api")
local compose = require("difftate.compose")
local draw = require("difftate.draw")
local float = require("difftate.float")
local git = require("difftate.git")
local gitsigns = require("difftate.gitsigns")
local threads = require("difftate.threads")

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

-- Read the threads of the open <review> (and, for threads on deleted lines, the
-- changeset's diff) and draw them in the buffers, when they changed since the last
-- time; then on_done(). A failed read leaves what is drawn, and says nothing: the
-- review request of the same poll says it when difftate stopped answering.
local function read_threads(review, on_done)
  api.request(review.watcher, "GET", "/api/threads?view=", function(listed)
    if current ~= review then
      return
    end
    if not listed then
      on_done()
      return
    end
    local function draw_them(diff_text)
      if current ~= review then
        return
      end
      local key = vim.json.encode(listed) .. (diff_text or "")
      if key ~= review.drawn_key then
        review.drawn_key = key
        draw.show(review.watcher.top, listed, diff_text)
      end
      on_done()
    end
    local on_deleted_lines = vim.iter(listed):any(threads.is_old)
    if not on_deleted_lines then
      draw_them()
      return
    end
    api.request(review.watcher, "GET", "/api/changeset?view=", function(changeset)
      if not changeset then
        on_done() -- without the diff the deleted lines can't be placed: leave what is drawn
        return
      end
      draw_them(changeset.diff or "")
    end)
  end)
end

-- One poll of the open <review>: the review API (the base may change after a
-- checkout), the merge-base, then the threads. One at a time: a slow one is skipped over.
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
      if why and why ~= review.base_error then
        say(why, vim.log.levels.WARN) -- once, not every poll
      end
      review.base_error = why
      read_threads(review, function()
        review.polling = false
      end)
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
        read_threads(review, function()
          start_polling(review, opts.poll_ms)
        end)
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
  float.close()
  compose.close() -- what is typed stays, for when a review is open again
  draw.clear()
  local base = gitsigns.restore()
  say(("Review closed: git signs show changes since %s again"):format(base or "the index"))
end

--- Expand every resolved, dismissed and outdated thread to full, or shrink them to
--- one line again.
function M.toggle_expanded()
  if not (current and current.watcher) then
    say("No review is open: open it to expand its threads")
    return
  end
  say(draw.toggle_expanded() and "Every thread is expanded" or "Resolved, dismissed and outdated threads are one line")
end

-- The review for a key that needs one, or nil (with the message): <what> says what the key does
local function open_review(what)
  if not (current and current.watcher) then
    say("No review is open: open it to " .. what)
    return nil
  end
  return current
end

-- Choose among <candidates>, the threads on the cursor's line (a choice when several
-- are): then_(thread). <none> is said when there are none.
local function choose(candidates, none, then_)
  if #candidates == 0 then
    say(none)
  elseif #candidates == 1 then
    then_(candidates[1])
  else
    vim.ui.select(candidates, { prompt = "Which thread?", format_item = function(thread)
      return threads.summary(thread, 80)
    end }, function(thread)
      if thread then
        then_(thread)
      end
    end)
  end
end

-- The threads on the cursor's line that <wanted> (a function of a thread, any when nil)
-- accepts: then_(thread) on the one the reviewer chooses. <none> says what is missing when
-- threads are there but none is wanted.
local function thread_here(wanted, none, then_)
  local found = draw.threads_at(vim.api.nvim_get_current_buf(), vim.api.nvim_win_get_cursor(0)[1])
  if #found == 0 then
    say("No thread on this line")
    return
  end
  choose(wanted and vim.tbl_filter(wanted, found) or found, none, then_)
end

--- Open the thread on the cursor's line in the read float (a choice when several are).
function M.read_thread()
  if not open_review("read a thread") then
    return
  end
  thread_here(nil, nil, float.open)
end

-- Read the threads again now, so that what was just sent is drawn without waiting for a poll
local function refresh(review)
  read_threads(review, function() end)
end

-- Send <payload> to the review API: done(true) once it took it (and the threads are
-- drawn again, when the review is still open), or done(false, why).
local function send(review, method, path, payload, done)
  api.request(review.watcher, method, path, function(answer, err)
    if not answer then
      done(false, err.missing and no_watcher(review.watcher.top) or err.message)
      return
    end
    done(true)
    if current == review then
      refresh(review)
    end
  end, payload)
end

-- A compose float's send function: post <payload> (a function of the text) to <path>, say
-- <sent> when the review API took it
local function poster(review, method, path, payload, sent)
  return function(body, done)
    send(review, method, path, payload(body), function(ok, why)
      if ok then
        say(sent)
      end
      done(ok, why)
    end)
  end
end

-- The path of the file of buffer <buf> in the review's folder, or nil and why
local function path_in_review(review, buf)
  local name = vim.api.nvim_buf_get_name(buf)
  if vim.bo[buf].buftype ~= "" or name == "" then
    return nil, "This buffer is not a file: comments go on the files of the review"
  end
  local top = vim.uv.fs_realpath(review.watcher.top) or review.watcher.top
  local path = vim.uv.fs_realpath(name) or name
  if not vim.startswith(path, top .. "/") then
    return nil, ("%s is not in %s, the folder of the review"):format(vim.fn.fnamemodify(name, ":~"), review.watcher.top)
  end
  return path:sub(#top + 2)
end

-- The lines of the cursor, or of the visual selection when <visual> (which ends it)
local function lines_picked(visual)
  local cursor = vim.fn.line(".")
  local other = visual and vim.fn.line("v") or cursor -- the selection's other end
  if visual then
    vim.api.nvim_feedkeys(vim.keycode("<Esc>"), "nx", false)
  end
  return math.min(cursor, other), math.max(cursor, other)
end

--- Write a comment on the cursor's line, or on the visual selection when <visual>: it opens a
--- thread on the code on disk at those lines, on the side new (a deleted line is in no buffer).
function M.comment(visual)
  local review = open_review("comment")
  if not review then
    return
  end
  local first, last = lines_picked(visual)
  local buf, win = vim.api.nvim_get_current_buf(), vim.api.nvim_get_current_win()
  if vim.bo[buf].modified then
    say("Save the file to comment on it", vim.log.levels.WARN)
    return
  end
  local file, why = path_in_review(review, buf)
  if not file then
    say(why, vim.log.levels.WARN)
    return
  end
  -- The anchor, as the browser sends it, without a version: the file is read from disk, not from a diff
  local anchor = { file = file, side = "new", startLine = first, endLine = last,
    code = table.concat(vim.api.nvim_buf_get_lines(buf, first - 1, last, false), "\n") }
  local where = first == last and tostring(first) or ("%d-%d"):format(first, last)
  compose.open({
    title = ("comment on %s:%s"):format(file, where), win = win, line = last,
    key = ("%s\0%s:%d:%d"):format(review.watcher.top, file, first, last),
    send = poster(review, "POST", "/api/threads", function(body)
      return { anchor = anchor, body = body, view = "" }
    end, "Comment sent"),
  })
end

--- Write a reply to the thread on the cursor's line (a choice when several are).
function M.reply()
  local review = open_review("reply")
  if not review then
    return
  end
  local win, line = vim.api.nvim_get_current_win(), vim.api.nvim_win_get_cursor(0)[1]
  thread_here(nil, nil, function(thread)
    local a = thread.anchor
    compose.open({
      title = a and ("reply on %s:%d"):format(a.file, a.endLine) or "reply on a general thread", win = win, line = line,
      key = ("%s\0reply:%s"):format(review.watcher.top, thread.id),
      send = poster(review, "POST", ("/api/threads/%s/comments"):format(vim.uri_encode(thread.id)), function(body)
        return { kind = "comment", body = body }
      end, "Reply sent"),
    })
  end)
end

--- Write a general thread: one on the changeset as a whole, with no line.
function M.general()
  local review = open_review("write a general thread")
  if not review then
    return
  end
  compose.open({
    title = "general thread", win = vim.api.nvim_get_current_win(), line = vim.api.nvim_win_get_cursor(0)[1],
    key = review.watcher.top .. "\0general",
    send = poster(review, "POST", "/api/threads", function(body)
      return { anchor = vim.NIL, body = body, view = "" }
    end, "General thread sent"),
  })
end

--- Set the status of the thread on the cursor's line: <status> "resolved" resolves an open
--- one, "open" reopens a resolved or dismissed one.
function M.set_status(status)
  local review = open_review(status == "open" and "reopen a thread" or "resolve a thread")
  if not review then
    return
  end
  local reopening = status == "open"
  thread_here(function(thread)
    return (thread.status == "open") ~= reopening
  end, reopening and "No resolved or dismissed thread on this line" or "No open thread on this line", function(thread)
    send(review, "PATCH", ("/api/threads/%s/status"):format(vim.uri_encode(thread.id)), { status = status },
      function(ok, why)
        say(ok and (reopening and "Reopened" or "Resolved") or why, ok and vim.log.levels.INFO or vim.log.levels.ERROR)
      end)
  end)
end

--- Say whether the review is open, and what git signs show.
function M.say_status()
  local note = M.status()
  say(note ~= "" and note or (current and "The review is opening" or "No review is open"))
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
