// Draws the Conversation tab (conversation.js): the timeline of threads, and the box for a general
// thread under it. A thread's card and a box keep their nodes through a poll (draw_threads.js).

import { drawBox, drawThread } from "./draw_threads.js";
import { place } from "./dom.js";

/** The Conversation tab's model, drawn. on: draw_threads.js's. */
export function drawConversation({ threads, empty, general }, on) {
  document.getElementById("no-threads").textContent = empty;
  document.getElementById("no-threads").hidden = !empty;
  place(document.getElementById("timeline"), threads.map((t) => drawThread(t, on)));
  place(document.getElementById("general"), [drawBox(general, on)]);
}
