-- The order of what is drawn in one gap between two lines, which is the order of the marks'
-- columns: Neovim promises no order for the virtual lines of marks at one position, but it draws
-- those at different columns left to right. (A column past the end of a short line is clamped to
-- it, so the order is only certain across rows: see look.lua for the deleted text, which sits on
-- the line after its gap for that reason.)
return {
  threads = 0, -- threads on the line before the gap
  deleted_text = 1, -- the diff look's deleted text (look.lua)
  threads_on_deleted = 2, -- threads on the deleted lines, which quote their code (draw.lua)
}
