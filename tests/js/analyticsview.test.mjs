import test from "node:test";
import assert from "node:assert/strict";
import { rainbow } from "../../heimdall/web/rainbow.js";
import { orbitColumn, orbitTotal, findClustering, sizeRank, clusterHex, members, similarity, kChoices, conflicts, dsatur, classNodes, rareFirst } from "../../heimdall/web/analyticsview.js";

const rows = [[1, 0, 3], [0, 0, 0], [2, 1, 3]];
const runs = [
  { key: "gdv_u/kmeans/2", feature: "gdv_u", alg: "kmeans", k: 2, silhouette: 0.5, default: false, sizes: [2, 1] },
  { key: "gdv_u/kmeans/4", feature: "gdv_u", alg: "kmeans", k: 4, silhouette: 0.6, default: true, sizes: [1, 1, 1, 0] },
  { key: "gdv_u/ap", feature: "gdv_u", alg: "ap", k: 2, silhouette: null, default: true, sizes: [2, 1] },
];

test("orbit column is log1p of the count", () => {
  assert.deepEqual(orbitColumn(rows, 0), [Math.log(2), 0, Math.log(3)]);
  assert.equal(orbitTotal(rows, 2), 6);
});

test("clustering lookup", () => {
  assert.equal(findClustering(runs, "gdv_u", "kmeans", "default").k, 4);
  assert.equal(findClustering(runs, "gdv_u", "kmeans", 2).key, "gdv_u/kmeans/2");
  assert.equal(findClustering(runs, "gdv_u", "kmeans", 8), null);
  assert.equal(findClustering(runs, "xy", "kmeans", "default"), null);
  assert.deepEqual(kChoices(runs, "gdv_u", "kmeans"), ["default", 2, 4]);
  assert.deepEqual(kChoices(runs, "gdv_u", "ap"), ["default"]);
  assert.deepEqual(kChoices(runs, "gdv_d", "ap"), []);
});

test("size rank and colours", () => {
  assert.deepEqual(sizeRank([1, 5, 3]), [2, 0, 1]);
  assert.equal(clusterHex([1, 5, 3], 1), rainbow(0, 3));
  assert.notEqual(clusterHex([1, 5, 3], 0), clusterHex([1, 5, 3], 1));
  assert.deepEqual(members(["a", "b", "c"], [0, 1, 0], 0), ["a", "c"]);
});

test("similarity reads the Odin III matrices", () => {
  const sig = { groups: [{ nodes: 4 }, { nodes: 9 }], gdd_agreement: [[1, 0.5], [0.5, 1]], cosine_log: [[1, 0.25], [0.25, 1]] };
  assert.deepEqual(similarity(sig, 0, 1), { gdd: 0.5, cosine: 0.25, na: 4, nb: 9 });
});

test("conflict graph: shared node or joining edge", () => {
  // path 0-1-2-3-4-5; instances {0,1}, {1,2}, {3,4}, {5}
  const edges = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]];
  const adj = conflicts([[0, 1], [1, 2], [3, 4], [5]], edges);
  assert.deepEqual([...adj[0]], [1]);            // shares node 1
  assert.deepEqual([...adj[1]].sort(), [0, 2]);  // shares 1 with #0, edge 2-3 joins #2
  assert.deepEqual([...adj[2]].sort(), [1, 3]);  // edge 4-5 joins {5}
  assert.deepEqual([...adj[3]], [2]);
});

test("dsatur: path needs 2 colours, triangle 3, valid colouring", () => {
  const path = [new Set([1]), new Set([0, 2]), new Set([1, 3]), new Set([2])];
  const r = dsatur(path);
  assert.equal(r.count, 2);
  path.forEach((nb, v) => nb.forEach((w) => assert.notEqual(r.colours[v], r.colours[w])));
  const tri = [new Set([1, 2]), new Set([0, 2]), new Set([0, 1])];
  assert.equal(dsatur(tri).count, 3);
  assert.deepEqual(dsatur([]), { colours: [], count: 0 });
  // odd cycle of five: chromatic number 3, DSatur finds it
  const c5 = [0, 1, 2, 3, 4].map((v) => new Set([(v + 1) % 5, (v + 4) % 5]));
  assert.equal(dsatur(c5).count, 3);
});

test("class nodes and rare-first table", () => {
  assert.deepEqual(classNodes([[0, 1], [3, 4], [1, 2]], [0, 0, 1], 2), [[0, 1, 3, 4], [1, 2]]);
  assert.deepEqual(rareFirst([[0, 2, 1, 40], [1, 3, 2, 0], [2, 3, 3, 7]]).map((r) => r[0]), [2, 0, 1]);
});

test("rareFirst puts every nonzero type before the greyed zero types", () => {
  const rows = Array.from({ length: 30 }, (_, g) => [g, 3, 2, g % 4 === 0 ? 0 : 100 - g]);
  const out = rareFirst(rows);
  const firstZero = out.findIndex((r) => r[3] === 0);
  assert.ok(out.slice(firstZero).every((r) => r[3] === 0));
  assert.ok(out.slice(0, firstZero).every((r) => r[3] > 0));
  assert.equal(out.length, 30);
});

test("instance files are fetched only when a type is picked", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("../../heimdall/web/app.js", import.meta.url), "utf8");
  const hits = src.split("\n").filter((l) => l.includes("analytics/instances."));
  assert.equal(hits.length, 1);
  const fn = src.slice(src.indexOf("async function anInstances"));
  assert.ok(fn.slice(0, fn.indexOf("\n}\n")).includes("analytics/instances."));
});
