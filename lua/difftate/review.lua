-- The review open in this Neovim: at most one, of the checked-out folder Neovim
-- was in when it opened.
local agent = require("difftate.agent")
local api = require("difftate.api")
local compose = require("difftate.compose")
local diff = require("difftate.diff")
local draw = require("difftate.draw")
local float = require("difftate.float")
local git = require("difftate.git")
local gitsigns = require("difftate.gitsigns")
local look = require("difftate.look")
local mode = require("difftate.mode")
local done = require("difftate.done")
local export = require("difftate.export")
local nav = require("difftate.nav")
local pick = require("difftate.pick")
local review_path = require("difftate.review_path")
local threads = require("difftate.threads")
local view = require("difftate.view")

local M = {}

local current -- the open review, or the one opening: { watcher, base, ... }
local show_sidebar, refresh_sidebar -- the changed files sidebar, below

local function say(message, level)
  vim.notify(message, level or vim.log.levels.INFO, { title = "difftate" })
end

local function no_watcher()
  return api.NOT_RUNNING
end

-- The view the review shows: the review's view, or all changes when it is the staged one (only the
-- browser shows it) or one git can't find here (a view chosen on a longer branch, say)
local function shown_view(review)
  return review.unreadable and "" or view.shown(review.view)
end

-- Point gitsigns at the base of the view shown, when it moved since the last time; then on_done(), or
-- on_done(why, fatal) when git can't: fatal when it can't find where the branch left the base; a view
-- it can't find is not (the review shows all changes meanwhile, so the reviewer can choose another). All changes: where the branch left the review's base (the
-- merge-base of the base and HEAD); the unstaged view: the index (gitsigns' own default); any other
-- view is a commit (HEAD~2, HEAD, ...), which gitsigns compares the file on disk with.
local function follow_base(review, on_done)
  git.run(review.watcher.top, { "merge-base", review.base, "HEAD" }, function(commit, err)
    if current ~= review then
      return
    end
    if not commit then
      on_done(("git can't find where this branch left %s: %s"):format(review.base, err), true)
      return
    end
    review.merge_base = commit
    local function point(target) -- a commit, or nil for the index
      local key = target or "the index"
      if key ~= review.pointed then
        review.pointed = key
        review.signs = gitsigns.point_at(target)
      end
      on_done()
    end
    local shown = view.shown(review.view)
    review.unreadable = false
    if shown == "" then
      point(commit)
    elseif shown == "unstaged" then
      point(nil)
    else
      git.run(review.watcher.top, { "rev-parse", "--verify", shown .. "^{commit}" }, function(sha, why)
        if current ~= review then
          return
        end
        if view.shown(review.view) ~= shown then
          on_done() -- the view changed while git looked: the change follows its own base, and this one is stale
          return
        end
        if not sha then
          review.unreadable = true
          point(commit)
          on_done(("git can't find %s, the view: showing all changes (%s)"):format(shown, why))
          return
        end
        point(sha)
      end)
    end
  end)
end

-- Read the threads of the open <review> (and, for threads on deleted lines, the
-- changeset's diff) and draw them in the buffers, when they changed since the last
-- time; then on_done(). A failed read leaves what is drawn, and says nothing: the
-- review request of the same poll says it when difftate stopped answering.
local function read_threads(review, on_done)
  local shown = shown_view(review)
  api.request(review.watcher, "GET", view.query("/api/threads", shown), function(listed)
    if current ~= review then
      return
    end
    if not listed then
      on_done()
      return
    end
    float.refresh(listed) -- a thread read in the float shows what changed in it
    local function draw_them(diff_text)
      if current ~= review then
        return
      end
      local key = view.shown(shown) .. "\0" .. vim.json.encode(listed) .. (diff_text or "")
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
    api.request(review.watcher, "GET", view.query("/api/changeset", shown), function(changeset)
      if not changeset then
        on_done() -- without the diff the deleted lines can't be placed: leave what is drawn
        return
      end
      draw_them(changeset.diff or "")
    end)
  end)
end

-- Take <answer> (what the review API says of the mode: { mode, held }) as the mode of the open
-- <review>, for the statusline note, which redraws now rather than on its own timers
local function know_mode(review, answer)
  if current == review then
    review.mode = { mode = answer.mode, held = answer.held or {} }
    vim.cmd("redrawstatus")
  end
end

-- Read the review mode and the held threads of the open <review> (GET /api/mode), for the
-- statusline note; then on_done(answer), or on_done(nil, err) when the review API didn't answer
-- (what was known stays: the poll says when difftate stopped).
local function read_mode(review, on_done)
  local stamp = review.mode_stamp
  api.request(review.watcher, "GET", "/api/mode", function(answer, err)
    if not answer then
      on_done(nil, err)
      return
    end
    -- A change or a Submit answered since this was asked: its answer is newer, so this one doesn't overwrite it
    if review.mode_stamp == stamp then
      know_mode(review, answer)
    end
    on_done(answer)
  end)
end

-- Take <answer> (what the review API says of the agent: { agent, source, names }) as the agent of the
-- open <review>, for the statusline note
local function know_agent(review, answer)
  if current == review then
    review.agent = answer
    vim.cmd("redrawstatus")
  end
end

-- Read who replies in the open <review> (GET /api/agent), for the statusline note; then on_done(answer),
-- or on_done(nil, err) when the review API didn't answer or the agent list can't be read (the note then
-- names no agent: it doesn't say so on every poll).
local function read_agent(review, on_done)
  local stamp = review.agent_stamp
  api.request(review.watcher, "GET", "/api/agent", function(answer, err)
    if not answer then
      if review.agent_stamp == stamp and not (err and err.missing) then
        know_agent(review, nil)
      end
      on_done(nil, err)
      return
    end
    -- A choice answered since this was asked: its answer is newer, so this one doesn't overwrite it
    if review.agent_stamp == stamp then
      know_agent(review, answer)
    end
    on_done(answer)
  end)
end

-- Take <answer> (what the review API says of Done) as the state of the open <review>, for the
-- statusline note, which redraws now rather than on its own timers
local function know_done(review, answer)
  if current == review then
    review.done = answer
    vim.cmd("redrawstatus")
  end
end

-- Read whether the open <review> is Done (GET /api/done), for the statusline note and Done's key; then
-- on_done(answer), or on_done(nil, err) when the review API didn't answer (what was known stays: a watcher
-- without the route shows no Done and no error: the poll says when difftate stopped).
local function read_done(review, on_done)
  local stamp = review.done_stamp
  api.request(review.watcher, "GET", "/api/done", function(answer, err)
    if not answer then
      on_done(nil, err)
      return
    end
    -- A mark or an undo answered since this was asked: its answer is newer, so this one doesn't overwrite it
    if review.done_stamp == stamp then
      know_done(review, answer)
    end
    on_done(answer)
  end)
end

-- Take <answer> (what the review API says of the view: { view }) as the view of the open <review>. The
-- watcher keeps the view, so another viewer's choice is followed too.
local function know_view(review, answer)
  if current == review then
    review.view = answer.view or ""
    vim.cmd("redrawstatus")
  end
end

-- Read the view the viewers show (GET /api/view); then on_done(answer), or on_done(nil, err) when the review API
-- didn't answer (a watcher without the route shows all changes: what was known stays).
local function read_view(review, on_done)
  local stamp = review.view_stamp
  api.request(review.watcher, "GET", "/api/view", function(answer, err)
    if not answer then
      on_done(nil, err)
      return
    end
    -- A choice answered since this was asked: its answer is newer, so this one doesn't overwrite it
    if review.view_stamp == stamp then
      know_view(review, answer)
    end
    on_done(answer)
  end)
end

-- Have Neovim look at the disk for each loaded file of the review's folder, as LazyVim does on focus: a file
-- a run changed reloads (when the reviewer's own 'autoread' says so; an unsaved edit gets Neovim's warning, once
-- per change, never an overwrite). Errors (the command-line window, say) are swallowed.
local function check_files(review)
  local top = vim.uv.fs_realpath(review.watcher.top) or review.watcher.top
  for _, buf in ipairs(vim.api.nvim_list_bufs()) do
    local name = vim.api.nvim_buf_get_name(buf)
    if vim.api.nvim_buf_is_loaded(buf) and vim.bo[buf].buftype == "" and name ~= ""
        and vim.startswith(vim.uv.fs_realpath(name) or name, top .. "/") then
      pcall(vim.cmd, "silent! checktime " .. buf)
    end
  end
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
    check_files(review)
    -- A warning about the review (a store changed outside difftate): shown once, as it comes
    review.warned = review.warned or {}
    for _, warning in ipairs(answer.warnings or {}) do
      if not review.warned[warning.id] then
        review.warned[warning.id] = true
        say(warning.text, vim.log.levels.WARN)
      end
    end
    read_view(review, function()
      follow_base(review, function(why)
        if why and why ~= review.base_error then
          say(why, vim.log.levels.WARN) -- once, not every poll
        end
        review.base_error = why
        look.redraw() -- gitsigns may have moved its hunks since: it only says so when their counts change
        read_mode(review, function()
          read_agent(review, function()
            read_done(review, function()
              read_threads(review, function()
                review.polling = false
                refresh_sidebar(review)
              end)
            end)
          end)
        end)
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
      review.watcher, review.base, review.view = watcher, answer.base, ""
      read_view(review, function()
        follow_base(review, function(why, fatal)
          if fatal then
            current = nil
            gitsigns.restore()
            say(why, vim.log.levels.WARN)
            return
          end
          if why then
            say(why, vim.log.levels.WARN)
          end
          read_mode(review, function()
            read_agent(review, function()
              read_done(review, function()
                if current ~= review then
                  return
                end
                say(M.status())
                look.show(watcher.top, opts.diff)
                read_threads(review, function()
                  start_polling(review, opts.poll_ms)
                  show_sidebar(review, false)
                end)
              end)
            end)
          end)
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
  if current.sidebar then
    current.sidebar.close()
  end
  current = nil
  float.close()
  compose.close() -- what is typed stays, for when a review is open again
  draw.clear()
  look.clear()
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
  local buf = vim.api.nvim_get_current_buf()
  -- In the read float the thread is the one it shows: that is how a general thread, which has no line, is acted on
  local read = float.thread_in(buf)
  local found = read and { read } or draw.threads_at(buf, vim.api.nvim_win_get_cursor(0)[1])
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
-- <sent> when the review API took it (that the comment is held when the review is batched)
local function poster(review, method, path, payload, sent)
  return function(body, done)
    send(review, method, path, payload(body), function(ok, why)
      if ok then
        -- The mode as it is now, not as the last poll saw it: another viewer may have changed it
        read_mode(review, function(answer)
          say(mode.comment_message(answer or review.mode, sent))
        end)
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

--- Write a comment in the thread on the cursor's line (a choice when several are). A
--- reply is the coding agent's answer (GLOSSARY.md), so this is a comment too.
function M.add_comment()
  local review = open_review("comment on a thread")
  if not review then
    return
  end
  local win, line = vim.api.nvim_get_current_win(), vim.api.nvim_win_get_cursor(0)[1]
  thread_here(nil, nil, function(thread)
    local a = thread.anchor
    compose.open({
      title = a and ("comment on thread at %s:%d"):format(a.file, a.endLine) or "comment on a general thread", win = win, line = line,
      key = ("%s\0thread:%s"):format(review.watcher.top, thread.id),
      send = poster(review, "POST", ("/api/threads/%s/comments"):format(vim.uri_encode(thread.id)), function(body)
        return { kind = "comment", body = body }
      end, "Comment sent"),
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

-- The review mode and Submit ---------------------------------------------------

local function failed(review, err)
  say(err.missing and no_watcher(review.watcher.top) or err.message, vim.log.levels.ERROR)
end

-- Take what a change of mode or a Submit answered ({ mode, held, submitted }) as the mode now,
-- and draw the threads again: what was held is no longer
local function changed(review, answer)
  review.mode_stamp = (review.mode_stamp or 0) + 1
  know_mode(review, answer)
  if current == review then
    refresh(review)
  end
end

--- Switch the review between live and batched. Changing to live submits what is held: it says how many.
function M.toggle_mode()
  local review = open_review("switch the review mode")
  if not review then
    return
  end
  -- From the mode the review API has now, so a switch made in another viewer isn't switched back blindly
  read_mode(review, function(now, err)
    if not now then
      return failed(review, err)
    end
    api.request(review.watcher, "PUT", "/api/mode", function(answer, err)
      if not answer then
        return failed(review, err)
      end
      say(mode.changed_message(answer.mode, answer.submitted))
      changed(review, answer)
    end, { mode = mode.other(now) })
  end)
end

--- Choose the agent that replies in this review from the machine's list, or go back to the repository's. A
--- run in progress keeps its agent: the next run uses the choice.
function M.pick_agent()
  local review = open_review("choose the agent")
  if not review then
    return
  end
  -- From the agent the review API has now, so a choice made in another viewer isn't undone blindly
  read_agent(review, function(now, err)
    if not now then
      return failed(review, err)
    end
    pick.choose(agent.entries(now), "Review agent", function(chosen)
      if current ~= review then
        return
      end
      local already = agent.already(now, chosen)
      if already then
        say(already)
        return
      end
      api.request(review.watcher, "PUT", "/api/agent", function(answer, err)
        if not answer then
          return failed(review, err)
        end
        review.agent_stamp = (review.agent_stamp or 0) + 1
        know_agent(review, answer)
        say(agent.changed_message(answer, chosen))
      end, { agent = chosen })
    end)
  end)
end

--- Submit the held threads of a batched review: they go to the coding agent as one run. With none held,
--- or in a live review, it says so and sends nothing.
function M.submit()
  local review = open_review("submit")
  if not review then
    return
  end
  read_mode(review, function(now, err)
    if not now then
      return failed(review, err)
    end
    local problem = mode.submit_problem(now)
    if problem then
      say(problem)
      return
    end
    api.request(review.watcher, "POST", "/api/submit", function(answer, err)
      if not answer then
        return failed(review, err)
      end
      say(mode.submitted_message(answer.submitted))
      changed(review, answer)
    end, vim.empty_dict()) -- {}, not []: the API wants an object
  end)
end

-- Done ---------------------------------------------------------------------------

-- Mark the review Done, or undo it (<now> is what the review API said a moment ago); the answer is the new status
local function put_done(review, marking, now)
  api.request(review.watcher, "PUT", "/api/done", function(answer, err)
    if not answer then
      return failed(review, err)
    end
    review.done_stamp = (review.done_stamp or 0) + 1
    know_done(review, answer)
    say(marking and done.marked_message(answer) or done.undone_message(now))
  end, { done = marking })
end

--- Mark the review Done at the commit its branch is at, or undo it. Open threads and runs still working are
--- warned about first (as the browser does): the reviewer goes on or stops.
function M.toggle_done()
  local review = open_review("mark it Done")
  if not review then
    return
  end
  -- From what the review API says now, so a mark made in another viewer isn't marked again blindly
  read_done(review, function(now, err)
    if not now then
      return failed(review, err)
    end
    local question = not done.is_done(now) and done.question(now) or nil
    if not question then
      return put_done(review, not done.is_done(now), now)
    end
    vim.ui.select({ "Mark Done anyway", "Stop" }, { prompt = question }, function(choice)
      if choice == "Mark Done anyway" and current == review then
        put_done(review, true, now)
      end
    end)
  end)
end

-- Export -------------------------------------------------------------------------

--- Copy the review's export (GET /api/export) to the system clipboard, for an agent session the
--- reviewer starts, as the browser does; to the unnamed register where there is no clipboard.
--- It names the review's folder in its reply command, so the session can reply from anywhere.
--- Exporting changes no thread.
function M.export()
  local review = open_review("export")
  if not review then
    return
  end
  local path = "/api/export?reply_folder=" .. vim.uri_encode(review.watcher.top, "rfc3986")
  api.request(review.watcher, "GET", path, function(text, err)
    if not text then
      if err.missing then
        return failed(review, err)
      end
      return say(export.failed_message(err.message), vim.log.levels.ERROR)
    end
    local problem = export.problem(text)
    if problem then
      return say(export.failed_message(problem), vim.log.levels.ERROR)
    end
    if vim.fn.has("clipboard") == 1 then
      vim.fn.setreg("+", text)
      say(export.copied_message(text))
    else
      vim.fn.setreg('"', text)
      say(export.in_register_message())
    end
  end, nil, true)
end

-- Browser -----------------------------------------------------------------------

--- Open the review of the checked-out folder <cwd> is in in the browser (<leader>rB): the link the
--- watcher gives for its page (POST /api/launch), with a new single-use launch code, opened with
--- vim.ui.open. It starts nothing and needs no review open here: with no watcher it says so.
function M.browser(cwd)
  api.find(cwd, function(watcher, why)
    if not watcher then
      return say(why, vim.log.levels.WARN)
    end
    api.request(watcher, "POST", "/api/launch", function(answer, err)
      if not answer then
        return say(err.missing and no_watcher(watcher.top) or err.message, vim.log.levels.WARN)
      end
      local handle, open_err = vim.ui.open(answer.url)
      if not handle and open_err then
        return say("Could not open the browser: " .. open_err, vim.log.levels.WARN)
      end
      say("Opened the review in the browser")
    end)
  end)
end

-- Viewed files --------------------------------------------------------------------

--- Side by side, on or off, for the file in the current window: gitsigns' diffthis against the base of the
--- view shown (the base gitsigns.lua pointed it at, given explicitly: never typed), the old version on the left
--- and the reviewer's file on the right, where the cursor stays. Off, from either side: the old version's window
--- closes, the reviewer's file leaves the diff (:diffoff gives back the options diff mode set), the cursor goes back
--- to it. gitsigns builds the split: this adds no option of its own.
-- What diff mode (Neovim's own, through gitsigns' diffthis) changes and :diffoff never gives back, as it was
-- before: 'scrollopt' (diff mode adds "hor") and the reviewer's window's 'foldenable' (diff mode leaves it off).
-- Put back when the split closes, so side by side leaves nothing behind.
local before_diff -- { scrollopt, win, foldenable }

function M.toggle_side_by_side()
  local review = open_review("compare side by side")
  if not review then
    return
  end
  if not review.signs then
    say("gitsigns is not here: side by side needs it")
    return
  end
  local here = vim.api.nvim_get_current_win()
  local old, mine
  for _, win in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    if vim.wo[win].diff then
      if vim.startswith(vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf(win)), "gitsigns://") then
        old = win
      elseif win == here or not mine then
        mine = win
      end
    end
  end
  if vim.wo[here].diff then
    if not (old and mine) then
      say("This window is in a diff difftate didn't open: close it to use side by side")
      return
    end
    vim.api.nvim_win_call(mine, function()
      vim.cmd("diffoff")
    end)
    vim.api.nvim_win_close(old, true)
    vim.api.nvim_set_current_win(mine)
    if before_diff then
      if vim.o.scrollopt == before_diff.scrollopt .. ",hor" then -- nobody changed it since
        vim.o.scrollopt = before_diff.scrollopt
      end
      if before_diff.win == mine then
        vim.wo[mine].foldenable = before_diff.foldenable
      end
      before_diff = nil
    end
    return
  end
  if not vim.b[vim.api.nvim_get_current_buf()].gitsigns_status_dict then
    say("Open a file of the repository to compare it side by side")
    return
  end
  local _, commit = gitsigns.pointed()
  -- The index, as gitsigns names it, when the view shown compares with the index (the unstaged one)
  before_diff = { scrollopt = vim.o.scrollopt, win = here, foldenable = vim.wo[here].foldenable }
  require("gitsigns").diffthis(commit or ":0")
end

--- Mark the file of the current buffer viewed, or not (PUT /api/viewed), as the browser's checkbox does:
--- the review API keeps the mark until the file's diff changes. From what it says now, so a mark made in
--- another viewer isn't marked again blindly. A file that isn't in the changeset says so and changes nothing.
function M.toggle_viewed()
  local review = open_review("mark a file viewed")
  if not review then
    return
  end
  local buf = vim.api.nvim_get_current_buf()
  local path, why = path_in_review(review, buf)
  if not path then
    local not_a_file = vim.bo[buf].buftype ~= "" or vim.api.nvim_buf_get_name(buf) == ""
    say(not_a_file and "Open a changed file to mark it viewed" or why)
    return
  end
  api.request(review.watcher, "GET", "/api/changeset?view=", function(changeset, err)
    if not changeset then
      return failed(review, err)
    end
    local changed = false
    for _, file in ipairs(nav.files(changeset.diff or "")) do
      changed = changed or file.path == path
    end
    if not changed then
      say(("%s is not in the changeset: nothing to mark viewed"):format(path))
      return
    end
    api.request(review.watcher, "GET", "/api/viewed", function(now, err2)
      if not now then
        return failed(review, err2)
      end
      local viewed = not vim.tbl_contains(now.files or {}, path)
      api.request(review.watcher, "PUT", "/api/viewed", function(answer, err3)
        if not answer then
          return failed(review, err3)
        end
        say(viewed and ("Viewed " .. path) or ("Not viewed: " .. path))
      end, { file = path, viewed = viewed })
    end)
  end)
end

-- Views ----------------------------------------------------------------------------

-- Show <chosen> in every viewer (PUT /api/view: the watcher keeps it), then point git signs at its base and
-- draw the threads the view shows
local function switch_view(review, chosen)
  api.request(review.watcher, "PUT", "/api/view", function(answer, err)
    if current ~= review then
      return
    end
    if not answer then
      say(err.missing and no_watcher(review.watcher.top)
        or ("Can't show %s: %s"):format(view.label(chosen), err.message), vim.log.levels.ERROR)
      return
    end
    review.view_stamp = (review.view_stamp or 0) + 1
    know_view(review, { view = answer.view or chosen })
    say("Showing " .. view.label(chosen))
    follow_base(review, function(why)
      if why then
        say(why, vim.log.levels.WARN)
      end
      review.base_error = why
      look.redraw()
      refresh(review)
    end)
  end, { view = chosen })
end

--- The views picker: all changes, the uncommitted and the unstaged ones, and the last commit and the last
--- few commits with their subjects (the staged view stays in the browser). The chosen view is shown in every
--- viewer, as the browser's menu does.
function M.pick_view()
  local review = open_review("choose the view")
  if not review then
    return
  end
  local range = (review.merge_base or review.base) .. "..HEAD"
  git.run(review.watcher.top, { "log", "--format=%h %s", "-n", "30", range }, function(out)
    if current ~= review then
      return
    end
    local commits = vim.tbl_filter(function(line)
      return line ~= ""
    end, vim.split(out or "", "\n"))
    pick.choose(view.entries(commits, review.view, review.base), "Review views", function(chosen)
      if current ~= review then
        return
      end
      if chosen == review.view then
        say("Already showing " .. view.label(chosen))
        return
      end
      switch_view(review, chosen)
    end)
  end)
end

-- ]r, [r and the pickers ------------------------------------------------------

-- The review's threads and its changeset's files as they are now: then_(threads, files, diff
-- files) once both came; a request that failed says why (unless <quiet>) and calls nothing.
local function snapshot(review, then_, quiet)
  local function failed(err)
    if quiet then
      return
    end
    say(err.missing and no_watcher(review.watcher.top) or err.message, vim.log.levels.ERROR)
  end
  api.request(review.watcher, "GET", view.query("/api/threads", shown_view(review)), function(listed, err)
    if not listed then
      return failed(err)
    end
    api.request(review.watcher, "GET", view.query("/api/changeset", shown_view(review)), function(changeset, why)
      if not changeset then
        return failed(why)
      end
      if current == review then
        local diff_text = changeset.diff or ""
        then_(listed, nav.files(diff_text), diff.parse(diff_text))
      end
    end)
  end)
end

-- Open <path> (in the review's folder) in the current window, unless it is the one it
-- shows: reloading it would run the reviewer's file autocmds again. False (and says
-- why) when it can't be opened, such as with unsaved changes in the way.
local function open_file(review, path)
  float.close()
  review.visited = nil
  if path_in_review(review, vim.api.nvim_get_current_buf()) == path then
    return true
  end
  local top = vim.uv.fs_realpath(review.watcher.top) or review.watcher.top
  local ok, err = pcall(vim.cmd.edit, vim.fn.fnameescape(top .. "/" .. path))
  if not ok then
    say(tostring(err), vim.log.levels.ERROR)
  end
  return ok
end

-- Put the cursor of the current window on <row> of its buffer (the jump list keeps where it was)
local function go_to_line(row)
  vim.cmd("normal! m'")
  vim.api.nvim_win_set_cursor(0, { math.max(1, math.min(row, vim.api.nvim_buf_line_count(0))), 0 })
  vim.cmd("normal! ^zvzz")
end

-- Go to <thread>: where it is drawn (opening its file when the cursor is in another), or, for a
-- thread with no line (a general one, or one whose code is on another branch), its read float
local function go_to(review, thread, parsed)
  local at = draw.where(thread, parsed)
  review.visited = nil
  if not at then
    float.open(thread)
    return
  end
  if not open_file(review, at.path) then
    return
  end
  vim.cmd("normal! m'") -- the jump list: <C-o> goes back
  local row = math.min(at.row, vim.api.nvim_buf_line_count(0))
  vim.api.nvim_win_set_cursor(0, { row, 0 })
  vim.cmd("normal! ^zvzz")
  review.visited = { id = thread.id, path = at.path, row = row }
end

-- Where the cursor is, for a step: nil outside the review's files; the general thread the
-- read float shows; else the file and line (and the thread last visited when it is still there)
local function whereabouts(review, parsed)
  local buf = vim.api.nvim_get_current_buf()
  local read = float.thread_in(buf)
  if read then
    if not read.anchor then
      return { general = read.id }
    end
    local at = draw.where(read, parsed)
    return at and { path = at.path, line = at.row, thread = read.id } or nil
  end
  local path = path_in_review(review, buf)
  if not path then
    return nil
  end
  local line = vim.api.nvim_win_get_cursor(0)[1]
  local visited = review.visited
  return { path = path, line = line,
           thread = visited and visited.path == path and visited.row == line and visited.id or nil }
end

--- Go to the next (<direction> 1) or previous (-1) open thread: general threads first,
--- then across the files, opening the next file; at the end it wraps round, and says so.
function M.step_thread(direction)
  local review = open_review("go to a thread")
  if not review then
    return
  end
  snapshot(review, function(listed, files, parsed)
    local sequence = nav.sequence(listed, files, function(thread)
      return draw.where(thread, parsed)
    end)
    local entry, wrapped = nav.step(sequence, files, whereabouts(review, parsed), direction)
    if not entry then
      say("No open threads")
      return
    end
    go_to(review, entry.thread, parsed)
    if wrapped then
      say(("Wrapped to the %s open thread"):format(direction > 0 and "first" or "last"))
    end
  end)
end

--- The threads picker: every thread, outdated ones too, general threads at the top. A
--- thread on a line is gone to; a general one opens in the read float.
function M.pick_thread()
  local review = open_review("list its threads")
  if not review then
    return
  end
  snapshot(review, function(listed, files, parsed)
    if #listed == 0 then
      say("No threads in this review")
      return
    end
    local entries = vim.tbl_map(function(thread)
      return { text = nav.thread_row(thread), value = thread }
    end, nav.picker_threads(listed, files))
    pick.choose(entries, "Review threads", function(thread)
      if current == review then
        go_to(review, thread, parsed)
      end
    end)
  end)
end

-- The review path the coding agent wrote in the review's folder: on_written(written), nil when there
-- is none, or when the watcher can't say (one older than the review path): the picker is then as before.
-- In the view the review shows, the path is cut down to that view's files, as its files are
local function written_path(review, on_written)
  api.request(review.watcher, "GET", view.query("/api/review-path", shown_view(review)), function(answer)
    on_written(answer and answer.path or nil)
  end)
end

-- The rows of the changed files (the picker's and the sidebar's): on_entries(entries) once they are
-- known; a failed request says why (when <quiet> is not set) and calls nothing. With a review
-- path, its stops come first in reading order as a tree, then the files it skips, then the
-- files it doesn't name; with none, every file in the changeset's order. Called with no entries
-- when the changeset has no file.
local function file_entries(review, quiet, on_entries)
  api.request(review.watcher, "GET", "/api/viewed", function(answer, err)
    if current ~= review then
      return
    end
    if not answer then
      if not quiet then
        say(err.missing and no_watcher(review.watcher.top) or err.message, vim.log.levels.ERROR)
      end
      return
    end
    local viewed = {}
    for _, path in ipairs(answer.files or {}) do
      viewed[path] = true
    end
    written_path(review, function(written)
      if current ~= review then
        return
      end
      snapshot(review, function(_, files)
        local entries = {}
        if written then
          entries = review_path.entries(written, files, viewed)
        else
          for _, file in ipairs(files) do
            table.insert(entries, { text = nav.file_row(file, viewed[file.path]), value = file })
          end
        end
        on_entries(#files > 0 and entries or {})
      end, quiet)
    end)
  end)
end

-- What choosing the file <file> of a row does: open it (at its line, when the row has one)
local function open_row(review, file)
  if current ~= review then
    return
  end
  if file.deleted then
    say(("%s was deleted: there is no file to open"):format(file.path))
    return
  end
  if open_file(review, file.path) and file.line then
    go_to_line(file.line)
  end
end

-- The row that shows the file the current buffer is, for a list to start on
local function row_of_here(review)
  local here = path_in_review(review, vim.api.nvim_get_current_buf())
  return function(file)
    return file.path == here
  end
end

--- The changed files picker: the changeset's files, viewed ones marked; the picked one opens.
function M.pick_file()
  local review = open_review("list its files")
  if not review then
    return
  end
  file_entries(review, false, function(entries)
    if #entries == 0 then
      say("No changed files in this review")
      return
    end
    pick.choose(entries, "Changed files", function(file)
      open_row(review, file)
    end, { current = row_of_here(review) })
  end)
end

-- The changed files sidebar -----------------------------------------------------

-- Show the sidebar of <review>; the rows come in a moment. <by_key>: the reviewer asked for it, so the
-- cursor goes into it, and it says when there is no Snacks to show it with.
function show_sidebar(review, by_key)
  if not pick.can_sidebar() then
    if by_key then
      say("The files sidebar needs Snacks.picker (LazyVim's picker): <leader>rf lists the files")
    end
    return -- no request for rows that nothing would show
  end
  file_entries(review, true, function(entries)
    if current ~= review or (review.sidebar and review.sidebar.is_open()) then
      return
    end
    review.sidebar = pick.sidebar(entries, "Changed files", function(file)
      open_row(review, file)
    end, { focus = by_key, current = row_of_here(review) })
  end)
end

-- Bring the rows of the open sidebar up to date: they change with the viewed marks, the files and the path
function refresh_sidebar(review)
  if review.sidebar and review.sidebar.is_open() then
    file_entries(review, true, function(entries)
      if current == review and review.sidebar then
        review.sidebar.update(entries)
      end
    end)
  end
end

--- Show the sidebar of the open review, or hide it when it is shown (<leader>rF).
function M.toggle_files_sidebar()
  local review = open_review("show its files")
  if not review then
    return
  end
  if review.sidebar and review.sidebar.is_open() then
    review.sidebar.close()
    return
  end
  show_sidebar(review, true)
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
  local parts = { "review open" }
  local function add(part)
    if part then
      table.insert(parts, part)
    end
  end
  add(current.unreadable and ("showing all changes: git can't find " .. current.view)
    or view.status_part(current.view))
  add(mode.label(current.mode))
  add(agent.label(current.agent))
  add(done.label(current.done))
  local signs = view.signs_phrase(shown_view(current), current.base)
  if not current.signs then
    table.insert(parts, ("gitsigns isn't loaded: no git signs for %s"):format(signs))
  else
    table.insert(parts, ("git signs show %s"):format(signs))
  end
  return table.concat(parts, " · ")
end

return M
