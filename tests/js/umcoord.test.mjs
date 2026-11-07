import test from "node:test";
import assert from "node:assert/strict";
import { isUm, zOf, outlines, rowLines, netSegments, coreSize } from "../../heimdall/web/umcoord.js";

// the tiny fixture of tests/data/silicon: die 20 x 20 um, core [1,2,5.6,7.44], two rows of 2.72 um
const coord = {
  kind: "um", unit: "um", flip_y: 20, bounds: [0, 0, 20, 20], core: [1, 2, 5.6, 7.44],
  rows: { count: 2, pitch_um: 2.72, y0_um: 2, x0_um: 1, x1_um: 5.6 },
};

test("only um coordinates are physical", () => {
  assert.equal(isUm(coord), true);
  assert.equal(isUm({ kind: "grid" }), false);
  assert.equal(isUm(undefined), false);
});

test("y is flipped about the die top", () => {
  assert.equal(zOf(coord, 0), 20);
  assert.equal(zOf(coord, 20), 0);
  assert.equal(zOf({ kind: "um" }, 3), -3);
});

test("die and core outlines are two closed rectangles in um", () => {
  const o = outlines(coord);
  assert.equal(o.length, 8);
  assert.deepEqual(o[0], [0, 0, 20, 0]); // die top edge: y = 20 -> z = 0
  assert.deepEqual(o[2], [20, 20, 0, 20]); // die bottom edge: y = 0 -> z = 20
  assert.ok(Math.abs(o[4][1] - 12.56) < 1e-9 && o[4][0] === 1 && o[4][2] === 5.6); // core top edge
});

test("one row line between two rows, at the row pitch", () => {
  const r = rowLines(coord);
  assert.equal(r.length, 1);
  assert.deepEqual([r[0][0], r[0][2]], [1, 5.6]);
  assert.ok(Math.abs(r[0][1] - 15.28) < 1e-9 && r[0][1] === r[0][3]);
  assert.deepEqual(rowLines({ kind: "um", bounds: [0, 0, 1, 1] }), []);
});

test("a net's polyline segments follow routes.json and keep the layer", () => {
  const segs = [[0, 2.0, 3.0, 6.0, 3.0], [1, 6.0, 3.0, 6.0, 5.0, 6.0, 7.0]];
  const out = netSegments(coord, segs);
  assert.deepEqual(out[0], { layer: 0, seg: [2, 17, 6, 17] });
  assert.deepEqual(out[1], { layer: 1, seg: [6, 17, 6, 15] });
  assert.deepEqual(out[2], { layer: 1, seg: [6, 15, 6, 13] }); // a polyline of three points
  assert.deepEqual(netSegments(coord, undefined), []);
});

test("core size in um", () => {
  const [w, h] = coreSize(coord);
  assert.ok(Math.abs(w - 4.6) < 1e-9 && Math.abs(h - 5.44) < 1e-9);
  assert.equal(coreSize({ kind: "um" }), null);
});
