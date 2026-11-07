import test from "node:test";
import assert from "node:assert/strict";
import { rainbow } from "../../heimdall/web/rainbow.js";
import { orbitColumn, orbitTotal, findClustering, sizeRank, clusterHex, members, similarity, kChoices } from "../../heimdall/web/analyticsview.js";

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
