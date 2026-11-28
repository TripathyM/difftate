-- The review mode and Submit, as text (GLOSSARY.md: Review mode, Live, Batched, Submit). Pure: no
-- editor, no request. The words follow the browser viewer's (lib/difftate/adapters/inbound/review_api/web/d/:
-- submit.js, actions.js setMode). <mode> is what GET /api/mode
-- answers: { mode = "live" | "batched", held = { thread ids } }.
local M = {}

--- "2 held threads", "1 held thread"
function M.held_count(n)
  return ("%d held thread%s"):format(n, n == 1 and "" or "s")
end

--- Whether <mode> is a batched review's.
function M.is_batched(mode)
  return mode ~= nil and mode.mode == "batched"
end

--- The mode a change from <mode> goes to.
function M.other(mode)
  return M.is_batched(mode) and "live" or "batched"
end

--- What the statusline note says of the mode: "live", "batched · 2 held"; nil when it isn't known.
function M.label(mode)
  if not mode then
    return nil
  end
  if M.is_batched(mode) then
    return ("batched · %d held"):format(#(mode.held or {}))
  end
  return "live"
end

--- Said after the review was changed to the mode called <name> ("live" or "batched"); <submitted> is
--- the ids the change sent (a change to live submits what is held).
function M.changed_message(name, submitted)
  if name == "batched" then
    return "Batched: comments are held until you submit"
  end
  if submitted and #submitted > 0 then
    return ("Live: %s submitted to the coding agent"):format(M.held_count(#submitted))
  end
  return "Live: comments go to the coding agent as you write them"
end

--- Why Submit does nothing in <mode>, or nil when there are held threads to submit.
function M.submit_problem(mode)
  if not M.is_batched(mode) then
    return "Not a batched review: nothing to submit"
  end
  if #(mode.held or {}) == 0 then
    return "Nothing is held: nothing to submit"
  end
  return nil
end

--- Said after a Submit; <submitted> is the ids it sent.
function M.submitted_message(submitted)
  if submitted and #submitted > 0 then
    return "Submitted " .. M.held_count(#submitted)
  end
  return "Nothing is held: nothing to submit"
end

--- Said after a comment or a thread was written: <sent> when the review is live, else that it is held.
function M.comment_message(mode, sent)
  return M.is_batched(mode) and "Comment held until you submit" or sent
end

return M
