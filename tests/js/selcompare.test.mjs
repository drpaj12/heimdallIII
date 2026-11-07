import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { signature, gddAgreement, cosineLog, selectionSignature, compareSignatures } from "../../heimdall/web/selcompare.js";

const fx = JSON.parse(readFileSync(new URL("../data/selcompare/fixture.json", import.meta.url), "utf8"));

// The fixture holds Odin III's metrics at full double precision (odin3.graphlet_similarity), so a faithful port agrees to 1e-9.
const TOL = 1e-9;

test("browser metrics equal Odin III's on every fixture case", () => {
  assert.ok(fx.cases.length >= 30);
  let maxG = 0, maxC = 0;
  for (const c of fx.cases) {
    const g = fx.graphs[c.graph];
    const a = signature(g.rows, c.a, g.n_orbits), b = signature(g.rows, c.b, g.n_orbits);
    const r = compareSignatures(a, b);
    maxG = Math.max(maxG, Math.abs(r.gdd - c.gdd_agreement));
    maxC = Math.max(maxC, Math.abs(r.cosine - c.cosine_log));
    assert.ok(Math.abs(r.gdd - c.gdd_agreement) <= TOL, `gdd ${g.name} ${r.gdd} vs ${c.gdd_agreement}`);
    assert.ok(Math.abs(r.cosine - c.cosine_log) <= TOL, `cosine ${g.name} ${r.cosine} vs ${c.cosine_log}`);
  }
  console.log(`max abs diff: gdd ${maxG.toExponential(2)}, cosine ${maxC.toExponential(2)}`);
});

test("both modes and edge cases are covered by the fixture", () => {
  assert.deepEqual([...new Set(fx.graphs.map((g) => g.mode))].sort(), ["d", "u"]);
  assert.deepEqual(fx.graphs.map((g) => g.n_orbits), [73, 73, 73, 129, 129]);
  const same = fx.cases.filter((c) => c.gdd_agreement === 1 && c.cosine_log === 1);
  assert.ok(same.length >= 5); // identical subsets and the all-zero tail on both sides
});

test("signature by hand", () => {
  const rows = [[1, 2], [0, 2], [3, 0]];
  const s = signature(rows, [0, 1, 2], 2);
  assert.deepEqual(s.totals, [4, 4]);
  assert.deepEqual(s.gdd, [[[1, 1], [3, 1]], [[2, 2]]]);
  assert.equal(s.nodes, 3);
});

test("empty orbits: both empty = 1, one empty = 0; zero vectors", () => {
  const rows = [[0, 0], [1, 0]];
  const z = signature(rows, [0], 2), nz = signature(rows, [1], 2);
  assert.equal(gddAgreement(z, z), 1);
  assert.equal(cosineLog(z, z), 1);
  assert.equal(cosineLog(z, nz), 0);
  // orbit 0 has mass on one side only (A_0 = 0), orbit 1 is empty on both (A_1 = 1)
  assert.equal(gddAgreement(z, nz), 0.5);
  assert.equal(gddAgreement(signature(rows, [], 2), z), 1);
});

test("members without a GDV are counted and left out", () => {
  const rows = [[1, 0], [2, 0]], idx = new Map([["a", 0], ["b", 1]]);
  const r = selectionSignature(rows, idx, ["a", "x", "b", "y", "z"], 2);
  assert.equal(r.members, 5); assert.equal(r.withGdv, 2); assert.equal(r.without, 3);
  assert.deepEqual(r.sig.totals, [3, 0]);
  const none = selectionSignature(null, new Map(), ["a", "b"], 2);
  assert.equal(none.without, 2); assert.equal(none.withGdv, 0);
});
