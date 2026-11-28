// The little layout D draws with: elements, icons, and putting nodes in place.

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c);
  return node;
}

// Simple stroked shapes on a 16 by 16 grid
const ICONS = {
  open: "M4 6l4 4 4-4", folded: "M6 4l4 4-4 4",
  file: "M4 2h5l3 3v9H4zM9 2v3h3", folder: "M2 4h4l1.5 1.5H14V13H2z",
  comment: "M2 3h12v8H8l-3 3v-3H2z", check: "M3 8.5l3 3 7-7",
  sun: "M8 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.5 1.5M11.5 11.5L13 13M13 3l-1.5 1.5M4.5 11.5L3 13",
  moon: "M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7z",
  settings: "M2 4.5h6M12 4.5h2M2 11.5h2M8 11.5h6M10 2.5v4M6 9.5v4",
};

export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

/** Make <nodes> the children of <parent>. One that is in place already isn't touched, so the
 *  text the reviewer selected in it stays selected. */
export function place(parent, nodes) {
  for (const child of [...parent.children]) if (!nodes.includes(child)) child.remove();
  nodes.forEach((node, i) => {
    if (parent.children[i] !== node) parent.insertBefore(node, parent.children[i] ?? null);
  });
}

/** A drawer (key, model, draw): the node drawn for <key> before when <model> is the same, else a
 *  new one from draw(model). */
export function keptWhileSame() {
  const nodes = new Map();
  return (key, model, draw) => {
    const sig = JSON.stringify(model);
    let had = nodes.get(key);
    if (had?.sig !== sig) nodes.set(key, (had = { sig, node: draw(model) }));
    return had.node;
  };
}

/** A drawer (key, model, ...more) of parts that change in place: make(key, ...more) gives {node,
 *  update(model)}, once for each key. The key's node, updated to <model>. */
export function keptByKey(make) {
  const parts = new Map();
  return (key, model, ...more) => {
    const part = parts.get(key) ?? parts.set(key, make(key, ...more)).get(key);
    part.update(model);
    return part.node;
  };
}

/** Set <node>'s text, leaving it alone (and what is selected in it) when it says that already. */
export function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}
