// Pure colour logic for the rainbow selection, the bit squares and the reverse groups (no DOM, no three.js).

function hsl(h, s, l) {
  const a = s * Math.min(l, 1 - l), f = (n) => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  const hx = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + hx(f(0)) + hx(f(8)) + hx(f(4));
}

// colour of position k of n, red (first) to violet (last); n = 1 gives red
export function rainbow(k, n) {
  const t = n <= 1 ? 0 : Math.max(0, Math.min(1, k / (n - 1)));
  return hsl(270 * t, 0.85, 0.55);
}

// the fixed sequence of group colours: red, orange, yellow, green, cyan, blue, indigo, violet
export const GROUP_COLOURS = ["#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#32d3e8", "#2f6bff", "#5b3fd6", "#b455e8"];
export const groupColour = (g) => GROUP_COLOURS[((g % 8) + 8) % 8];

// owners: Map object id -> sorted list of owner numbers. `add` puts owner o on every id of a set.
function addOwner(owners, ids, o) {
  for (const id of ids) {
    const l = owners.get(id);
    if (!l) owners.set(id, [o]);
    else if (!l.includes(o)) { l.push(o); l.sort((a, b) => a - b); }
  }
}

// Forward: lines[k] = start (HDL) ids of selected line k; reach(ids) -> iterable of every id the line reaches
// (the start ids included). Lines with the same start ids share one reach.
export function lineOwners(lines, reach) {
  const owners = new Map(), cache = new Map();
  lines.forEach((ids, k) => {
    if (!ids.length) return;
    const key = [...ids].sort().join("|");
    if (!cache.has(key)) cache.set(key, [...reach(ids)]);
    addOwner(owners, cache.get(key), k);
  });
  return owners;
}

// Reverse: groups[g] = ids clicked into group g; reach(id) -> iterable of the ids linked to it (the id included)
export function groupOwners(groups, reach) {
  const owners = new Map(), cache = new Map();
  groups.forEach((g, k) => {
    for (const id of g.ids) {
      if (!cache.has(id)) cache.set(id, [...reach(id)]);
      addOwner(owners, cache.get(id), k);
    }
  });
  return owners;
}

// Group bookkeeping. state = { groups: [{ colour, ids }], next }. A group keeps the colour it was created with.
export const newGroups = () => ({ groups: [], next: 0 });
export function addGroup(st, id) {
  st.groups.push({ colour: st.next % 8, ids: [id] });
  st.next++;
  return st.groups.length - 1;
}
export function addToCurrent(st, id) {
  if (!st.groups.length) return addGroup(st, id);
  const g = st.groups[st.groups.length - 1];
  if (!g.ids.includes(id)) g.ids.push(id);
  return st.groups.length - 1;
}
export function clearGroups(st) { st.groups = []; st.next = 0; }

// items [{ file, l0, l1, owner }] -> Map file -> Map line -> sorted unique owners
export function lineMap(items) {
  const out = new Map();
  for (const { file, l0, l1, owner } of items) {
    const m = out.get(file) ?? out.set(file, new Map()).get(file);
    for (let l = l0; l <= l1; l++) {
      const o = m.get(l);
      if (!o) m.set(l, [owner]);
      else if (!o.includes(owner)) { o.push(owner); o.sort((a, b) => a - b); }
    }
  }
  return out;
}

// CSS background-image with one hard-edged vertical bar per colour, `w` px wide each, from the left
export function barGradient(cols, w = 4) {
  if (!cols.length) return "";
  return "linear-gradient(to right," + cols.map((c, i) => `${c} ${i * w}px ${(i + 1) * w}px`).join(",") + `,transparent ${cols.length * w}px)`;
}

// Bit square of an object: colours MSb..LSb (one colour = a plain square), or null.
// bit: offset from the LSb (null for a whole-bus object), busk "own" | "cone", width: bus width.
export function bitStripes(bus, bit, busk, width, maxStripes = 8) {
  if (!bus) return null;
  if (bit !== null && bit !== undefined) return [rainbow(bit, width)];
  if (busk !== "own" || width <= 1) return busk === "own" && width === 1 ? [rainbow(0, 1)] : null;
  const n = Math.min(width, maxStripes), out = [];
  for (let i = 0; i < n; i++) {
    const bitAt = n === width ? width - 1 - i : Math.round((width - 1) * (1 - i / (n - 1)));
    out.push(rainbow(bitAt, width));
  }
  return out;
}

// equal slices of a disc: [{ a0, a1, colour }] in turns (0..1)
export function pieSlices(cols) {
  return cols.map((colour, i) => ({ a0: i / cols.length, a1: (i + 1) / cols.length, colour }));
}
