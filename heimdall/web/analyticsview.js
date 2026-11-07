// Pure logic of the graph analytics panel (no DOM, no three.js): orbit columns, clustering lookup, cluster
// colours and the signature matrices written by the exporter (Odin III did the counting and the metrics).
import { rainbow } from "./rainbow.js";

// log scale of an orbit count column: rows[i][orbit] -> log(1 + count)
export const orbitColumn = (rows, orbit) => rows.map((r) => Math.log1p(r[orbit]));

// the orbit counts of one orbit summed over all nodes of the rows (what the picker shows beside the number)
export const orbitTotal = (rows, orbit) => rows.reduce((t, r) => t + r[orbit], 0);

// clustering entries of a plane: [{key, feature, alg, k, silhouette, default, sizes}]
export function findClustering(runs, feature, alg, k) {
  const of = runs.filter((r) => r.feature === feature && r.alg === alg);
  if (!of.length) return null;
  if (k === "default" || k === undefined) return of.find((r) => r.default) ?? of[0];
  return of.find((r) => r.k === +k) ?? null;
}

// rank of each cluster by size (0 = largest), ties by cluster number
export function sizeRank(sizes) {
  const order = sizes.map((_, c) => c).sort((a, b) => sizes[b] - sizes[a] || a - b);
  const rank = new Array(sizes.length);
  order.forEach((c, r) => { rank[c] = r; });
  return rank;
}

// colour (hex string) of cluster c: the rainbow palette over the size ranks
export function clusterHex(sizes, c) {
  const rank = sizeRank(sizes);
  return rainbow(rank[c], sizes.length);
}

// ids of the members of cluster c
export const members = (ids, labels, c) => ids.filter((_, i) => labels[i] === c);

// one signature set (plane, mode) from index.planes[p].signatures[m]: the two similarities of groups a, b
export function similarity(sig, a, b) {
  return { gdd: sig.gdd_agreement[a][b], cosine: sig.cosine_log[a][b], na: sig.groups[a].nodes, nb: sig.groups[b].nodes };
}

// the k choices of a (feature, alg): ["default", 2, 4, ...] for k-means, ["default"] for AP
export function kChoices(runs, feature, alg) {
  const of = runs.filter((r) => r.feature === feature && r.alg === alg);
  return alg === "ap" ? (of.length ? ["default"] : []) : of.length ? ["default", ...of.map((r) => r.k)] : [];
}
