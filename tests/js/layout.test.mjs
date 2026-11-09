import test from "node:test";
import assert from "node:assert/strict";
import { parseState, toggled, panelForKey, gridColumns, load, save } from "../../heimdall/web/layout.js";

test("state parses, defaults to open and survives garbage", () => {
  assert.deepEqual(parseState(null), { left: false, hdl: false, right: false });
  assert.deepEqual(parseState("not json"), { left: false, hdl: false, right: false });
  assert.deepEqual(parseState('{"hdl":true,"x":true}'), { left: false, hdl: true, right: false });
});

test("toggle flips one panel and ignores unknown names", () => {
  const s = toggled(parseState(null), "right");
  assert.deepEqual(s, { left: false, hdl: false, right: true });
  assert.deepEqual(toggled(s, "right"), parseState(null));
  assert.equal(toggled(s, "nope"), s);
});

test("keys do not clash with the plane keys 0-9", () => {
  assert.equal(panelForKey("["), "left");
  assert.equal(panelForKey("h"), "hdl");
  assert.equal(panelForKey("]"), "right");
  for (let d = 0; d <= 9; d++) assert.equal(panelForKey(String(d)), null);
});

test("grid columns shrink collapsed side panels to a strip", () => {
  assert.equal(gridColumns({ left: false, hdl: false, right: false }), "230px minmax(0,1fr) 320px");
  assert.equal(gridColumns({ left: true, hdl: false, right: true }), "26px minmax(0,1fr) 26px");
});

test("state round-trips through storage", () => {
  const m = new Map();
  const st = { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
  save(st, { left: true, hdl: false, right: false });
  assert.deepEqual(load(st), { left: true, hdl: false, right: false });
});

test("nothing stored: open on a wide screen, collapsed on a narrow one; stored state wins", () => {
  const empty = { getItem: () => null };
  assert.deepEqual(load(empty), { left: false, hdl: false, right: false });
  assert.deepEqual(load(empty, true), { left: true, hdl: true, right: true });
  const kept = { getItem: () => '{"left":true}' };
  assert.deepEqual(load(kept, true), { left: true, hdl: false, right: false });
});
