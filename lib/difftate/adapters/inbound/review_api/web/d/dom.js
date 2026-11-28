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
