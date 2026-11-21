// Warnings about the review (the API's "warnings": each with an id, a time and a text): the page
// shows each one once, whatever the number of polls that still carry it.

// The warnings in <warnings> whose ids are not in <seen> (a Set), in order; their ids are added to <seen>.
export function unseen(warnings, seen) {
  const fresh = [];
  for (const w of warnings ?? []) {
    if (seen.has(w.id)) continue;
    seen.add(w.id);
    fresh.push(w);
  }
  return fresh;
}
