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

// ---- graphlet instances: map colouring of the conflict graph ----
// instances: arrays of node indices (one per instance); edges: [u, v] pairs of the plane graph (either direction).
// Two instances conflict when they share a node or an edge joins a node of one to a node of the other.
export function conflicts(instances, edges) {
  const adj = new Map();
  for (const [u, v] of edges) {
    (adj.get(u) ?? adj.set(u, new Set()).get(u)).add(v);
    (adj.get(v) ?? adj.set(v, new Set()).get(v)).add(u);
  }
  const at = new Map();
  instances.forEach((inst, i) => { for (const n of inst) (at.get(n) ?? at.set(n, []).get(n)).push(i); });
  return instances.map((inst, i) => {
    const out = new Set();
    for (const n of inst) {
      for (const j of at.get(n) ?? []) if (j !== i) out.add(j);
      for (const m of adj.get(n) ?? []) for (const j of at.get(m) ?? []) if (j !== i) out.add(j);
    }
    return out;
  });
}

// DSatur colouring (Brelaz 1979): repeatedly colour the vertex with the most distinct neighbour colours (ties:
// larger degree, then lower index) with the smallest colour no neighbour has. Returns { colours, count }.
export function dsatur(adj) {
  const n = adj.length, colours = new Array(n).fill(-1), seen = adj.map(() => new Set());
  for (let done = 0; done < n; done++) {
    let best = -1;
    for (let v = 0; v < n; v++) {
      if (colours[v] >= 0) continue;
      if (best < 0 || seen[v].size > seen[best].size || (seen[v].size === seen[best].size && adj[v].size > adj[best].size)) best = v;
    }
    let c = 0;
    while (seen[best].has(c)) c++;
    colours[best] = c;
    for (const w of adj[best]) seen[w].add(c);
  }
  return { colours, count: n ? Math.max(...colours) + 1 : 0 };
}

// colour classes: class c -> sorted unique node indices of the instances coloured c
export function classNodes(instances, colours, count) {
  const out = Array.from({ length: count }, () => new Set());
  instances.forEach((inst, i) => { for (const n of inst) out[colours[i]].add(n); });
  return out.map((s) => [...s].sort((a, b) => a - b));
}

// graphlet type table rows [graphlet, nodes, edges, count]: rare types first, types with no instance last
export function rareFirst(rows) {
  return [...rows].sort((a, b) => ((a[3] === 0) - (b[3] === 0)) || a[3] - b[3] || a[0] - b[0]);
}
