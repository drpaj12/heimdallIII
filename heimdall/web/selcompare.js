// Signature compare of arbitrary selections, in the browser (spec section 8.1). A port of the metric code of
// Odin III (src/graph/sig.c: glet_sig_make, glet_gdd_agreement, glet_cosine_log); do not change the arithmetic
// without changing Odin III and regenerating tests/data/selcompare/fixture.json.

const SQRT2 = 1.4142135623730951;

// rows: GDV rows of a plane (rows[i][orbit] ints); take: row indices of the members; nOrb: orbits of the mode.
// Returns { nodes, totals[nOrb], gdd[nOrb] = sorted [[k, nodes touching the orbit exactly k times], ...] (k >= 1) }.
export function signature(rows, take, nOrb) {
  const totals = new Array(nOrb).fill(0);
  const gdd = [];
  for (let j = 0; j < nOrb; j++) {
    const h = new Map();
    for (const i of take) {
      const c = rows[i][j];
      totals[j] += c;
      if (c > 0) h.set(c, (h.get(c) ?? 0) + 1);
    }
    gdd.push([...h].sort((a, b) => a[0] - b[0]));
  }
  return { nodes: take.length, totals, gdd };
}

// sum over k of d(k)/k, in increasing k (orbit_total_area)
const area = (runs) => runs.reduce((t, [k, d]) => t + d / k, 0);

function orbitAgreement(ra, rb) {
  const ta = area(ra), tb = area(rb);
  if (ta === 0 && tb === 0) return 1.0;
  if (ta === 0 || tb === 0) return 0.0;
  let ia = 0, ib = 0, sum = 0;
  while (ia < ra.length || ib < rb.length) {
    const ka = ia < ra.length ? ra[ia][0] : Infinity, kb = ib < rb.length ? rb[ib][0] : Infinity;
    let na = 0, nb = 0;
    if (ka <= kb) { na = ra[ia][1] / ka / ta; ia++; }
    if (kb <= ka) { nb = rb[ib][1] / kb / tb; ib++; }
    sum += (na - nb) * (na - nb);
  }
  return 1.0 - Math.sqrt(sum) / SQRT2;
}

// mean over all orbits of the per-orbit agreement (1 for zero orbits)
export function gddAgreement(a, b) {
  const n = a.gdd.length;
  let total = 0;
  for (let j = 0; j < n; j++) total += orbitAgreement(a.gdd[j], b.gdd[j]);
  return n === 0 ? 1.0 : total / n;
}

// cosine of the vectors log(1 + orbit total)
export function cosineLog(a, b) {
  let dot = 0, na = 0, nb = 0;
  for (let j = 0; j < a.totals.length; j++) {
    const xa = Math.log1p(a.totals[j]), xb = Math.log1p(b.totals[j]);
    dot += xa * xb; na += xa * xa; nb += xb * xb;
  }
  if (na === 0 && nb === 0) return 1.0;
  return na === 0 || nb === 0 ? 0.0 : dot / (Math.sqrt(na) * Math.sqrt(nb));
}

// Signature of a selection of ids on one plane. gdv = analytics rows (aligned with plane ids `ids`), or null when the
// plane has no analytics. Returns the signature plus counts: members (ids of the selection on this plane),
// withGdv (in the rows), without (members - withGdv).
export function selectionSignature(gdv, idIndex, memberIds, nOrb) {
  const take = [];
  let without = 0;
  for (const id of memberIds) {
    const i = gdv ? idIndex.get(id) : undefined;
    if (i === undefined) without++; else take.push(i);
  }
  return { sig: signature(gdv ?? [], take, nOrb), members: memberIds.length, withGdv: take.length, without };
}

export function compareSignatures(a, b) {
  return { gdd: gddAgreement(a, b), cosine: cosineLog(a, b) };
}
