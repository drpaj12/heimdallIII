// Real coordinates of the ASIC planes (um). The anchor y is flipped (z = flip_y - y) so a chip reads with y up.
// Everything here is pure: segments are [x0, z0, x1, z1] in anchor coordinates (the viewer subtracts the
// centre of the bounds).
export const isUm = (coord) => coord?.kind === "um";
export const zOf = (coord, y) => (coord.flip_y ?? 0) - y;

const rectOf = (coord, b) => {
  const [x0, z0, x1, z1] = [b[0], zOf(coord, b[3]), b[2], zOf(coord, b[1])];
  return [[x0, z0, x1, z0], [x1, z0, x1, z1], [x1, z1, x0, z1], [x0, z1, x0, z0]];
};
// the die outline and the core outline
export const outlines = (coord) => [...rectOf(coord, coord.bounds), ...(coord.core ? rectOf(coord, coord.core) : [])];
// the row boundaries inside the core (one line between each pair of rows)
export function rowLines(coord) {
  const r = coord.rows, out = [];
  if (!coord.core || !r) return out;
  for (let i = 1; i < r.count; i++) {
    const z = zOf(coord, r.y0_um + i * r.pitch_um);
    out.push([r.x0_um, z, r.x1_um, z]);
  }
  return out;
}
// one net of routes.json: [[layer, x, y, x, y, ...], ...] -> [{ layer, seg }]
export function netSegments(coord, segs) {
  const out = [];
  for (const s of segs ?? []) {
    for (let k = 1; k + 3 < s.length; k += 2) out.push({ layer: s[0], seg: [s[k], zOf(coord, s[k + 1]), s[k + 2], zOf(coord, s[k + 3])] });
  }
  return out;
}
// bounds of the core in um: [x0, y0, x1, y1] (y up)
export const coreSize = (coord) => (coord.core ? [coord.core[2] - coord.core[0], coord.core[3] - coord.core[1]] : null);
