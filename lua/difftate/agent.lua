-- Which coding agent replies in the review, as text (GLOSSARY.md: Agent override). Pure: no editor, no request.
-- The words are the browser viewer's (lib/difftate/adapters/inbound/review_api/web/app.js). <agent> is what
-- GET /api/agent answers: { agent = a name, source = "review" | "repository" | "machine", names = { the machine's list } }.
local M = {}

--- Whether <agent> is the review's own choice, not the repository's or the machine's.
function M.is_own(agent)
  return agent ~= nil and agent.source == "review"
end

--- What the statusline note says of the agent: "agent work", "agent work (this review)"; nil when it isn't known.
function M.label(agent)
  if not agent then
    return nil
  end
  return ("agent %s%s"):format(agent.agent, M.is_own(agent) and " (this review)" or "")
end

--- The entries of the picker, { { text, value } }: first the review without a choice of its own (value ""), then
--- each agent of the list.
function M.entries(agent)
  local own = M.is_own(agent)
  local entries = {
    { text = own and "Default (clears this review's choice)" or ("Default: %s (the %s's)"):format(agent.agent, agent.source),
      value = "" },
  }
  for _, name in ipairs(agent.names or {}) do
    table.insert(entries, { text = (own and name == agent.agent) and (name .. " (this review)") or name, value = name })
  end
  return entries
end

--- Why choosing <chosen> ("" for the default) changes nothing, or nil when it changes the review.
function M.already(agent, chosen)
  if chosen == "" and not M.is_own(agent) then
    return ("The review has no agent of its own: %s replies"):format(agent.agent)
  end
  if chosen ~= "" and M.is_own(agent) and chosen == agent.agent then
    return ("%s replies in this review already"):format(chosen)
  end
  return nil
end

--- Said after the choice was kept: <answer> is what PUT /api/agent answered, <chosen> what was chosen.
function M.changed_message(answer, chosen)
  if chosen == "" then
    return ("The review's own agent is cleared: %s replies, from the next run"):format(answer.agent)
  end
  return ("%s replies in this review, from the next run"):format(answer.agent)
end

return M
