// Deep links of the Heimdall viewer: URL query parameters -> a plain state object (pure; app.js applies it).
// Unknown or malformed parameters are ignored, never an error. See "Deep links" in help.html.
//
//   sel=line:12 | line:12-15 | line:FILE:12-15 | obj:ID | bus:NAME | path:N (VPR report path number)
//   enclosing=1            take all enclosing constructs of a line selection
//   plane=NAME             focus a plane        solo=NAME   show only that plane
//   view=stack | NAME      3D stack, or the 2D view of a plane
//   graphs=stg,cfg,ddg     show graph planes    zoom=N      move the camera N times closer
//   colour=METRIC | @bus | @cluster | @role      size=, height=, fade=METRIC
//   ff=off|highlight|only  anchor=NAME          csrc=SOURCE compare=SOURCE
//   scoap=cc0|cc1|co[:min|max|mean]              cone=in|out|both[:DEPTH]
//   cell=comb|latched:I:J  a Comb or Latched matrix cell
//   bits=1                 show the bit squares on the selection
//   grp=ID,ID;ID           reverse groups: ';' separates groups, ',' the objects of one group
//   panels=left,hdl,right  collapse these panels (not saved)      rotate=0   stop auto-rotation
export const PARAMS = ["sel", "enclosing", "plane", "solo", "view", "graphs", "zoom", "colour", "size", "height", "fade",
  "ff", "anchor", "csrc", "compare", "scoap", "cone", "cell", "panels", "rotate", "bits", "grp"];

const num = (s) => (/^\d+$/.test(s) ? Number(s) : null);
const word = (s) => (/^[\w@.:\-]+$/.test(s) ? s : null);

function parseSel(v) {
  const i = v.indexOf(":");
  if (i < 0) return null;
  const kind = v.slice(0, i), rest = v.slice(i + 1);
  if (kind === "line") {
    const m = /^(?:(.+):)?(\d+)(?:-(\d+))?$/.exec(rest);
    return m ? { kind, file: m[1] ?? "", a: Number(m[2]), b: Number(m[3] ?? m[2]) } : null;
  }
  if (kind === "path") { const n = num(rest); return n === null ? null : { kind, n }; }
  if ((kind === "obj" || kind === "bus") && rest) return { kind, id: rest };
  return null;
}

export function parseQuery(search) {
  const q = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const g = (k) => q.get(k);
  const out = {};
  if (g("sel")) { const s = parseSel(g("sel")); if (s) out.sel = s; }
  if (g("enclosing") === "1") out.enclosing = true;
  for (const k of ["plane", "solo", "view", "colour", "size", "height", "fade", "anchor", "csrc", "compare"]) {
    const v = g(k) && word(g(k));
    if (v) out[k] = v;
  }
  if (g("ff") && ["off", "highlight", "only"].includes(g("ff"))) out.ff = g("ff");
  if (g("graphs")) out.graphs = g("graphs").split(",").filter((x) => ["stg", "cfg", "ddg"].includes(x));
  if (g("panels")) out.panels = g("panels").split(",").filter((x) => ["left", "hdl", "right"].includes(x));
  if (g("zoom") && Number(g("zoom")) > 0 && Number(g("zoom")) <= 20) out.zoom = Number(g("zoom"));
  if (g("rotate") === "0") out.rotate = false;
  if (g("bits") === "1") out.bits = true;
  if (g("grp")) {
    const groups = g("grp").split(";").map((x) => x.split(",").filter((id) => /^[\w@.:/\-[\]$]+$/.test(id))).filter((x) => x.length);
    if (groups.length) out.grp = groups.slice(0, 16);
  }
  const sc = g("scoap") && /^(cc0|cc1|co)(?::(min|max|mean))?$/.exec(g("scoap"));
  if (sc) out.scoap = { m: sc[1], op: sc[2] ?? "max" };
  const co = g("cone") && /^(in|out|both)(?::(\d+))?$/.exec(g("cone"));
  if (co) out.cone = { dir: co[1], depth: Number(co[2] ?? 6) };
  const ce = g("cell") && /^(comb|latched):(\d+):(\d+)$/.exec(g("cell"));
  if (ce) out.cell = { which: ce[1], i: Number(ce[2]), j: Number(ce[3]) };
  return out;
}
