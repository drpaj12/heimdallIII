import test from "node:test";
import assert from "node:assert/strict";
import { rainbow, GROUP_COLOURS, groupColour, lineOwners, groupOwners, newGroups, addGroup, addToCurrent, clearGroups, lineMap, barGradient, bitStripes, pieSlices } from "../../heimdall/web/rainbow.js";

test("rainbow: n = 1 is red, first red, last violet, even in between", () => {
  assert.equal(rainbow(0, 1), "#ee2b2b");
  assert.equal(rainbow(0, 5), "#ee2b2b");
  const hue = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return Math.round(((h * 60) + 360) % 360);
  };
  assert.equal(hue(rainbow(0, 4)), 0);
  assert.equal(hue(rainbow(1, 4)), 90);
  assert.equal(hue(rainbow(2, 4)), 180);
  assert.equal(hue(rainbow(3, 4)), 270);
  assert.equal(hue(rainbow(9, 4)), 270); // clamped
  assert.equal(hue(rainbow(1, 3)), 135);
});

test("group colours: fixed 8 steps, wrap", () => {
  assert.equal(GROUP_COLOURS.length, 8);
  assert.equal(new Set(GROUP_COLOURS).size, 8);
  assert.equal(groupColour(0), GROUP_COLOURS[0]);
  assert.equal(groupColour(8), GROUP_COLOURS[0]);
  assert.equal(groupColour(9), GROUP_COLOURS[1]);
});

test("lineOwners: one line one colour, shared objects list every line, empty lines skipped", () => {
  const reach = (ids) => ids.flatMap((i) => ({ a: ["a", "x"], b: ["b", "x"] }[i]));
  const o = lineOwners([["a"], [], ["b"]], reach);
  assert.deepEqual(o.get("a"), [0]);
  assert.deepEqual(o.get("b"), [2]);
  assert.deepEqual(o.get("x"), [0, 2]);
  assert.equal(o.has("zz"), false);
});

test("lineOwners: two lines with the same constructs share one reach call", () => {
  let calls = 0;
  const o = lineOwners([["a", "b"], ["b", "a"]], (ids) => { calls++; return ids; });
  assert.equal(calls, 1);
  assert.deepEqual(o.get("a"), [0, 1]);
});

test("group bookkeeping: new colours in order, add to current, wrap, clear", () => {
  const st = newGroups();
  assert.equal(addGroup(st, "p"), 0);
  assert.equal(addGroup(st, "q"), 1);
  assert.equal(addToCurrent(st, "r"), 1);
  addToCurrent(st, "r");
  assert.deepEqual(st.groups.map((g) => g.ids), [["p"], ["q", "r"]]);
  assert.deepEqual(st.groups.map((g) => g.colour), [0, 1]);
});

test("group bookkeeping: colour wraps after 8 and a group keeps it", () => {
  const st = newGroups();
  for (let i = 0; i < 9; i++) addGroup(st, "o" + i);
  assert.equal(st.groups[8].colour, 0);
  assert.equal(st.groups[3].colour, 3);
  clearGroups(st);
  assert.equal(st.groups.length, 0);
  assert.equal(addGroup(st, "n"), 0);
  assert.equal(st.groups[0].colour, 0);
  const s2 = newGroups();
  assert.equal(addToCurrent(s2, "first"), 0); // add with no group starts one
});

test("groupOwners: shared object has both groups, each id reach computed once", () => {
  let calls = 0;
  const links = { p: ["p", "m", "s"], q: ["q", "s"], r: ["r", "s"] };
  const st = newGroups();
  addGroup(st, "p"); addGroup(st, "q"); addToCurrent(st, "r");
  const o = groupOwners(st.groups, (id) => { calls++; return links[id]; });
  assert.deepEqual(o.get("m"), [0]);
  assert.deepEqual(o.get("s"), [0, 1]);
  assert.deepEqual(o.get("r"), [1]);
  assert.equal(calls, 3);
});

test("lineMap: one bar per owner on a shared line", () => {
  const m = lineMap([{ file: "a.v", l0: 3, l1: 5, owner: 0 }, { file: "a.v", l0: 5, l1: 6, owner: 1 }, { file: "a.v", l0: 5, l1: 5, owner: 1 }]);
  assert.deepEqual(m.get("a.v").get(3), [0]);
  assert.deepEqual(m.get("a.v").get(5), [0, 1]);
  assert.deepEqual(m.get("a.v").get(6), [1]);
  assert.equal(m.get("a.v").has(7), false);
});

test("barGradient: hard stops, empty for none", () => {
  assert.equal(barGradient([]), "");
  assert.match(barGradient(["#111111", "#222222"]), /#111111 0px 4px,#222222 4px 8px/);
});

test("bitStripes: a bit is one colour LSb red MSb violet, a word is striped MSb..LSb, cone none", () => {
  assert.deepEqual(bitStripes("a", 0, "own", 8), [rainbow(0, 8)]);
  assert.deepEqual(bitStripes("a", 7, "own", 8), [rainbow(7, 8)]);
  assert.equal(bitStripes(null, 0, "own", 8), null);
  assert.equal(bitStripes("a", null, "cone", 8), null);
  assert.deepEqual(bitStripes("a", null, "own", 4), [rainbow(3, 4), rainbow(2, 4), rainbow(1, 4), rainbow(0, 4)]);
  const w = bitStripes("a", null, "own", 32);
  assert.equal(w.length, 8);
  assert.equal(w[0], rainbow(31, 32));
  assert.equal(w[7], rainbow(0, 32));
  assert.deepEqual(bitStripes("a", null, "own", 1), [rainbow(0, 1)]);
});

test("pieSlices: equal turns in order", () => {
  assert.deepEqual(pieSlices(["#1", "#2", "#3", "#4"]).map((s) => [s.a0, s.a1]), [[0, 0.25], [0.25, 0.5], [0.5, 0.75], [0.75, 1]]);
});
