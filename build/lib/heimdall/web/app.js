// Heimdall III viewer: one benchmark as a stack of planes (three.js, vendored, no network).
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { parse, evaluate, varsOf } from "./expr.js";
import { spearman, mutualInfo } from "./stats.js";
import * as pl from "./layout.js";
import * as um from "./umcoord.js";
import { characterize, edgeLength, cellEdges } from "./circuit.js";
import { barChart, drawMatrix, drawShape, cellAt } from "./circuitdraw.js";
import { GRAPHS, KEYS as GKEYS, isGraph, khopEdges, nodeEdges, edgeClass, propagate } from "./graphview.js";
import { parseQuery } from "./urlstate.js";
import * as av from "./analyticsview.js";
import * as sc from "./selcompare.js";
import { rainbow, groupColour, lineOwners, groupOwners, newGroups, addGroup, addToCurrent, clearGroups, lineMap, barGradient, bitStripes, pieSlices } from "./rainbow.js";
import { parseSpan, innermost, hdlCovering, reachDown, cone as coneOf, chainFor, tiers as tiersOf, mixOf, meanMix, mixRGB, mixText, busHue, bitLight } from "./select.js";

const BUNDLE = "./bundle/";
const GREY = new THREE.Color("#5b6572");
const BG = new THREE.Color("#14171c");
const SEQ = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"].map((c) => new THREE.Color(c));
const DIV = ["#d7301f", "#f7f7f7", "#2166ac"].map((c) => new THREE.Color(c));
const $ = (id) => document.getElementById(id);

const S = { man: null, planes: {}, order: [], links: [], up: new Map(), down: new Map(), pos: {},
  bounds: [0, 0, 1, 1], colour: "", size: "", sel: null, core: new Set(), gap: 6, byId: new Map(), ranges: {},
  height: "", fade: "", slot: {}, anchor: "", brush: null, vis: {}, view: "stack",
  lineSel: null, mode: { type: "none" }, focus: null, solo: null, cone: null, coneOn: false, path: null, paths: [], texts: {},
  srcFile: "", morph: { a: "", b: "", m: 0 }, group: { mode: "", expanded: new Set(), keys: {}, blobs: {} }, edges: null, edgeOn: false,
  cl: null, csrc: "", clCache: {}, anchorMeta: {}, cellEdges: null, tier: null, tierInfo: null, ff: "off", paint: null, groups: newGroups(), bits: false, busIndex: new Map(), busWidth: new Map(), busFilter: "", ffSlot: {}, clbFF: null,
  an: null,
  g: { data: {}, hops: 1, all: false, labels: true } };

// A static-site bundle lists gzip parts per file in manifest.parts (see `heimdall site`); a plain bundle (from
// `heimdall serve`) has none. The parts are joined in order and gunzipped with DecompressionStream.
async function getJson(path) {
  const parts = S.man && S.man.parts && S.man.parts[path];
  if (parts) {
    const bufs = [];
    for (const f of parts) {
      const r = await fetch(BUNDLE + f);
      if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`);
      bufs.push(await r.blob());
    }
    const stream = new Blob(bufs).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }
  const r = await fetch(BUNDLE + path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export async function loadBundle() {
  S.man = await getJson("manifest.json");
  S.order = S.man.planes;
  for (const p of S.order) S.planes[p] = await getJson(`planes/${p}.json`);
  const lj = await getJson("links.json");
  const all = S.order.flatMap((p) => S.planes[p].ids);
  S.links = lj.rows.map(([a, b]) => [all[a], all[b]]);
  for (const [a, b] of S.links) {
    (S.down.get(a) ?? S.down.set(a, []).get(a)).push(b);
    (S.up.get(b) ?? S.up.set(b, []).get(b)).push(a);
  }
  for (const p of S.order) S.planes[p].ids.forEach((id, i) => S.byId.set(id, { plane: p, i }));
  for (const p of S.order) if (isGraph(p)) { S.vis[p] = false; S.g.data[p] = await getJson(`graphs/${p}.json`); }
  (S.man.buses ?? []).forEach((b, k) => { S.busIndex.set(b.name, k); S.busWidth.set(b.name, b.width); });
  if (S.man.paths > 0) S.paths = (await getJson("paths.json")).paths;
  const files = new Set(Object.keys(S.man.inputs ?? {}));
  for (const p of S.order) for (const srcs of S.planes[p].src) for (const [f] of srcs) files.add(f);
  for (const f of [...files].sort()) {
    const r = await fetch(BUNDLE + "hdl/" + f.replace(/[<>]/g, "_"));
    S.texts[f] = r.ok ? (await r.text()).split("\n") : null;
  }
  if (S.man.circuit) {
    S.cl = await getJson("clusters.json");
    const lut = S.planes.lut;
    S.lutAt = new Map(lut.ids.map((id, i) => [id, i]));
    S.lutByName = new Map(lut.ids.map((id, i) => [id.slice(id.indexOf("/") + 1), i]));
  }
  if (S.man.activity) await loadActivity();
  if (S.man.analytics) S.an = { index: await getJson("analytics/index.json"), data: {}, cur: null, rank: {}, inst: {}, snaps: [], idx: {} };
  await loadAnchor(S.man.anchors.includes("placement") ? "placement" : S.man.anchors[0]);
}

async function loadAnchor(name) {
  const a = await getJson(`anchors/${name}.json`);
  S.pos = a.pos;
  S.bounds = a.bounds;
  S.anchor = name;
  const span = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  S.gap = Math.min(24, Math.max(6, span * 0.5));
  const gs = document.getElementById("gap");
  if (gs) gs.value = String(S.gap);
  S.unanchored = new Set(a.unanchored);
  S.anchorMeta = { step: a.step ?? 0, ff_attached: a.ff_attached !== false, labels: a.labels ?? [], band_kind: a.band_kind ?? "", source: a.source ?? "" };
}

// ---- scales ----
function metricRange(name) {
  if (S.ranges[name]) return S.ranges[name];
  let lo = Infinity, hi = -Infinity;
  for (const p of S.order) {
    const col = S.planes[p].metrics[name];
    if (!col) continue;
    for (const v of col) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  const clip = meta(name)?.clip;  // activity metrics: the clock nets toggle twice per cycle and would hide the rest
  if (clip && lo !== Infinity) {
    const all = S.order.flatMap((p) => (S.planes[p].metrics[name] ?? []).filter((v) => v !== null)).sort((a, b) => a - b);
    hi = Math.max(all[Math.min(all.length - 1, Math.floor(clip * all.length))], lo);
  }
  if (lo === Infinity) { lo = 0; hi = 1; }
  if (hi === lo) hi = lo + 1;
  return (S.ranges[name] = [lo, hi]);
}
const meta = (name) => S.man.metrics.find((m) => m.name === name);

function ramp(stops, t) {
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  return stops[i].clone().lerp(stops[i + 1], x - i);
}
function colourOf(name, v) {
  if (v === null || v === undefined) return GREY.clone();
  const [lo, hi] = metricRange(name);
  if (meta(name).scale === "div") {
    const m = Math.max(Math.abs(lo), Math.abs(hi));
    return ramp(DIV, (v + m) / (2 * m));
  }
  return ramp(SEQ, (v - lo) / (hi - lo));
}

// ---- scene ----
let renderer, scene, camera, controls, group, raycaster, meshes = {}, quads = {}, lines = null, markMesh = {};
const dummy = new THREE.Object3D();
const cx = () => (S.bounds[0] + S.bounds[2]) / 2;
const cz = () => (S.bounds[1] + S.bounds[3]) / 2;
// a graph plane that is switched off leaves no gap in the stack
const active = (p) => !(isGraph(p) && S.vis[p] === false);
const activeCount = () => S.order.filter(active).length;
const planeY = (k) => S.order.slice(k + 1).filter(active).length * S.gap;

// One shape per object kind inside a plane (shape channel): the kinds of a plane are sorted and take the
// shapes in this order.
const SHAPES = [
  () => new THREE.SphereGeometry(1, 10, 8), () => new THREE.BoxGeometry(1.5, 1.5, 1.5),
  () => new THREE.OctahedronGeometry(1.2), () => new THREE.ConeGeometry(1, 2, 8),
  () => new THREE.TetrahedronGeometry(1.3), () => new THREE.DodecahedronGeometry(1.1),
];
const CONE_COL = { seed: "#ffb454", in: "#5fe0ff", out: "#ff6fd8" };
const RADIUS = { stg: 0.14, cfg: 0.1, ddg: 0.07, hdl: 0.22, cell: 0.17, lut: 0.17, clb: 0.2, placed: 0.11, stdcell: 0.07, die: 0.06, route: 0.05 };
const TIER_COL = { A: "#ff9f1c", B: "#2ec4b6", C: "#9b8cff" };
const TIER_NAME = { A: "own: only this item", B: "shared: case select / mux, serves this item and others", C: "context: the rest of the case" };
const FF_COL = "#ff4fd8";
// a flip-flop: a lut/placed latch, a $dff cell, a declared reg driven by one (metric is_ff)
const isFF = (p, i) => S.planes[p].metrics.is_ff?.[i] === 1;
const ffCount = (p, i) => (p === "clb" ? S.planes.clb.metrics.ffs_inside?.[i] ?? 0 : 0);

function label(text, fs = 34, col = "#d8dee6") {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = col; g.font = `bold ${fs}px sans-serif`; g.fillText(text, 6, 44);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false }));
  s.scale.set(4, 1, 1);
  return s;
}

function buildScene() {
  const canvas = $("view");
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setClearColor(BG);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 4000);
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotateSpeed = 1.2;
  controls.enableZoom = false; // the wheel is handled by wheelZoom (towards the cursor)
  group = new THREE.Group();
  scene.add(group);
  raycaster = new THREE.Raycaster();
  const W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  S.order.forEach((p) => {
    const d = S.planes[p];
    const keyOf = (i) => (isFF(p, i) ? "\u2605ff" : d.kind[i]);
    const kinds = [...new Set(d.ids.map((_, i) => keyOf(i)))].sort();
    meshes[p] = kinds.map((kind, ki) => {
      const idx = d.ids.map((_, i) => i).filter((i) => keyOf(i) === kind);
      const geo = kind === "\u2605ff" ? new THREE.BoxGeometry(1.25, 1.25, 1.25) : SHAPES[ki % SHAPES.length]();
      const m = new THREE.InstancedMesh(geo, new THREE.MeshBasicMaterial(), idx.length);
      m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(idx.length * 3), 3);
      m.userData = { plane: p, kind, idx };
      idx.forEach((i, j) => { (S.slot[p] ??= [])[i] = [m, j]; });
      group.add(m);
      return m;
    });
    const q = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({
      color: 0x4a5a70, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
    q.rotation.x = -Math.PI / 2;
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(q.geometry), new THREE.LineBasicMaterial({ color: 0x6d7f99 }));
    edge.rotation.x = -Math.PI / 2;
    const lab = label(`${p}  (${d.ids.length})`);
    quads[p] = { q, edge, lab };
    group.add(q, edge, lab);
  });
  buildClbFF();
  layout();
  resetCamera();
}

function resizeQuads() {
  const W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  S.order.forEach((p) => {
    const { q, edge } = quads[p];
    q.geometry.dispose(); edge.geometry.dispose();
    q.geometry = new THREE.PlaneGeometry(W, H);
    edge.geometry = new THREE.EdgesGeometry(q.geometry);
  });
}

function layout() {
  drawFrames();
  S.order.forEach((p, k) => {
    const y = planeY(k);
    const { q, edge, lab } = quads[p];
    q.position.set(0, y - 0.01, 0); edge.position.copy(q.position);
    lab.position.set(-(S.bounds[2] - S.bounds[0]) / 2 + 2, y + 0.4, (S.bounds[3] - S.bounds[1]) / 2 + 0.5);
    refreshPlane(p);
  });
  drawLines();
  drawAnchorLabels();
  drawGraphs();
}

// level ticks and strip names of the Hutton / Kundarewich anchors, on the lut plane
let anchorLabels = [];
function drawAnchorLabels() {
  for (const l of anchorLabels) { group.remove(l); l.material.map.dispose(); l.material.dispose(); }
  anchorLabels = [];
  const k = S.order.indexOf("lut");
  if (k < 0) return;
  const a = S.anchorMeta, src = S.cl?.sources[a.source], W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  for (const t of a.labels) {
    const text = t.band === undefined ? t.text : a.band_kind === "seq" ? `seq ${t.band}` : (src?.names[t.band] ?? String(t.band)).slice(0, 16);
    const s = label(text);
    const sc = Math.max(0.5, W / 45);
    s.scale.set(4 * sc, sc, 1);
    s.position.set(t.x - cx() - (t.band === undefined ? 0 : 2 * sc), planeY(k) + 0.3, t.z - cz());
    group.add(s);
    anchorLabels.push(s);
  }
}

function stateOf(id) {
  if (S.cone?.nodes.has(id)) return 3;
  if (S.brush) return S.brush.has(id) ? 2 : S.core.has(id) ? 1 : -1;
  if (!S.sel) return S.cone ? -1 : 0;
  if (id === S.sel) return 2;
  return S.core.has(id) ? 1 : -1;
}

const norm = (name, v) => { const [lo, hi] = metricRange(name); return (v - lo) / (hi - lo); };

function heightOf(d, i) {
  if (!S.height) return 0;
  const v = d.metrics[S.height]?.[i];
  return v === null || v === undefined ? 0 : norm(S.height, v) * S.gap * 0.45;
}

function morphTarget(p, i) {
  const { a, b, m } = S.morph;
  if (p !== b || !m || !a || S.order.indexOf(a) >= S.order.indexOf(b)) return null;
  const id = S.planes[p].ids[i];
  const ups = (S.up.get(id) ?? []).filter((u) => S.byId.get(u)?.plane === a);
  if (!ups.length) return { y: m, x: null, z: null };
  const xs = ups.map((u) => S.pos[a][u]);
  return { y: m, x: xs.reduce((t, q) => t + q[0], 0) / xs.length, z: xs.reduce((t, q) => t + q[1], 0) / xs.length };
}

function hiddenByGroup(p, i) {
  const keys = S.group.keys[p];
  return !!keys && keys[i] !== null && keys[i] !== undefined && !S.group.expanded.has(keys[i]);
}

// Pies (several owners) and bit squares are drawn as flat vertex-coloured shapes just above the object's top, one
// mesh per plane. mark = { x, y, z, s, pie: [hex] | null, bit: [hex MSb..LSb] | null }
const SEG = 24;
function drawMarks(p, list) {
  if (markMesh[p]) { group.remove(markMesh[p]); markMesh[p].geometry.dispose(); markMesh[p].material.dispose(); markMesh[p] = null; }
  if (!list.length) return;
  const pos = [], col = [], c = new THREE.Color();
  const tri = (a, b, d, hex) => { c.set(hex); for (const v of [a, b, d]) { pos.push(v[0], v[1], v[2]); col.push(c.r, c.g, c.b); } };
  for (const m of list) {
    if (m.pie) {
      const y = m.y + m.s * 1.02, r = m.s * 1.05;
      for (const sl of pieSlices(m.pie)) {
        const n = Math.max(2, Math.round(SEG / m.pie.length));
        for (let k = 0; k < n; k++) {
          const a0 = (sl.a0 + (sl.a1 - sl.a0) * (k / n)) * 2 * Math.PI, a1 = (sl.a0 + (sl.a1 - sl.a0) * ((k + 1) / n)) * 2 * Math.PI;
          tri([m.x, y, m.z], [m.x + r * Math.cos(a0), y, m.z + r * Math.sin(a0)], [m.x + r * Math.cos(a1), y, m.z + r * Math.sin(a1)], sl.colour);
        }
      }
    }
    if (m.bit) {
      const y = m.y + m.s * 1.1, h = m.s * 0.5, n = m.bit.length, w = (2 * h) / n;
      m.bit.forEach((hex, k) => {
        const x0 = m.x - h + k * w, x1 = x0 + w;
        tri([x0, y, m.z - h], [x1, y, m.z - h], [x1, y, m.z + h], hex);
        tri([x0, y, m.z - h], [x1, y, m.z + h], [x0, y, m.z + h], hex);
      });
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide }));
  mesh.visible = meshes[p]?.[0]?.visible !== false;
  mesh.userData.mark = true;
  markMesh[p] = mesh;
  group.add(mesh);
}

function refreshPlane(p) {
  const d = S.planes[p], k = S.order.indexOf(p);
  const col = S.colour ? d.metrics[S.colour] : null;
  const sz = S.size ? d.metrics[S.size] : null;
  const fd = S.fade ? d.metrics[S.fade] : null;
  const r0 = unitR(p);
  const hl = S.bits ? highlighted() : null, marks = [];
  d.ids.forEach((id, i) => {
    const [m, j] = S.slot[p][i];
    const pos = posOf(p, i);
    let x = pos[0] - cx(), z = pos[1] - cz(), y = planeY(k) + heightOf(d, i);
    const mt = morphTarget(p, i);
    if (mt) {
      const ya = planeY(S.order.indexOf(S.morph.a));
      y = y + (ya - y) * mt.y;
      if (mt.x !== null) { x += (mt.x - cx() - x) * mt.y; z += (mt.z - cz() - z) * mt.y; }
    }
    dummy.position.set(x, y, z);
    let s = r0;
    if (sz) s *= sz[i] === null ? 0.5 : 0.6 + 1.8 * norm(S.size, sz[i]);
    const st = stateOf(id), tr = S.tier?.get(id), ff = isFF(p, i);
    const mx = S.tier && p !== "cell" && p !== "hdl" ? S.tierMix?.get(id) : null;
    if (mx) s *= 0.45 + Math.min(1.55, 1.55 * (mx.A * 1.3 + mx.B * 0.9 + mx.C * 0.5));
    else if (S.tier) s *= tr === "A" ? 2 : tr === "B" ? 1.5 : tr === "C" ? 1.1 : 0.45;
    else if (st === 2) s *= S.brush ? 1.5 : 2.4; else if (st === 3) s *= 1.3; else if (st === 1) s *= S.brush ? 1.15 : 1.5; else if (st === -1) s *= 0.55;
    if (S.ff !== "off" && p === "clb") s *= 0.45;
    const dim = S.ff === "only" && !ff && !(p === "clb" && ffCount(p, i) > 0);
    if (dim) s *= 0.4;
    if (ff && d.attach?.[i]) s *= 0.7;
    if (hiddenByGroup(p, i)) s = 1e-4;
    dummy.scale.setScalar(s);
    dummy.updateMatrix();
    m.setMatrixAt(j, dummy.matrix);
    let c = S.colour === "@bus" ? busColour(d, i) : S.colour === "@an" ? anColour(p, i) : S.colour === "@cluster" ? clusterColour(p, i) : S.colour === "@role" ? roleColour(p, i) : col ? colourOf(S.colour, col[i]) : new THREE.Color("#8fc1ff");
    if (ff && (S.ff !== "off" || !col && !S.colour.startsWith("@"))) c = new THREE.Color(FF_COL);
    if (fd) c.lerp(BG, 0.85 * (1 - (fd[i] === null ? 0 : norm(S.fade, fd[i]))));
    if (mx) {
      const [r, g, b] = mixRGB(mx, { A: hexRGB(TIER_COL.A), B: hexRGB(TIER_COL.B), C: hexRGB(TIER_COL.C) }, [BG.r, BG.g, BG.b]);
      c = new THREE.Color(r, g, b);
    } else if (S.tier) {
      if (tr) { c = new THREE.Color(TIER_COL[tr]); if (tr === "C") c.lerp(BG, 0.4); } else c.lerp(BG, 0.86);
    } else if (S.paint?.owners.has(id) && st < 3) {
      c = ff ? new THREE.Color("#ffffff") : new THREE.Color(S.paint.cols[S.paint.owners.get(id)[0]]);
    } else if (st === 3) c = new THREE.Color(CONE_COL[S.cone.nodes.get(id)] ?? "#5fe0ff");
    else if (st === 2 && !(S.colour === "@bus" && S.mode.type === "bus")) c = new THREE.Color("#ffb454");
    else if (st === -1) c.lerp(BG, 0.82);
    if (dim && !S.tier && st < 1) c.lerp(BG, 0.85);
    m.setColorAt(j, c);
    if (s > 1e-3) {
      const owners = S.paint && !S.tier ? S.paint.owners.get(id) : null;
      const pie = owners && owners.length > 1 && !ff ? owners.map((o) => S.paint.cols[o]) : null;
      const bit = hl?.has(id) && d.bus?.[i] ? bitStripes(d.bus[i], d.bit[i], d.busk?.[i], S.busWidth.get(d.bus[i]) ?? 1) : null;
      if (pie || bit) marks.push({ x, y, z, s, pie, bit });
    }
  });
  drawMarks(p, marks);
  for (const m of meshes[p]) {
    m.instanceMatrix.needsUpdate = true;
    m.instanceColor.needsUpdate = true;
    m.computeBoundingSphere();
  }
  refreshBlobs(p);
}
// ---- circuit colours: cluster of the current source, role (flip-flop, latched node, primary output) ----
function clusterIdx(p, i) {
  const src = S.cl?.sources[S.csrc];
  if (!src) return null;
  const d = S.planes[p], cache = (S.clCache[p] ??= {});
  if (i in cache) return cache[i];
  let v = null;
  if (p === "lut") v = src.of[i];
  else if (p === "placed") { const l = S.lutByName.get(d.name[i]); v = l === undefined ? null : src.of[l]; }
  else if (p === "clb") {
    const votes = new Map();
    for (const u of S.up.get(d.ids[i]) ?? []) { const l = S.lutAt.get(u); if (l !== undefined) votes.set(src.of[l], (votes.get(src.of[l]) ?? 0) + 1); }
    v = [...votes.entries()].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0] ?? null;
  } else if (p === "hdl") { const k = src.construct.indexOf(d.ids[i]); v = k < 0 ? null : k; }
  return (cache[i] = v);
}
function clusterColour(p, i) {
  const k = clusterIdx(p, i), src = S.cl?.sources[S.csrc];
  if (k === null || k === undefined || src.names[k] === "(none)") return GREY.clone();
  return new THREE.Color().setHSL(busHue(k) / 360, 0.75, 0.55);
}
const ROLE_COL = { latched: "#ffb454", po: "#4cd9a0", plain: "#8fc1ff" };
function roleColour(p, i) {
  const m = S.planes[p].metrics;
  if (isFF(p, i)) return new THREE.Color(FF_COL);
  if (m.is_latched?.[i] === 1) return new THREE.Color(ROLE_COL.latched);
  if (m.is_po?.[i] === 1) return new THREE.Color(ROLE_COL.po);
  return m.logic_level?.[i] === null || m.logic_level?.[i] === undefined ? GREY.clone() : new THREE.Color(ROLE_COL.plain);
}
function busColour(d, i) {
  const b = d.bus?.[i];
  if (!b) return GREY.clone();
  const k = S.busIndex.get(b) ?? 0;
  return new THREE.Color().setHSL(busHue(k) / 360, 0.78, bitLight(d.bit[i], S.busWidth.get(b) ?? 1));
}
const unitR = (p) => S.anchorMeta.step
  ? (RADIUS[p] ?? 0.15) / 0.17 * 0.28 * S.anchorMeta.step  // layouts with a fixed grid step: objects sized to it
  : (RADIUS[p] ?? 0.15) * Math.max(1, Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 12);

// ---- grouping: one blob per group (HDL module or VPR cluster); click a blob to expand it ----
function groupKeys(mode) {
  const keys = {};
  if (!mode) return keys;
  for (const p of ["lut", "placed"]) {
    if (!S.planes[p]) continue;
    keys[p] = S.planes[p].ids.map((id) => {
      const lut = p === "lut" ? id : (S.up.get(id) ?? []).find((u) => S.byId.get(u)?.plane === "lut");
      if (mode === "cluster") {
        const links = p === "lut" ? S.down.get(id) ?? [] : S.up.get(id) ?? [];
        const c = links.find((u) => S.byId.get(u)?.plane === "clb");
        return c ? S.planes.clb.name[S.byId.get(c).i] : null;
      }
      const m = (lut ? S.up.get(lut) ?? [] : []).find((u) => { const o = S.byId.get(u); return o?.plane === "hdl" && S.planes.hdl.type[o.i] === "module"; });
      return m ? S.planes.hdl.name[S.byId.get(m).i] : null;
    });
  }
  return keys;
}

function setGroupMode(mode) {
  $("grouping").value = mode;
  for (const p of Object.keys(S.group.blobs)) { group.remove(S.group.blobs[p].mesh); S.group.blobs[p].mesh.dispose(); }
  S.group = { mode, expanded: new Set(), keys: groupKeys(mode), blobs: {} };
  for (const p of Object.keys(S.group.keys)) {
    const gs = new Map();
    S.group.keys[p].forEach((key, i) => { if (key !== null) (gs.get(key) ?? gs.set(key, []).get(key)).push(i); });
    const list = [...gs.entries()].sort((x, y) => (x[0] < y[0] ? -1 : 1)).map(([key, members]) => ({ key, members }));
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 14, 10), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85 }), Math.max(1, list.length));
    mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1, list.length) * 3), 3);
    mesh.userData = { blob: p, list };
    mesh.count = list.length;
    group.add(mesh);
    S.group.blobs[p] = { mesh, list };
  }
  refreshAll();
}

function refreshBlobs(p) {
  const bl = S.group.blobs[p];
  if (!bl) return;
  const d = S.planes[p], k = S.order.indexOf(p);
  const col = S.colour ? d.metrics[S.colour] : null;
  bl.list.forEach((g, n) => {
    const open = S.group.expanded.has(g.key);
    let x = 0, z = 0, sum = 0, cnt = 0;
    for (const i of g.members) {
      const q = S.pos[p][d.ids[i]];
      x += q[0]; z += q[1];
      if (col && col[i] !== null) { sum += col[i]; cnt++; }
    }
    dummy.position.set(x / g.members.length - cx(), planeY(k), z / g.members.length - cz());
    dummy.scale.setScalar(open ? 1e-4 : Math.min(unitR(p) * (0.8 + 0.3 * Math.cbrt(g.members.length)), Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 9));
    dummy.updateMatrix();
    bl.mesh.setMatrixAt(n, dummy.matrix);
    bl.mesh.setColorAt(n, col && cnt ? colourOf(S.colour, sum / cnt) : new THREE.Color("#8fc1ff"));
  });
  bl.mesh.instanceMatrix.needsUpdate = true;
  bl.mesh.instanceColor.needsUpdate = true;
  bl.mesh.visible = S.vis[p] !== false && (S.view === "stack" || S.view === p);
  bl.mesh.computeBoundingSphere();
}

const refreshAll = () => { S.order.forEach(refreshPlane); refreshClbFF(); drawFFEdges(); drawLines(); drawEdges(); drawPathLines(); drawGraphs(); legend(); };

// position on the plane: a flip-flop with a driver (d.attach) sits beside it as a small piece of it
function posOf(plane, i) {
  const d = S.planes[plane], id = d.ids[i], att = d.attach?.[i], q = att && S.pos[plane][att];
  if (!q || !S.anchorMeta.ff_attached) return S.pos[plane][id];
  const k = (S.ffSlot[plane] ??= {})[att] ??= new Map();
  if (!k.has(id)) k.set(id, k.size);
  const r = unitR(plane) * 2.1, a = 0.9 + k.get(id) * 2.2;
  return [q[0] + r * Math.cos(a), q[1] + r * Math.sin(a)];
}
function worldPos(plane, id) {
  const k = S.order.indexOf(plane), i = S.byId.get(id).i, p = posOf(plane, i);
  return new THREE.Vector3(p[0] - cx(), planeY(k) + heightOf(S.planes[plane], i), p[1] - cz());
}

// short edges from each flip-flop to the object that drives it
let ffEdges = null;
function drawFFEdges() {
  if (ffEdges) { group.remove(ffEdges); ffEdges.geometry.dispose(); ffEdges = null; }
  const pts = [];
  for (const p of S.order) {
    const d = S.planes[p];
    if (!d.attach || S.vis[p] === false || (S.view !== "stack" && S.view !== p)) continue;
    d.attach.forEach((att, i) => { if (att && S.pos[p][att]) pts.push(worldPos(p, att), worldPos(p, d.ids[i])); });
  }
  if (!pts.length) return;
  ffEdges = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: new THREE.Color(FF_COL), transparent: true, opacity: 0.7 }));
  group.add(ffEdges);
}

// clusters: each flip-flop inside is a small cube in the cluster; the cubes of a selected cluster grow
function buildClbFF() {
  const d = S.planes.clb, col = d?.metrics.ffs_inside;
  if (!col) return;
  const owner = [];
  col.forEach((n, i) => { for (let k = 0; k < Math.min(n ?? 0, 16); k++) owner.push([i, k, Math.min(n, 16)]); });
  if (!owner.length) return;
  const m = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial(), owner.length);
  m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(owner.length * 3), 3);
  S.clbFF = { mesh: m, owner };
  group.add(m);
}
function refreshClbFF() {
  const f = S.clbFF;
  if (!f) return;
  const d = S.planes.clb, k = S.order.indexOf("clb"), r0 = unitR("clb");
  f.owner.forEach(([i, j, n], q) => {
    const id = d.ids[i], st = stateOf(id), tr = S.tier?.get(id);
    const hot = st >= 1 || S.ff !== "off" || tr;
    const pos = S.pos.clb[id], a = (j / n) * Math.PI * 2, rr = r0 * 0.62;
    dummy.position.set(pos[0] - cx() + rr * Math.cos(a), planeY(k) + heightOf(d, i) + r0 * 0.3, pos[1] - cz() + rr * Math.sin(a));
    dummy.scale.setScalar(hiddenByGroup("clb", i) || S.vis.clb === false ? 1e-4 : r0 * (hot ? 0.5 : 0.32));
    dummy.updateMatrix();
    f.mesh.setMatrixAt(q, dummy.matrix);
    const c = new THREE.Color(FF_COL);
    if ((S.sel || S.brush || S.tier) && st < 1 && !tr) c.lerp(BG, 0.8);
    f.mesh.setColorAt(q, c);
  });
  f.mesh.instanceMatrix.needsUpdate = true;
  f.mesh.instanceColor.needsUpdate = true;
  f.mesh.computeBoundingSphere();
}

// ---- ASIC planes: the die is drawn in um; core outline, rows and the routed wires of the selection ----
// Anchor y is flipped (y' = flip_y - y) so the chip reads with y up, as in a layout viewer.
const PHYS_ANCHORS = new Set(["placement", "global"]); // anchors in real um
const umPlanes = () => S.order.filter((p) => um.isUm(S.man.coord?.[p]));
let frames = [], routeLines = null;
const dispose = (o) => { group.remove(o); o.geometry.dispose(); o.material.dispose(); };
function drawFrames() {
  for (const f of frames) dispose(f);
  frames = [];
  for (const p of PHYS_ANCHORS.has(S.anchor) ? umPlanes().filter((q) => S.vis[q] !== false) : []) {
    const c = S.man.coord[p], y = planeY(S.order.indexOf(p)) + 0.02;
    const v = (list) => list.flatMap(([x0, z0, x1, z1]) => [new THREE.Vector3(x0 - cx(), y, z0 - cz()), new THREE.Vector3(x1 - cx(), y, z1 - cz())]);
    const mk = (pts, col, op) => { const l = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: op })); group.add(l); frames.push(l); };
    mk(v(um.outlines(c)), 0xffb454, 0.9);
    const rows = um.rowLines(c);
    if (rows.length) mk(v(rows), 0x6d7f99, 0.25);
  }
}
const LAYER_COL = [0x5fe0ff, 0xff6fd8, 0xffd166, 0x7bd88f, 0xb69cff, 0xff9f1c, 0x9be7ff, 0xff8a8a];
async function drawRoutes() {
  if (routeLines) { dispose(routeLines); routeLines = null; }
  if (!S.sel || !S.planes.route || !umPlanes().length || !PHYS_ANCHORS.has(S.anchor)) return;
  const a = S.byId.get(S.sel);
  const nets = a.plane === "route" ? [S.sel] : a.plane === "die" ? (S.down.get(S.sel) ?? []).filter((x) => S.byId.get(x)?.plane === "route").slice(0, 60) : [];
  if (!nets.length) return;
  S.routes ??= await getJson("routes.json");
  if (!S.sel || S.byId.get(S.sel) !== a) return;
  const coord = S.man.coord.die, y = planeY(S.order.indexOf("die")) + 0.06;
  const pos = [], col = [];
  for (const n of nets) for (const { layer, seg } of um.netSegments(coord, S.routes.nets[n])) {
    const c = new THREE.Color(LAYER_COL[layer % LAYER_COL.length]);
    pos.push(seg[0] - cx(), y, seg[1] - cz(), seg[2] - cx(), y, seg[3] - cz());
    col.push(c.r, c.g, c.b, c.r, c.g, c.b);
  }
  if (!pos.length) return;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  routeLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true }));
  group.add(routeLines);
}

function drawLines() {
  if (lines) { group.remove(lines); lines.geometry.dispose(); lines = null; }
  drawRoutes();
  if (!S.sel) return;
  const pts = [];
  const a = S.byId.get(S.sel);
  const from = worldPos(a.plane, S.sel);
  let n = 0;
  for (const id of [...(S.up.get(S.sel) ?? []), ...(S.down.get(S.sel) ?? [])]) {
    const b = S.byId.get(id);
    if (!b || n++ > 400) continue;
    pts.push(from, worldPos(b.plane, id));
  }
  if (!pts.length) return;
  lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: 0xffb454, transparent: true, opacity: 0.55 }));
  group.add(lines);
}

// ---- collapsible panels: left controls, HDL pane, right selection ----
let panels = pl.load(globalThis.localStorage, globalThis.matchMedia?.("(max-width: 800px)").matches);
function applyPanels() {
  $("app").style.gridTemplateColumns = pl.gridColumns(panels);
  const ids = { left: "left", hdl: "srcpane", right: "right" };
  for (const p of pl.PANELS) {
    $(ids[p]).classList.toggle("collapsed", panels[p]);
    const b = document.querySelector(`button[data-tgl="${p}"]`);
    b.innerHTML = (p === "right") === panels[p] ? "&laquo;" : "&raquo;";
  }
  $("split").classList.toggle("hidden", panels.hdl);
  if (renderer) resize();
}
function togglePanel(name) {
  panels = pl.toggled(panels, name);
  pl.save(globalThis.localStorage, panels);
  applyPanels();
}

function resize() {
  const r = $("stage").getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
}
function resetCamera() {
  S.focus = null; markFocus();
  const W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  const h = (activeCount() - 1) * S.gap;
  controls.target.set(0, h / 2, 0);
  const dist = Math.max(h * 1.1, W * 1.5) * 1.9;
  camera.position.set(dist * 0.5, h / 2 + dist * 0.42, dist * 0.75);
  controls.update();
}

// ---- selection ----
function closure(start, dir) {
  const seen = new Set(), planes = new Set();
  let frontier = [start];
  const step = dir === "down" ? S.down : S.up;
  const sign = dir === "down" ? 1 : -1;
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      const a = S.byId.get(id), ka = S.order.indexOf(a.plane);
      for (const t of step.get(id) ?? []) {
        const b = S.byId.get(t);
        if (!b || seen.has(t)) continue;
        const kb = S.order.indexOf(b.plane);
        if (sign * (kb - ka) <= 0) continue;
        // expand only into planes not yet reached from the start, so a cluster does not drag its siblings in
        if (id !== start && planes.has(b.plane)) continue;
        seen.add(t); next.push(t);
      }
    }
    for (const t of next) planes.add(S.byId.get(t).plane);
    frontier = next;
  }
  return seen;
}

// tiers of a clicked construct inside a case or if/else chain (null when it is in none)
function setTier(hdlIds) {
  S.tier = null; S.tierInfo = null;
  const hdl = S.planes.hdl;
  if (!hdl?.parent) return;
  for (const id of hdlIds) {
    const ch = chainFor(hdl, id);
    if (!ch) continue;
    const hdlOf = (x) => [...(S.up.get(x) ?? []), ...(S.down.get(x) ?? [])].filter((u) => S.byId.get(u)?.plane === "hdl" && !u.startsWith("hdl:sig."));
    const rest = S.order.filter((p) => p !== "hdl").map((p) => [p, S.planes[p].ids]);
    S.tier = tiersOf(ch, hdl.ids.filter((x) => !x.startsWith("hdl:sig.")), hdlOf, rest, (x) => S.up.get(x) ?? []);
    S.tierInfo = { chain: ch.chain, item: ch.item, items: ch.items };
    computeMix();
    return;
  }
}
// Graded ownership below the cell plane: a LUT takes the tier mix of the cells it was mapped from; a cluster and
// a placed atom the mean over their LUTs. A LUT with no cell link keeps its whole tier (share 1).
function computeMix() {
  S.tierMix = new Map();
  const lutMix = new Map();
  const tierCol = (t) => ({ A: 0, B: 0, C: 0, [t]: 1 });
  for (const id of S.planes.lut?.ids ?? []) {
    const cells = (S.up.get(id) ?? []).filter((u) => S.byId.get(u)?.plane === "cell");
    const m = cells.length ? mixOf(cells.map((c) => S.tier.get(c))) : S.tier.has(id) ? { ...tierCol(S.tier.get(id)), n: 0 } : null;
    if (m) lutMix.set(id, m);
  }
  S.tierMix = new Map(lutMix);
  for (const id of S.planes.clb?.ids ?? []) {
    const m = meanMix((S.up.get(id) ?? []).map((u) => lutMix.get(u)));
    if (m) S.tierMix.set(id, m);
  }
  const placed = S.planes.placed;
  placed?.ids.forEach((id, i) => {
    const l = S.lutByName?.get(placed.name[i]);
    const m = l === undefined ? null : lutMix.get(S.planes.lut.ids[l]);
    if (m) S.tierMix.set(id, m);
  });
}
const hexRGB = (h) => { const c = new THREE.Color(h); return [c.r, c.g, c.b]; };
function tierCounts() {
  const out = Object.fromEntries(S.order.map((p) => [p, { A: 0, B: 0, C: 0 }]));
  if (S.tier) for (const [id, t] of S.tier) out[S.byId.get(id).plane][t]++;
  return out;
}

export function select(id) {
  if (!S.byId.has(id)) return;
  S.sel = id;
  S.brush = null;
  S.lineSel = null; S.path = null;
  S.mode = { type: "obj" };
  for (const p of Object.keys(S.group.keys)) {
    const k = S.group.keys[p][S.byId.get(id).plane === p ? S.byId.get(id).i : -1];
    if (k) S.group.expanded.add(k);
  }
  S.core = new Set([...closure(id, "up"), ...closure(id, "down")]);
  const o = S.byId.get(id);
  // a CFG case node gets the same three tiers as its HDL item
  setTier(o.plane === "hdl" ? [id] : o.plane === "cfg" && S.planes.cfg.kind[o.i] === "case" ? (S.down.get(id) ?? []).filter((x) => S.byId.get(x)?.plane === "hdl") : []);
  afterSelection();
}
function clearSel() {
  S.sel = null; S.brush = null; S.core = new Set(); S.lineSel = null; S.path = null; S.cone = null; S.tier = null; S.tierInfo = null;
  S.paint = null; clearGroups(S.groups);
  S.cellEdges = null;
  S.mode = { type: "none" };
  $("pathinfo").textContent = "no path drawn";
  document.querySelectorAll("#pathlist div.on").forEach((e) => e.classList.remove("on"));
  refreshAll(); markLines();
  $("sel").textContent = "Click an HDL line or a node. Everything linked to it is highlighted."; $("sel").className = "sub";
}
async function afterSelection() {
  if (S.mode.type !== "line" && S.mode.type !== "groups") S.paint = null;
  if (S.mode.type !== "groups") clearGroups(S.groups);
  if (S.coneOn) await updateCone(); else refreshAll();
  markLines();
  showSelection();
  showCircuit();
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const fmt = (v) => (Number.isInteger(v) ? String(v) : Math.abs(v) < 0.01 ? v.toPrecision(3) : v.toFixed(3));

function infoRows(id) {
  const { plane, i } = S.byId.get(id), d = S.planes[plane];
  const rows = [["id", id], ["plane", plane], ["kind", d.kind[i]], ["type", d.type[i]], ["origin", d.origin[i]], ["name", d.name[i]]];
  for (const m of S.man.metrics) {
    const v = d.metrics[m.name]?.[i];
    if (v !== null && v !== undefined) rows.push([m.name, `${fmt(v)} ${m.unit}`]);
  }
  return rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
}

// objects highlighted (selected, brushed, drawn path or linked) per plane
function highlighted() {
  return new Set([...(S.sel ? [S.sel] : []), ...(S.brush ?? []), ...S.core]);
}
export function planeCounts() {
  const c = Object.fromEntries(S.order.map((p) => [p, 0]));
  for (const id of highlighted()) c[S.byId.get(id).plane]++;
  return c;
}

function paintLegend() {
  const P = S.paint, count = (o) => [...P.owners.values()].filter((l) => l.includes(o)).length;
  const sw = (c) => `<span style="color:${c}">&#9632;</span>`;
  if (P.kind === "lines") {
    const grad = P.cols.length > 1 ? `<div style="height:8px;border-radius:3px;background:linear-gradient(to right,${rainbow(0, 2)},${[1, 2, 3, 4, 5].map((k) => rainbow(k, 6)).join(",")})"></div>` : "";
    return `<h2>Line colours</h2>${grad}<div class="sub">${sw(P.cols[0])} line ${P.lo} to ${sw(P.cols[P.cols.length - 1])} line ${P.hi}: red first, violet last. An object reached from several lines is a pie; flip-flops are white.</div>`;
  }
  return '<h2>Groups</h2>' + P.cols.map((c, k) => `<div>${sw(c)} group ${k + 1}: ${S.groups.groups[k].ids.length} clicked, ${count(k)} objects</div>`).join("");
}
function tierTable() {
  const c = tierCounts();
  const rows = S.order.map((p) => `<tr><td>${p}</td>` + ["A", "B", "C"].map((t) => `<td style="color:${TIER_COL[t]}">${c[p][t]}</td>`).join("") + "</tr>").join("");
  return '<h2>Case tiers per plane</h2><table><tr><td></td>' +
    ["A", "B", "C"].map((t) => `<td style="color:${TIER_COL[t]}" title="${TIER_NAME[t]}"><b>${t}</b></td>`).join("") + `</tr>${rows}</table>` +
    ["A", "B", "C"].map((t) => `<div class="sub"><span style="color:${TIER_COL[t]}">&#9632;</span> ${t} ${TIER_NAME[t]}</div>`).join("") + mixTable();
}
// lut, clb and placed are graded: colour = the tier shares of the cells a LUT was mapped from
function mixTable() {
  if (!S.tierMix?.size) return "";
  const rows = ["lut", "clb", "placed"].filter((p) => S.planes[p]).map((p) => {
    const ms = S.planes[p].ids.map((id) => S.tierMix.get(id)).filter(Boolean);
    const some = (k) => ms.filter((m) => m[k] > 0).length;
    return `<tr><td>${p}</td>` + ["A", "B", "C"].map((k) => `<td style="color:${TIER_COL[k]}">${some(k)}</td>`).join("") + `<td>${ms.length}/${S.planes[p].ids.length}</td></tr>`;
  }).join("");
  return '<h2>Graded ownership</h2><div class="sub">lut, clb and placed are coloured by the mix of A, B and C among the cells a LUT was mapped from (clusters and atoms: mean over their LUTs); hover shows the shares. Objects with some share:</div>' +
    `<table><tr><td></td><td style="color:${TIER_COL.A}">A</td><td style="color:${TIER_COL.B}">B</td><td style="color:${TIER_COL.C}">C</td><td>graded</td></tr>${rows}</table>`;
}

function showSelection() {
  const m = S.mode;
  let html = "";
  if (m.type === "obj" && S.sel) html += `<table>${infoRows(S.sel)}</table>`;
  else if (m.type === "line") {
    html += `<div><b>HDL ${esc(m.file)} line${m.a === m.b ? " " + m.a : "s " + m.a + "-" + m.b}</b>: ` +
      (m.n ? `${m.n} ${$("enclosing").checked ? "covering" : "innermost covering"} construct${m.n === 1 ? "" : "s"}` : "no construct covers it") + "</div>";
  } else if (m.type === "path") html += `<div><b>Path</b>: ${esc(S.pathInfo ?? "")}</div>`;
  else if (m.type === "brush") html += `<div><b>Brush</b>: ${m.n} objects of ${m.plane}</div>`;
  if (m.type === "gedge") html += `<div><b>${esc(m.text)}</b>: ${m.n} HDL construct${m.n === 1 ? "" : "s"} with its span, highlighted with the ends</div>`;
  if (m.type === "obj" && S.sel && isGraph(S.byId.get(S.sel).plane)) html += graphPanel(S.sel);
  if (m.type === "cell") html += `<div><b>${esc(m.text)}</b>: ${m.n} edges, highlighted in yellow; their endpoints and the HDL lines behind them are selected</div>`;
  if (m.type === "bus") html += `<div><b>Bus ${esc(m.name)}</b>: ${m.n} objects across the planes${m.decl ? "; declared at line " + m.decl[1].split(".")[0] : ""}</div>`;
  if (m.type === "groups") html += `<div><b>${m.n} group${m.n === 1 ? "" : "s"}</b>: shift-click adds a group, shift+alt-click adds to the last one, Esc clears</div>`;
  if (S.paint) html += paintLegend();
  if (S.tier) html += tierTable();
  const c = planeCounts();
  html += '<h2>Linked objects per plane</h2><div class="col">' + S.order.map((p) =>
    `<div class="prow${S.focus === p ? " on" : ""}"><b>${p}</b><span>${c[p]}</span><button data-focus="${p}">focus</button></div>`).join("") + "</div>";
  $("sel").className = "";
  $("sel").innerHTML = html;
  $("sel").querySelectorAll("button[data-focus]").forEach((b) => b.addEventListener("click", () => focusPlane(b.dataset.focus)));
  $("sel").querySelectorAll("tr.gedge").forEach((r) => r.addEventListener("click", () => selectEdge(r.dataset.k, Number(r.dataset.i))));
  $("sel").querySelectorAll("button[data-bus]").forEach((b) => b.addEventListener("click", () => selectBus(b.dataset.bus)));
}

// ---- graph planes ----
const GCOL = { data: 0x5fa8ff, control: 0xff6fd8, transition: 0x2ec4b6, seq: 0x8b96a3 };
const GCSS = { data: "#5fa8ff", control: "#ff6fd8", transition: "#2ec4b6", seq: "#8b96a3" };
let gLines = [], gLabels = [];
function clearGraphDraw() {
  for (const l of gLines) { group.remove(l); l.geometry.dispose(); l.material.dispose(); }
  for (const l of gLabels) { group.remove(l); l.material.map.dispose(); l.material.dispose(); }
  gLines = []; gLabels = [];
}
const hotOf = (kind) => new Set([...highlighted()].filter((id) => S.byId.get(id)?.plane === kind));
// the edge segments of one graph plane: [from, to, class, seq, hot]
function graphSegments(kind) {
  const gd = S.g.data[kind], edges = gd.edges, hot = hotOf(kind);
  const seeds = new Set([S.sel, ...(S.brush ?? []), ...S.core].filter((id) => S.byId.get(id)?.plane === kind));
  const pick = kind === "ddg" && !S.g.all ? khopEdges(edges, seeds, S.g.hops) : null;
  const out = [];
  edges.forEach((e, i) => {
    if (pick && !pick.has(i)) return;
    if (!S.byId.has(e[0]) || !S.byId.has(e[1])) return;
    out.push([e[0], e[1], edgeClass(e[2]), e[4] === 1, hot.has(e[0]) || hot.has(e[1])]);
  });
  return out;
}
function pushSeg(seg, kind, solid, dashed) {
  const [a, b, cls, seq, hot] = seg;
  const pa = worldPos(kind, a), pb = worldPos(kind, b);
  const c = new THREE.Color(hot ? 0xffb454 : GCOL[cls]), dim = c.clone().lerp(BG, 0.55);
  const into = seq ? dashed : solid;
  const r = unitR(kind) * 1.4;
  const add = (p, q, c0, c1) => { into.pts.push(p, q); into.cols.push(c0.r, c0.g, c0.b, c1.r, c1.g, c1.b); };
  if (a === b) {  // self loop: a small octagon beside the node
    for (let k = 0; k < 8; k++) {
      const t0 = (k / 8) * 2 * Math.PI, t1 = ((k + 1) / 8) * 2 * Math.PI;
      const q0 = pa.clone().add(new THREE.Vector3(r * (1 + Math.cos(t0)), 0, r * Math.sin(t0)));
      const q1 = pa.clone().add(new THREE.Vector3(r * (1 + Math.cos(t1)), 0, r * Math.sin(t1)));
      add(q0, q1, c, c);
    }
    return;
  }
  add(pa, pb, dim, c);
  if (solid.arrows) {  // arrow head at the target
    const d = pb.clone().sub(pa).setY(0);
    if (d.length() < 1e-6) return;
    d.normalize();
    const base = pb.clone().addScaledVector(d, -r);
    const side = new THREE.Vector3(-d.z, 0, d.x).multiplyScalar(r * 0.5);
    solid.pts.push(pb, base.clone().add(side), pb, base.clone().sub(side));
    solid.cols.push(c.r, c.g, c.b, c.r, c.g, c.b, c.r, c.g, c.b, c.r, c.g, c.b);
  }
}
function lineObj(set, dashed, kind) {
  const g = new THREE.BufferGeometry().setFromPoints(set.pts);
  g.setAttribute("color", new THREE.Float32BufferAttribute(set.cols, 3));
  const unit = unitR(kind);
  const m = dashed ? new THREE.LineDashedMaterial({ vertexColors: true, dashSize: unit * 0.9, gapSize: unit * 0.6, transparent: true, opacity: 0.85 })
    : new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 });
  const l = new THREE.LineSegments(g, m);
  if (dashed) l.computeLineDistances();
  return l;
}
function drawGraphs() {
  if (!group) return;
  clearGraphDraw();
  let msg = "";
  for (const kind of GRAPHS) {
    const gd = S.g.data[kind];
    if (!gd || S.vis[kind] === false || !(S.view === "stack" || S.view === kind)) continue;
    const segs = graphSegments(kind);
    const solid = { pts: [], cols: [], arrows: segs.length <= 600 }, dashed = { pts: [], cols: [] };
    for (const s of segs) pushSeg(s, kind, solid, dashed);
    if (solid.pts.length) { const l = lineObj(solid, false, kind); group.add(l); gLines.push(l); }
    if (dashed.pts.length) { const l = lineObj(dashed, true, kind); group.add(l); gLines.push(l); }
    const d = S.planes[kind];
    if (S.g.labels && d.ids.length <= 80) {
      d.ids.forEach((id, i) => {
        const s = label(String(d.name[i]).replace(/^\\/, "").slice(0, 15), 26);
        const sc = Math.max(0.5, Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 100);
        s.scale.set(4 * sc, sc, 1);
        const p = worldPos(kind, id);
        s.position.set(p.x + 2 * sc, p.y + 0.5 * sc, p.z);
        group.add(s); gLabels.push(s);
      });
    }
    if (S.g.labels && kind !== "ddg") edgeLabels(kind, gd);
    if (kind === "ddg" && !S.g.all && !segs.length) msg = "ddg: select a signal (or an HDL line) to see its edges; tick all edges to draw the whole graph";
  }
  const el = document.getElementById("gmsg");
  if (el) el.textContent = msg;
}
// edge labels (transition conditions, case patterns) at the middle of the edge, when there are not too many
function edgeLabels(kind, gd) {
  const rows = gd.edges.filter((e) => e[3] && S.byId.has(e[0]) && S.byId.has(e[1]));
  if (rows.length > 80) return;
  const sc = Math.max(0.5, Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 120);
  for (const e of rows) {
    const a = worldPos(kind, e[0]), b = worldPos(kind, e[1]);
    const mid = e[0] === e[1] ? a.clone().add(new THREE.Vector3(unitR(kind) * 3, 0, 0)) : a.clone().lerp(b, 0.5);
    const s = label(String(e[3]).slice(0, 16), 24, e[2] === "transition" ? "#7fe3d6" : "#ffb454");
    s.scale.set(4 * sc, sc, 1);
    s.position.set(mid.x + 2 * sc, mid.y + 0.3 * sc, mid.z);
    group.add(s); gLabels.push(s);
  }
}
function graphPanel(id) {
  const { plane, i } = S.byId.get(id), gd = S.g.data[plane], d = S.planes[plane];
  const det = gd.detail[id] ?? {};
  let h = `<h2>${plane.toUpperCase()} node</h2><div class="sub">${esc(d.name[i])}</div>`;
  if (det.code !== undefined) h += `<div>state code <b>${esc(det.code)}</b> (MSB first), register ${esc(det.wire)}; reset state: ${d.metrics.is_reset?.[i] === 1 ? "yes" : "no"}</div>` +
    `<div class="sub">Linked: the state register (declaration, flip-flops) and the next-state selection logic. The fsm pass does not attribute a state to one case item.</div>`;
  if (det.compares?.length) h += `<div>patterns: ${esc(det.compares.join(", "))}</div>`;
  if (det.signal) h += `<div>selector: ${esc(det.signal)}</div>`;
  if (det.actions?.length) h += "<div class=\"sub\">actions: " + det.actions.map((a) => esc(`${a[0]} <= ${a[1]}`.slice(0, 60))).join("; ") + "</div>";
  const es = nodeEdges(gd.edges, id), shown = es.slice(0, 40);
  h += `<table>` + shown.map((e) => {
    const r = gd.edges[e.idx];
    return `<tr class="gedge" data-k="${plane}" data-i="${e.idx}" style="cursor:pointer"><td style="color:${GCSS[edgeClass(r[2])]}">${e.dir === "in" ? "&larr;" : "&rarr;"}</td><td>${esc(r[2])}${r[4] ? " (seq)" : ""}</td><td>${esc(e.other.split(":").slice(1).join(":"))}${r[3] ? " [" + esc(r[3]) + "]" : ""}</td></tr>`;
  }).join("") + "</table>" + (es.length > 40 ? `<div class="sub">${es.length - 40} more edges not listed</div>` : "");
  const bus = d.name[i];
  if (plane === "stg" && det.wire && S.busIndex.has(det.wire.split(".").pop())) h += `<button data-bus="${esc(det.wire.split(".").pop())}">select the state register bus</button>`;
  return h;
}

// ---- source pane: the whole HDL file, line numbers; click or drag lines to select what they produced ----
const RANK = { tC: 0.5, hitw: 1, hit: 2, tB: 2.5, tA: 2.6, sel: 3 };
let rows = [], marks = new Map(), dragging = false;

function showFile(file) {
  S.srcFile = file;
  const text = S.texts[file];
  const box = $("srclines");
  box.innerHTML = "";
  rows = [];
  if (!text) { box.innerHTML = `<div class="sub" style="padding:8px">${esc(file)} is not in the bundle (export with --src)</div>`; }
  else {
    const frag = document.createDocumentFragment();
    const n = text.length && text[text.length - 1] === "" ? text.length - 1 : text.length;
    for (let i = 0; i < n; i++) {
      const row = document.createElement("div");
      row.className = "ln"; row.dataset.n = String(i + 1);
      row.innerHTML = `<span class="no">${i + 1}</span><span class="tx">${esc(text[i])}</span>`;
      rows[i + 1] = row;
      frag.appendChild(row);
    }
    box.appendChild(frag);
  }
  document.querySelectorAll("#srctabs button").forEach((b) => b.classList.toggle("on", b.dataset.f === file));
  paintLines();
}

function paintLines() {
  const mk = marks.get(S.srcFile), ls = S.lineSel && S.lineSel.file === S.srcFile ? S.lineSel : null;
  const lo = ls ? Math.min(ls.a, ls.b) : 0, hi = ls ? Math.max(ls.a, ls.b) : -1;
  const pm = S.paint?.lines.get(S.srcFile);
  for (let n = 1; n < rows.length; n++) {
    const cls = ls && n >= lo && n <= hi ? "sel" : mk?.get(n);
    rows[n].className = "ln" + (cls ? " " + cls : "");
    const cols = pm?.get(n)?.map((o) => S.paint.cols[o]);
    rows[n].style.background = cols ? (cols.length === 1 ? cols[0] + "66" : "#ffffff14") : "";
    rows[n].firstChild.style.backgroundImage = cols ? barGradient(cols) : "";
  }
}

// lines behind the current selection: innermost HDL constructs among the linked ones, plus the own span of
// the primary non-HDL objects; the user's own lines stay "sel"
function markLines() {
  marks = new Map();
  const put = (file, line, cls) => {
    const m = marks.get(file) ?? marks.set(file, new Map()).get(file);
    if (!m.has(line) || RANK[cls] > RANK[m.get(line)]) m.set(line, cls);
  };
  const prim = (id) => id === S.sel || S.brush?.has(id);
  const hdlItems = [], own = [];
  for (const id of highlighted()) {
    const o = S.byId.get(id), src = S.planes[o.plane].src[o.i];
    if (o.plane === "hdl") {
      const sp = src[0] && parseSpan(src[0][1]);
      if (sp) hdlItems.push({ file: src[0][0], span: sp });
    } else if (prim(id) && src.length) {
      const last = src[src.length - 1], sp = parseSpan(last[1]);
      if (sp) own.push({ file: last[0], span: sp });
    }
  }
  if (S.cone) for (const id of S.cone.nodes.keys()) {
    const o = S.byId.get(id), src = o && S.planes[o.plane].src[o.i];
    const last = src?.[src.length - 1], sp = last && parseSpan(last[1]);
    if (sp) for (let l = sp.l0; l <= sp.l1; l++) put(last[0], l, "hitw");
  }
  const strong = S.mode.type === "line" ? "hitw" : "hit";
  for (const file of new Set(hdlItems.map((x) => x.file))) {
    for (const it of innermost(hdlItems.filter((x) => x.file === file))) for (let l = it.span.l0; l <= it.span.l1; l++) put(file, l, strong);
  }
  for (const it of own) for (let l = it.span.l0; l <= it.span.l1; l++) put(it.file, l, "hit");
  if (S.tierInfo) tierLines(put);
  // scroll to the first marked line, unless the user is working in the pane
  if (S.mode.type !== "line" && marks.size) {
    let best = null, bestN = -1;
    for (const [f, m] of marks) if (m.size > bestN) { best = f; bestN = m.size; }
    if (best !== S.srcFile) showFile(best);
    const first = Math.min(...marks.get(best).keys());
    const box = $("srclines");
    if (rows[first]) box.scrollTop = Math.max(0, rows[first].offsetTop - box.clientHeight / 3);
  }
  paintLines();
  const nl = [...marks.values()].reduce((t, m) => t + m.size, 0);
  $("srcinfo").firstChild.textContent = S.mode.type === "none" || !marks.size && S.mode.type !== "line"
    ? (S.mode.type === "none" ? "Click a line, drag or shift-click for a range. " : "No HDL lines behind this selection. ")
    : `${nl} HDL line${nl === 1 ? "" : "s"} highlighted. `;
}

// the clicked item strong, the case header, and the rest of the case in a light tint
function tierLines(put) {
  const hdl = S.planes.hdl, t = S.tierInfo;
  const span = (id) => { const i = S.byId.get(id).i, s0 = hdl.src[i][0]; return s0 && { file: s0[0], sp: parseSpan(s0[1]) }; };
  const paint = (id, cls) => { const x = span(id); if (x?.sp) for (let l = x.sp.l0; l <= x.sp.l1; l++) put(x.file, l, cls); };
  for (const it of t.items) paint(it, it === t.item ? "tA" : "tC");
  const c = span(t.chain);
  if (c?.sp) put(c.file, c.sp.l0, "tB");
}

function selectLines(file, a, b) {
  if (!S.planes.hdl) return;
  const hdl = S.planes.hdl;
  const idx = hdlCovering(hdl, file, a, b, $("enclosing").checked);
  const ids = [...idx].map((i) => hdl.ids[i]);
  S.sel = null; S.path = null;
  S.lineSel = { file, a, b };
  S.mode = { type: "line", file, a: Math.min(a, b), b: Math.max(a, b), n: ids.length };
  setTier(ids);
  hdlSelection(ids);
  // one line inside a case keeps its tier view; two or more lines (or any other line) take the rainbow
  S.paint = S.tier && a === b ? null : linePaint(file, a, b);
  if (S.paint) { S.tier = null; S.tierInfo = null; S.tierMix = null; }
  afterSelection();
}
// the brush is a set of HDL constructs; everything linked below (cell, lut, clb, placed) and above (graph planes)
function reachSet(ids) {
  const r = reachDown(ids, S.order, (id) => S.byId.get(id)?.plane, S.down);
  const up = ids.flatMap((id) => (S.up.get(id) ?? []).filter((u) => isGraph(S.byId.get(u)?.plane)));
  return new Set([...S.order.filter((p) => p !== "hdl" && !isGraph(p)).flatMap((p) => [...r[p]]), ...up]);
}
function hdlSelection(ids) {
  if (!ids.length) { S.brush = null; S.core = new Set(); return; }
  S.brush = new Set(ids);
  S.core = reachSet(ids);
}

// ---- rainbow: line k of n selected lines takes the k-th colour, red to violet; its reach carries it ----
const MAX_RAINBOW_LINES = 300;
function linePaint(file, a, b) {
  const lo = Math.min(a, b), hi = Math.max(a, b), n = hi - lo + 1, hdl = S.planes.hdl;
  if (!hdl || n > MAX_RAINBOW_LINES) return null;
  const starts = [];
  for (let l = lo; l <= hi; l++) starts.push([...hdlCovering(hdl, file, l, l, $("enclosing").checked)].map((i) => hdl.ids[i]));
  const cols = starts.map((_, k) => rainbow(k, n));
  const owners = lineOwners(starts, (ids) => [...ids, ...reachSet(ids)]);
  const lines = new Map([[file, new Map(cols.map((_, k) => [lo + k, [k]]))]]);
  return { kind: "lines", owners, cols, lines, lo, hi };
}

// ---- reverse groups: shift-click objects; a group's reach and HDL lines take its colour ----
function groupClick(id, add) {
  if (!S.byId.has(id)) return;
  if (add) addToCurrent(S.groups, id); else addGroup(S.groups, id);
  applyGroups();
}
function applyGroups() {
  const gs = S.groups.groups, memo = new Map();
  const reach = (id) => memo.get(id) ?? memo.set(id, new Set([id, ...closure(id, "up"), ...closure(id, "down")])).get(id);
  const owners = groupOwners(gs, reach), cols = gs.map((g) => groupColour(g.colour)), items = [];
  const prim = new Set(gs.flatMap((g) => g.ids));
  gs.forEach((g, k) => {
    const all = new Set(g.ids.flatMap((id) => [...reach(id)])), per = new Map();
    for (const id of all) {
      const o = S.byId.get(id), src = S.planes[o.plane].src[o.i];
      if (o.plane === "hdl") { const sp = src[0] && parseSpan(src[0][1]); if (sp) (per.get(src[0][0]) ?? per.set(src[0][0], []).get(src[0][0])).push({ span: sp }); }
      else if (g.ids.includes(id) && src.length) { const last = src[src.length - 1], sp = parseSpan(last[1]); if (sp) (per.get(last[0]) ?? per.set(last[0], []).get(last[0])).push({ span: sp }); }
    }
    for (const [file, list] of per) for (const it of innermost(list)) items.push({ file, l0: it.span.l0, l1: it.span.l1, owner: k });
  });
  S.sel = null; S.lineSel = null; S.path = null; S.tier = null; S.tierInfo = null; S.cone = null;
  S.brush = prim;
  S.core = new Set([...owners.keys()].filter((id) => !prim.has(id)));
  S.mode = { type: "groups", n: gs.length };
  S.paint = gs.length ? { kind: "groups", owners, cols, lines: lineMap(items) } : null;
  afterSelection();
}
// click an edge row of the panel: its two ends and the HDL it comes from
export function selectEdge(kind, idx) {
  const e = S.g.data[kind]?.edges[idx];
  if (!e) return;
  const hdl = S.planes.hdl, ids = [];
  const spans = new Set(e[5].map((x) => x[1]));
  hdl.src.forEach((s, i) => { if (s[0] && spans.has(s[0][1])) ids.push(hdl.ids[i]); });
  S.sel = null; S.path = null; S.lineSel = null; S.tier = null; S.tierInfo = null;
  S.mode = { type: "gedge", text: `${kind} edge ${e[0].split(":").slice(1).join(":")} to ${e[1].split(":").slice(1).join(":")}${e[3] ? " [" + e[3] + "]" : ""}`, n: ids.length };
  hdlSelection(ids);
  S.brush = new Set([...(S.brush ?? []), e[0], e[1]]);
  afterSelection();
}

function buildSource() {
  const files = Object.keys(S.texts);
  $("srctabs").innerHTML = files.map((f) => `<button data-f="${esc(f)}">${esc(f)}</button>`).join("");
  $("srctabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => showFile(b.dataset.f)));
  const first = (() => {
    const d = S.planes.hdl;
    return (d && d.src.find((s) => s.length)?.[0][0]) || files[0] || "";
  })();
  showFile(first);
  const box = $("srclines");
  const lineOf = (e) => { const r = e.target.closest?.(".ln"); return r ? Number(r.dataset.n) : null; };
  box.addEventListener("mousedown", (e) => {
    const n = lineOf(e);
    if (n === null || e.button !== 0) return;
    const keep = e.shiftKey && S.lineSel && S.lineSel.file === S.srcFile ? S.lineSel.a : n;
    S.lineSel = { file: S.srcFile, a: keep, b: n };
    dragging = true;
    paintLines();
    e.preventDefault();
  });
  box.addEventListener("mouseover", (e) => {
    const n = lineOf(e);
    if (!dragging || n === null || !S.lineSel) return;
    S.lineSel.b = n;
    paintLines();
  });
  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    if (S.lineSel) selectLines(S.lineSel.file, S.lineSel.a, S.lineSel.b);
  });
  $("enclosing").addEventListener("change", () => { if (S.lineSel) selectLines(S.lineSel.file, S.lineSel.a, S.lineSel.b); });
  // resizable split between the source pane and the 3D view
  const split = $("split");
  split.addEventListener("pointerdown", (e) => {
    split.setPointerCapture(e.pointerId); split.classList.add("drag");
    const main = $("main").getBoundingClientRect();
    const move = (ev) => { $("srcpane").style.flexBasis = Math.min(main.width - 200, Math.max(120, ev.clientX - main.left)) + "px"; };
    const up = () => { split.classList.remove("drag"); split.removeEventListener("pointermove", move); split.removeEventListener("pointerup", up); };
    split.addEventListener("pointermove", move); split.addEventListener("pointerup", up);
  });
}

// ---- picking ----
function pick(ev) {
  const r = $("view").getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  let best = null;
  const take = (hit, what) => { if (hit && (!best || hit.distance < best.distance)) best = { distance: hit.distance, ...what }; };
  for (const p of S.order) {
    for (const m of meshes[p]) {
      if (!m.visible) continue;
      const hit = raycaster.intersectObject(m)[0];
      take(hit, hit && { id: S.planes[p].ids[m.userData.idx[hit.instanceId]] });
    }
    const bl = S.group.blobs[p];
    if (bl?.mesh.visible) {
      const hit = raycaster.intersectObject(bl.mesh)[0];
      take(hit, hit && { blob: bl.list[hit.instanceId], plane: p });
    }
  }
  return best;
}

// ---- edges: k-hop neighbourhood of the selection, or aggregated edges between groups ----
let edgeLines = null;
async function ensureEdges() {
  if (S.edges) return;
  S.edges = await getJson("edges/lut.json");
  S.adj = new Map();
  for (const [a, b] of S.edges) {
    (S.adj.get(a) ?? S.adj.set(a, []).get(a)).push(b);
    (S.adj.get(b) ?? S.adj.set(b, []).get(b)).push(a);
  }
}

let cellLines = null;
// the edges of the clicked Comb / Latched cell, bright
function drawCellEdges() {
  if (cellLines) { group.remove(cellLines); cellLines.geometry.dispose(); cellLines = null; }
  if (!S.cellEdges?.length) return;
  const pts = [];
  for (const [a, b] of S.cellEdges) pts.push(worldPos("lut", a), worldPos("lut", b));
  cellLines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xffe066 }));
  group.add(cellLines);
}
// every lut-plane edge coloured by Hutton's edge length (DFF and block edges, length 0, pink); with a
// selection only the edges that touch it
function lengthEdges(pts, cols) {
  const lut = S.planes.lut, lv = lut.metrics.logic_level;
  const hot = new Set([...highlighted()].filter((id) => S.byId.get(id)?.plane === "lut"));
  const dmax = Math.max(2, ...lv.filter((v) => v !== null));
  let n = 0;
  for (const [a, b, kind] of S.edges) {
    if (hot.size && !hot.has(a) && !hot.has(b)) continue;
    const ia = S.lutAt.get(a), ib = S.lutAt.get(b);
    if (lv[ia] == null || lv[ib] == null || n++ > 40000) continue;
    const len = edgeLength(kind, lv[ia], lv[ib]);
    const c = len === 0 ? new THREE.Color(FF_COL) : ramp(SEQ, (len - 1) / (dmax - 1));
    pts.push(worldPos("lut", a), worldPos("lut", b));
    cols.push(c.r, c.g, c.b, c.r, c.g, c.b);
  }
}
function drawEdges() {
  if (edgeLines) { group.remove(edgeLines); edgeLines.geometry.dispose(); edgeLines = null; }
  drawCellEdges();
  if (!S.edges || !S.edgeMode || !S.planes.lut) return;
  const pts = [], cols = [];
  if (S.edgeMode === "length") lengthEdges(pts, cols);
  else if (S.edgeMode === "groups") {
    const bl = S.group.blobs.lut;
    if (!bl) return;
    const of = new Map();
    bl.list.forEach((g, n) => g.members.forEach((i) => of.set(S.planes.lut.ids[i], n)));
    const cen = bl.list.map((g) => {
      let x = 0, z = 0;
      for (const i of g.members) { const q = S.pos.lut[S.planes.lut.ids[i]]; x += q[0]; z += q[1]; }
      return new THREE.Vector3(x / g.members.length - cx(), planeY(S.order.indexOf("lut")), z / g.members.length - cz());
    });
    const cnt = new Map();
    for (const [a, b] of S.edges) {
      const ga = of.get(a), gb = of.get(b);
      if (ga === undefined || gb === undefined || ga === gb) continue;
      const key = ga < gb ? `${ga}|${gb}` : `${gb}|${ga}`;
      cnt.set(key, (cnt.get(key) ?? 0) + 1);
    }
    const mx = Math.max(1, ...cnt.values());
    for (const [key, c] of cnt) {
      const [ga, gb] = key.split("|").map(Number);
      pts.push(cen[ga], cen[gb]);
      const t = 0.25 + 0.75 * (c / mx);
      cols.push(t, t * 0.8, 0.2, t, t * 0.8, 0.2);
    }
  } else {
    const start = new Set();
    const ids = S.brush ? [...S.brush, ...S.core] : S.sel ? [S.sel, ...S.core] : [];
    for (const id of ids) if (S.byId.get(id)?.plane === "lut" && start.size < 300) start.add(id);
    let seen = new Set(start), frontier = [...start];
    for (let h = 0; h < S.hops; h++) {
      const next = [];
      for (const id of frontier) for (const t of S.adj.get(id) ?? []) if (!seen.has(t)) { seen.add(t); next.push(t); }
      frontier = next;
    }
    let n = 0;
    for (const [a, b] of S.edges) {
      if (!seen.has(a) || !seen.has(b) || n++ > 4000) continue;
      pts.push(worldPos("lut", a), worldPos("lut", b));
      cols.push(0.3, 0.9, 1, 0.3, 0.9, 1);
    }
  }
  if (!pts.length) return;
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  edgeLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7 }));
  group.add(edgeLines);
}

// ---- views: the 3D stack, or one plane seen from above ----
function applyVisibility() {
  for (const p of S.order) {
    const v = S.vis[p] !== false && (S.view === "stack" || S.view === p);
    meshes[p].forEach((m) => { m.visible = v; });
    if (markMesh[p]) markMesh[p].visible = v;
    quads[p].q.visible = quads[p].edge.visible = quads[p].lab.visible = v;
    if (S.group.blobs[p]) S.group.blobs[p].mesh.visible = v;
  }
  if (S.clbFF) S.clbFF.mesh.visible = S.vis.clb !== false && (S.view === "stack" || S.view === "clb");
  drawFFEdges();
  drawGraphs();
}
function setView(v) {
  S.view = v;
  $("viewmode").value = v;
  applyVisibility();
  controls.touches.ONE = v === "stack" ? THREE.TOUCH.ROTATE : THREE.TOUCH.PAN; // a single plane view cannot rotate
  if (v === "stack") { controls.enableRotate = true; resetCamera(); return; }
  const y = planeY(S.order.indexOf(v)), W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  controls.enableRotate = false;
  controls.autoRotate = false; $("rotate").checked = false;
  controls.target.set(0, y, 0);
  camera.position.set(0, y + W * 1.5, 0.001);
  controls.update();
}

// ---- brush: shift + drag a rectangle on the screen; objects of the brush plane inside it are selected ----
function brushSelect(x0, y0, x1, y1) {
  const p = $("brushplane").value, d = S.planes[p], r = $("view").getBoundingClientRect(), hit = new Set();
  d.ids.forEach((id, i) => {
    if (hiddenByGroup(p, i)) return;
    const v = worldPos(p, id).project(camera);
    const sx = ((v.x + 1) / 2) * r.width + r.left, sy = ((1 - v.y) / 2) * r.height + r.top;
    if (sx >= Math.min(x0, x1) && sx <= Math.max(x0, x1) && sy >= Math.min(y0, y1) && sy <= Math.max(y0, y1)) hit.add(id);
  });
  if (!hit.size) return;
  const core = new Set();
  let n = 0;
  for (const id of hit) { if (n++ > 600) break; for (const t of [...closure(id, "up"), ...closure(id, "down")]) core.add(t); }
  S.sel = null; S.brush = hit; S.core = core; S.lineSel = null; S.path = null;
  S.mode = { type: "brush", n: hit.size, plane: p };
  afterSelection();
}

// ---- discovery: Spearman and mutual information between the metrics of one plane ----
function discover() {
  const p = $("dplane").value, d = S.planes[p], kind = $("dkind").value;
  const names = Object.keys(d.metrics).filter((n) => {
    const v = d.metrics[n].filter((x) => x !== null);
    return v.length >= 10 && new Set(v).size > 1;
  });
  const fn = kind === "mi" ? mutualInfo : spearman;
  let html = `<div class="sub">${names.length} metrics with 10 or more values on ${p} (${d.ids.length} objects); click a cell: colour = row, size = column</div><table><tr><td></td>${names.map((n, j) => `<td title="${esc(n)}">${j + 1}</td>`).join("")}</tr>`;
  names.forEach((a, i) => {
    html += `<tr><td title="${esc(a)}">${i + 1} ${esc(a.slice(0, 14))}</td>`;
    names.forEach((b) => {
      const v = a === b ? null : fn(d.metrics[a], d.metrics[b]);
      const t = v === null ? 0 : kind === "mi" ? Math.min(1, v / 2) : Math.abs(v);
      const hue = kind === "mi" ? 40 : v !== null && v < 0 ? 5 : 210;
      const sh = v === null ? "" : kind === "mi" ? v.toFixed(2) : v.toFixed(2);
      html += `<td data-a="${esc(a)}" data-b="${esc(b)}" style="background:hsla(${hue},70%,50%,${(0.1 + 0.8 * t).toFixed(2)});cursor:pointer;text-align:center">${sh}</td>`;
    });
    html += "</tr>";
  });
  $("dmat").innerHTML = html + "</table>";
  $("dmat").querySelectorAll("td[data-a]").forEach((c) => c.addEventListener("click", () => {
    if (c.dataset.a === c.dataset.b) return;
    S.colour = c.dataset.a; S.size = c.dataset.b; $("colour").value = S.colour; $("size").value = S.size; refreshAll();
  }));
}
export const discoverMatrix = (plane, kind) => {
  const d = S.planes[plane], fn = kind === "mi" ? mutualInfo : spearman;
  const names = Object.keys(d.metrics).filter((n) => d.metrics[n].filter((x) => x !== null).length >= 10);
  return { names, m: names.map((a) => names.map((b) => (a === b ? null : fn(d.metrics[a], d.metrics[b])))) };
};

// ---- plane control: focus (camera on a plane), zoom towards the cursor, solo ----
function setColour(n) {
  if (!meta(n) && !["@bus", "@cluster", "@role", "@an"].includes(n)) return;
  S.colour = n; $("colour").value = n; refreshAll();
}

function markFocus() {
  document.querySelectorAll("#sel .prow").forEach((r) => r.classList.toggle("on", r.querySelector("button")?.dataset.focus === S.focus));
  if (!quads) return;
  for (const p of S.order) if (quads[p]) quads[p].edge.material.color.set(p === S.focus ? 0xffb454 : 0x6d7f99);
}

const baseOrder = () => S.order.filter((p) => !isGraph(p));
// keep the checkboxes of the Planes list and of the Graph planes section in step with S.vis
function syncGraphBoxes() {
  $("planes").querySelectorAll("input[data-p]").forEach((c) => { c.checked = S.vis[c.dataset.p] !== false; });
  document.querySelectorAll("#gpanel input[data-g]").forEach((c) => { c.checked = S.vis[c.dataset.g] !== false; });
}
// switch a graph plane on or off (keys s, c, d); on: it joins the stack above the HDL plane and takes focus
export function showGraph(p, on = S.vis[p] === false) {
  if (!isGraph(p) || !S.order.includes(p)) return;
  S.vis[p] = on; S.solo = null;
  syncGraphBoxes();
  layout();
  applyVisibility();
  refreshAll();
  if (on) focusPlane(p); else if (S.focus === p) focusPlane(null); else resetCamera();
}
export function focusPlane(p) {
  if (!p) { S.focus = null; if (S.view === "stack") resetCamera(); markFocus(); return; }
  if (!S.order.includes(p)) return;
  if (S.view !== "stack") { setView(p); S.focus = p; markFocus(); return; }
  S.focus = p;
  const y = planeY(S.order.indexOf(p)), W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  const off = camera.position.clone().sub(controls.target);
  if (off.length() < 1e-6) off.set(0.3, 0.8, 0.5);
  off.y = Math.max(off.y, off.length() * 0.6);
  off.setLength(Math.max(W * 1.35, 8));
  controls.target.set(0, y, 0);
  camera.position.copy(controls.target).add(off);
  controls.update();
  markFocus();
}

export function soloPlane(p) {
  const off = S.solo === p;
  for (const q of S.order) S.vis[q] = off ? !isGraph(q) : q === p;
  S.solo = off ? null : p;
  syncGraphBoxes();
  layout();
  applyVisibility();
}

// the wheel zooms towards the point under the cursor on the focused plane (or on the nearest plane under the
// cursor when none is focused): the camera and the orbit target both move towards that point
function wheelZoom(ev) {
  ev.preventDefault();
  const dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
  zoomAt(ev.clientX, ev.clientY, Math.exp(dy * 0.0013));
}

// f < 1 zooms in, f > 1 out, towards the screen point (cx, cy); used by the wheel, the touch pinch and the buttons
function zoomAt(cx, cy, f) {
  const r = $("view").getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), camera);
  const ray = raycaster.ray, W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  let best = null;
  for (const p of S.focus ? [S.focus] : S.order) {
    if (!S.focus && S.vis[p] === false) continue;
    const y = planeY(S.order.indexOf(p));
    if (Math.abs(ray.direction.y) < 1e-6) continue;
    const t = (y - ray.origin.y) / ray.direction.y;
    if (t <= 0) continue;
    const hit = ray.origin.clone().addScaledVector(ray.direction, t);
    if (!S.focus && (Math.abs(hit.x) > W / 2 || Math.abs(hit.z) > H / 2)) continue;
    if (!best || t < best.t) best = { t, hit };
  }
  const P = best ? best.hit : controls.target.clone();
  const dist = camera.position.distanceTo(P);
  if (dist * f < 0.6) f = 0.6 / Math.max(dist, 1e-6);
  if (dist * f > 1500) f = 1500 / dist;
  const dc = camera.position.clone().sub(P), dt = controls.target.clone().sub(P);
  camera.position.copy(P).addScaledVector(dc, f);
  controls.target.copy(P).addScaledVector(dt, f);
  controls.update();
}

// Touch: one finger rotates (OrbitControls), two fingers pan (OrbitControls) and pinch zooms towards the pinch centre
// (OrbitControls' own dolly is off: enableZoom = false). `cancelTap` is called when a second finger lands, so the end
// of a gesture is never taken for a tap. The + / - / fit buttons zoom about the middle of the view.
function setupTouch(cv, cancelTap) {
  const pts = new Map();
  let last = null;
  const state = () => { const [a, b] = [...pts.values()]; return { d: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; };
  cv.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "touch") return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) { last = state(); cancelTap(); }
  });
  cv.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "touch" || !pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size !== 2 || !last) return;
    const now = state();
    if (now.d > 1 && last.d > 1) zoomAt(now.x, now.y, last.d / now.d);
    last = now;
  });
  const end = (e) => { pts.delete(e.pointerId); if (pts.size < 2) last = null; };
  cv.addEventListener("pointerup", end);
  cv.addEventListener("pointercancel", end);
  const mid = () => { const r = cv.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  $("zin").addEventListener("click", () => zoomAt(...mid(), 0.7));
  $("zout").addEventListener("click", () => zoomAt(...mid(), 1 / 0.7));
  $("zfit").addEventListener("click", () => { if (S.view === "stack") resetCamera(); else setView(S.view); });
}

// previous / next page in the complexity order of the index (the site writes _assets/order.json; absent when served locally)
async function setupOrderNav() {
  const url = document.body.dataset.order; // set by the site builder only
  if (!url) return;
  try {
    const r = await fetch(url);
    if (!r.ok) return;
    const slugs = (await r.json()).slugs, here = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() ?? "");
    const i = slugs.indexOf(here);
    if (i < 0) return;
    const link = (j, text) => (j >= 0 && j < slugs.length ? `<a href="../${slugs[j]}/">${text}</a>` : `<span class="dim">${text}</span>`);
    $("ordnav").innerHTML = `${link(i - 1, "&larr; simpler")} &middot; <a href="../">index</a> &middot; ${link(i + 1, "more complex &rarr;")} <span class="sub">(${i + 1} of ${slugs.length})</span>`;
  } catch { /* not part of a built site */ }
}

// ---- paths: VPR's reported setup paths, and the combinational cone of the selection in the LUT netlist ----
let pathLines = null;
const PATH_COL = { vpr: [1, 0.42, 0.42], in: [0.37, 0.88, 1], out: [1, 0.44, 0.85] };

function drawPathLines() {
  if (pathLines) { group.remove(pathLines); pathLines.geometry.dispose(); pathLines = null; }
  const pts = [], cols = [], seen = new Set();
  const seg = (plane, a, b, c) => {
    if (!S.pos[plane]?.[a] || !S.pos[plane]?.[b]) return;
    const key = plane + a + "|" + b;
    if (seen.has(key) || pts.length > 24000) return;
    seen.add(key);
    pts.push(worldPos(plane, a), worldPos(plane, b));
    cols.push(...c, ...c);
  };
  if (S.path) {
    for (const list of [S.path.lut, S.path.placed]) for (let i = 1; i < list.length; i++) seg(S.byId.get(list[i])?.plane, list[i - 1], list[i], PATH_COL.vpr);
  }
  if (S.cone) {
    const placedOf = (id) => {
      const o = S.byId.get(id);
      const pid = o && S.planes.placed ? "placed:" + S.planes.lut.name[o.i] : null;
      return pid && S.byId.has(pid) ? pid : null;
    };
    for (const [a, b, tag] of S.cone.edges) {
      seg("lut", a, b, PATH_COL[tag]);
      const pa = placedOf(a), pb = placedOf(b);
      if (pa && pb) seg("placed", pa, pb, PATH_COL[tag]);
    }
  }
  if (!pts.length) return;
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  pathLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false }));
  pathLines.renderOrder = 5;
  group.add(pathLines);
}

export function showPath(i) {
  const P = S.paths[i];
  if (!P) return;
  S.sel = null; S.lineSel = null; S.cone = null; S.coneOn = false;
  $("pathsrc").value = "vpr"; showPathPanel();
  const ids = [...P.lut, ...P.placed].filter((x) => S.byId.has(x));
  const core = new Set();
  for (const l of P.lut) {
    for (const u of S.up.get(l) ?? []) if (S.byId.get(u)?.plane === "hdl" && core.size < 3000) core.add(u);
    for (const d of S.down.get(l) ?? []) if (S.byId.get(d)?.plane === "clb") core.add(d);
  }
  S.path = { lut: P.lut, placed: P.placed, i };
  S.brush = new Set(ids); S.core = core;
  S.pathInfo = `source: VPR report_timing.setup.rpt, path #${P.n}, slack ${fmt(P.slack)} ns, ${P.lut.length} LUT-plane and ${P.placed.length} placed objects`;
  S.mode = { type: "path" };
  $("pathinfo").innerHTML = `<span class="tag">source: VPR report_timing.setup.rpt</span>, path #${P.n}, slack ${fmt(P.slack)} ns, ${P.lut.length} LUT-plane and ${P.placed.length} placed objects. ${esc(P.start)} to ${esc(P.end)}`;
  document.querySelectorAll("#pathlist div").forEach((e) => e.classList.toggle("on", Number(e.dataset.i) === i));
  afterSelection();
}

function coneSeeds() {
  const out = new Set();
  const add = (id) => {
    const o = S.byId.get(id);
    if (!o || out.size >= 300) return;
    if (o.plane === "lut") out.add(id);
    else if (o.plane === "placed") { const l = `luts:${S.man.top}/${S.planes.placed.name[o.i]}`; if (S.byId.has(l)) out.add(l); }
  };
  if (S.sel) add(S.sel);
  for (const id of S.brush ?? []) add(id);
  for (const id of S.core) add(id);
  return out;
}

export async function updateCone() {
  await ensureEdges();
  const seeds = [...coneSeeds()], dir = $("conedir").value, depth = Math.max(1, Number($("conedepth").value) || 6);
  if (!seeds.length) {
    S.cone = null;
    $("pathinfo").textContent = "cone: select an HDL line or an object that has LUT-plane objects first";
    refreshAll();
    return;
  }
  const lut = S.planes.lut;
  S.cone = coneOf(S.edges, seeds, dir, depth, (id) => lut.type[S.byId.get(id)?.i] === "names");
  const nodes = S.cone.nodes.size, label = { in: "fan-in", out: "fan-out", both: "fan-in and fan-out" }[dir];
  $("pathinfo").innerHTML = `<span class="tag">source: netlist cone (edges/lut.json)</span>, ${label}, depth limit ${depth}, from ${seeds.length} seed${seeds.length === 1 ? "" : "s"}: ${nodes} objects, ${S.cone.edges.length} edges. Stops at flip-flops, I/O and hard blocks.`;
  refreshAll();
}

function showPathPanel() {
  const cone = $("pathsrc").value === "cone";
  $("pathvpr").style.display = cone ? "none" : "";
  $("pathcone").style.display = cone ? "" : "none";
}

function buildPathsUi() {
  const list = $("pathlist");
  list.innerHTML = S.paths.length ? S.paths.map((P, i) =>
    `<div data-i="${i}" title="${esc(P.start)} to ${esc(P.end)}">#${P.n}  ${P.slack.toFixed(3)} ns  ${esc(P.start.split(" ")[0])} &gt; ${esc(P.end.split(" ")[0])}  (${P.lut.length} LUT-plane)</div>`).join("")
    : '<div class="sub">no setup-report paths in this bundle (re-export with a VPR run that kept report_timing.setup.rpt)</div>';
  list.querySelectorAll("div[data-i]").forEach((d) => d.addEventListener("click", () => showPath(Number(d.dataset.i))));
  const clearPath = () => {
    S.path = null; S.cone = null; $("pathinfo").textContent = "no path drawn";
    document.querySelectorAll("#pathlist div.on").forEach((e) => e.classList.remove("on"));
    if (S.mode.type === "path") clearSel(); else { refreshAll(); markLines(); }
  };
  $("pathclear").addEventListener("click", clearPath);
  $("pathsrc").addEventListener("change", async () => {
    showPathPanel();
    S.coneOn = $("pathsrc").value === "cone";
    if (S.coneOn) { S.path = null; await updateCone(); markLines(); } else { S.cone = null; $("pathinfo").textContent = "no path drawn"; refreshAll(); markLines(); }
  });
  for (const id of ["conedir", "conedepth"]) $(id).addEventListener("change", async () => { await updateCone(); markLines(); });
}

// ---- UI ----
function fillSelect(sel, names, withNone) {
  sel.innerHTML = (withNone ? '<option value="">(none)</option>' : "") +
    names.map((n) => `<option value="${n}">${n}${meta(n) ? "  [" + meta(n).unit + "]" : ""}</option>`).join("");
}
function legend() {
  const name = S.colour;
  $("buspanel").style.display = name === "@bus" ? "block" : "none";
  if (name === "@bus") { $("legend").style.display = "none"; $("cover").innerHTML = ""; fillBusList(); return; }
  if (name === "@an") { $("legend").style.display = "none"; $("cover").innerHTML = anLegend(); return; }
  if (name === "@cluster" || name === "@role") { $("legend").style.display = "none"; $("cover").innerHTML = name === "@role" ? roleLegend() : clusterLegend(); return; }
  $("legend").style.display = name ? "block" : "none";
  if (!name) { coverLegend(); return; }
  const [lo, hi] = metricRange(name), div = meta(name).scale === "div";
  const stops = div ? DIV : SEQ;
  $("bar").style.background = `linear-gradient(90deg, ${stops.map((c) => "#" + c.getHexString()).join(",")})`;
  const m = Math.max(Math.abs(lo), Math.abs(hi));
  $("lo").textContent = div ? fmt(-m) : fmt(lo);
  $("hi").textContent = div ? fmt(m) : fmt(hi);
  $("mid").textContent = div ? "0" : "";
  coverLegend();
  $("unit").textContent = `${meta(name).unit}; grey = not measured. ${meta(name).measurer}` +
    (meta(name).clip ? `. The colour range ends at the ${Math.round(meta(name).clip * 100)}th percentile; larger values show the top colour (clock nets toggle twice per cycle).` : "");
}
const roleLegend = () => '<span style="color:#ff4fd8">&#9632;</span> flip-flop <span style="color:#ffb454">&#9632;</span> latched node (drives a D input) ' +
  '<span style="color:#4cd9a0">&#9632;</span> drives a primary output <span style="color:#8fc1ff">&#9632;</span> other; grey = no delay level';
function clusterLegend() {
  const src = S.cl?.sources[S.csrc];
  if (!src) return "";
  const head = `<div class="sub">${esc(src.label)}: ${src.k} clusters; grey = no cluster</div>`;
  return head + src.names.slice(0, 40).map((n, k) => n === "(none)" ? "" : `<div><span style="color:hsl(${busHue(k).toFixed(0)},75%,55%)">&#9632;</span> ${esc(n)} <span class="sub">${src.sizes[k]}</span></div>`).join("") +
    (src.k > 40 ? `<div class="sub">and ${src.k - 40} more</div>` : "");
}
// bus mode: the list of buses (filterable); click selects every object of the bus on every plane
function fillBusList() {
  const f = S.busFilter.toLowerCase();
  const list = (S.man.buses ?? []).filter((b) => !f || b.name.toLowerCase().includes(f));
  $("buslist").innerHTML = list.map((b) => {
    const k = S.busIndex.get(b.name), n = Object.values(b.counts).reduce((t, v) => t + v, 0);
    const col = "hsl(" + busHue(k).toFixed(0) + ",78%,55%)";
    return `<div class="bus" data-b="${esc(b.name)}"><span style="color:${col}">&#9632;</span> ${esc(b.name)}` +
      `<span class="sub"> [${b.width}] ${b.kind}, ${n} obj</span></div>`;
  }).join("");
  $("buslist").querySelectorAll(".bus").forEach((e) => e.addEventListener("click", () => selectBus(e.dataset.b)));
  const none = S.order.map((p) => {
    const d = S.planes[p];
    return d.bus ? `${p}: ${d.bus.filter((b) => !b).length}/${d.ids.length}` : `${p}: all`;
  }).join(", ");
  $("busnone").textContent = `no bus (grey): ${none}`;
}

export function selectBus(name) {
  const ids = [];
  for (const p of S.order) { const d = S.planes[p]; d.bus?.forEach((b, i) => { if (b === name) ids.push(d.ids[i]); }); }
  const info = (S.man.buses ?? []).find((b) => b.name === name);
  S.sel = null; S.brush = new Set(ids); S.core = new Set(); S.path = null; S.tier = null; S.tierInfo = null;
  const decl = info?.decl ?? null;
  S.lineSel = decl ? { file: decl[0], a: Number(decl[1].split(".")[0]), b: Number(decl[1].split(".")[0]) } : null;
  S.mode = { type: "bus", name, n: ids.length, decl };
  afterSelection();
}

// per plane: how many objects have a measured value for the colour metric (grey = none); never invented
export function coverage(name) {
  return S.order.map((p) => {
    const col = S.planes[p].metrics[name], total = S.planes[p].ids.length;
    const n = col ? col.filter((v) => v !== null).length : 0;
    return { plane: p, measured: n, total, range: n ? [Math.min(...col.filter((v) => v !== null)), Math.max(...col.filter((v) => v !== null))] : null };
  });
}
function coverLegend() {
  const el = $("cover");
  if (!S.colour) { el.innerHTML = ""; return; }
  el.innerHTML = coverage(S.colour).map((c) => c.measured
    ? `${c.plane}: ${c.measured}/${c.total} measured, ${fmt(c.range[0])} to ${fmt(c.range[1])}`
    : `${c.plane}: <span class="err" style="color:#ffb454">no measured value (grey)</span>`).join("<br>");
}

// ---- derived metrics: expressions and cross-plane aggregation ----
function fillMetricSelects() {
  const names = S.man.metrics.map((m) => m.name);
  for (const [id, none] of [["colour", true], ["size", true], ["height", true], ["fade", true], ["aggmetric", false]]) {
    const el = $(id), cur = el.value;
    fillSelect(el, names, none);
    if (id === "colour" && S.cl) el.insertAdjacentHTML("beforeend", '<option value="@cluster">cluster (current source)</option><option value="@role">role: FF, latched node, PO</option>');
    if (id === "colour" && S.an) el.insertAdjacentHTML("beforeend", '<option value="@an">graph analytics: cluster</option>');
    if (id === "colour" && S.man.buses?.length) el.insertAdjacentHTML("beforeend", '<option value="@bus">bus (hue per bus, shade per bit)</option>');
    if (names.includes(cur)) el.value = cur;
  }
}

function addMetric(name, scale, measurer, cols) {
  S.man.metrics = S.man.metrics.filter((m) => m.name !== name);
  S.man.metrics.push({ name, unit: "derived", planes: Object.keys(cols), scale, measurer, source: "o3viz editor" });
  for (const p of S.order) S.planes[p].metrics[name] = cols[p] ?? S.planes[p].ids.map(() => null);
  delete S.ranges[name];
  fillMetricSelects();
}

export function addExpr(name, text, scale = "seq") {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new Error("name: letters, digits, underscore");
  const ast = parse(text), vars = [...varsOf(ast)];
  for (const v of vars) if (!meta(v)) throw new Error(`unknown metric "${v}"`);
  if (vars.includes(name)) throw new Error("a metric cannot use its own name");
  const cols = {};
  for (const p of S.order) {
    const d = S.planes[p];
    if (vars.every((v) => d.metrics[v])) cols[p] = d.ids.map((_, i) => evaluate(ast, (n) => d.metrics[n][i]));
  }
  if (!Object.keys(cols).length) throw new Error("no plane has all of these metrics");
  addMetric(name, scale, `expression: ${text}`, cols);
}

const AGG = {
  sum: (v) => v.reduce((a, b) => a + b, 0), mean: (v) => v.reduce((a, b) => a + b, 0) / v.length,
  min: (v) => Math.min(...v), max: (v) => Math.max(...v), count: (v) => v.length,
};

export function addAgg(metric, dir, op) {
  if (!meta(metric) || !AGG[op] || !["below", "above"].includes(dir)) throw new Error("bad aggregation");
  const name = `${op}_${dir}_${metric}`, adj = dir === "below" ? S.down : S.up, cols = {};
  for (const p of S.order) {
    cols[p] = S.planes[p].ids.map((id) => {
      const vals = [];
      for (const t of adj.get(id) ?? []) {
        const b = S.byId.get(t), v = S.planes[b.plane].metrics[metric]?.[b.i];
        if (v !== null && v !== undefined) vals.push(v);
      }
      return vals.length ? AGG[op](vals) : null;
    });
  }
  addMetric(name, meta(metric).scale, `${op} of ${metric} over the objects linked ${dir}`, cols);
  return name;
}

async function changeAnchor(name) {
  $("anchor").value = name;
  await loadAnchor(name); resizeQuads(); layout(); resetCamera();
  const a = S.anchorMeta;
  if (a.source && S.cl) {
    S.csrc = a.source; S.clCache = {}; $("csrc").value = a.source;
    if (!S.colour) { S.colour = "@cluster"; $("colour").value = "@cluster"; }
  }
  refreshAll();
  showCircuit();
}

// ---- circuit panel: Hutton shapes (whole circuit or selection), Kundarewich Comb / Latched matrices ----
function selectedLut() {
  const hot = [...highlighted()].filter((id) => S.byId.get(id)?.plane === "lut").map((id) => S.byId.get(id).i);
  return hot.length ? hot : null;
}
function shapePanel() {
  const lut = S.planes.lut, all = lut.ids.map((_, i) => i);
  const sel = $("cscope").value === "selection" ? selectedLut() : null;
  const c = characterize(lut, sel ?? all, S.edges ?? []);
  S.shape = c;
  const what = sel ? `${sel.length} selected lut-plane objects` : $("cscope").value === "selection" ? "no lut-plane object selected: whole circuit" : "whole circuit";
  return `<div class="sub">${what}: ${c.nodes} objects (${c.pis} primary inputs), dmax ${c.dmax}; DFF edges ${c.dff_edges}, block edges ${c.block_edges}</div><div class="shapes">` +
    barChart("node shape (objects per delay level)", c.node_shape) + barChart("input shape (LUT input pins)", c.input_shape) +
    barChart("output shape (objects with fanout)", c.output_shape) + barChart("PO shape", c.po_shape) +
    barChart("edge length (edges into LUTs)", c.edge_length, { max: 16 }) + barChart("fanout (LUTs driven)", c.fanout, { max: 16 }) + "</div>";
}
function sourceBlock(key, n) {
  const sr = S.cl.sources[key];
  const extra = [sr.cut !== undefined ? `cut ${sr.cut} nets` : "", sr.ambiguous !== undefined ? `${sr.ambiguous} objects reach several clusters (smallest span taken)` : "",
    sr.fallback ? `${sr.fallback} items fell back to their block` : "", sr.unassigned ? `${sr.unassigned} without cluster` : ""].filter(Boolean).join("; ");
  return `<div class="src" data-key="${key}"><b>${esc(sr.label)}</b> <span class="sub">k ${sr.k}, ${sr.edges} edges, ${sr.inter_pct === null ? "-" : sr.inter_pct.toFixed(1)}% between clusters${extra ? "; " + esc(extra) : ""}</span>` +
    `<div class="mats"><div><canvas data-m="shape" data-n="${n}"></canvas><div class="sub">cluster x level</div></div>` +
    `<div><canvas data-m="comb" data-n="${n}"></canvas><div class="sub">Comb (to LUTs)</div></div>` +
    `<div><canvas data-m="latched" data-n="${n}"></canvas><div class="sub">Latched (to FFs)</div></div></div></div>`;
}
const circuitKeys = () => ($("ccompare").checked ? [S.csrc, $("csrc2").value] : [S.csrc]);
function clusterPanel(keys) {
  let html = keys.map(sourceBlock).join("");
  if (keys.length === 2 && keys[0] !== keys[1]) {
    const v = S.cl.nmi[`${keys[0]}|${keys[1]}`] ?? S.cl.nmi[`${keys[1]}|${keys[0]}`];
    html += `<div class="sub">Normalised mutual information of the two partitions: ${v === null || v === undefined ? "not defined" : v.toFixed(3)} (0 unrelated, 1 the same). Descriptive only.</div>`;
  }
  return html;
}
function paintClusters(keys) {
  keys.forEach((key, n) => {
    const sr = S.cl.sources[key];
    document.querySelectorAll(`#cpanel canvas[data-n="${n}"]`).forEach((cv) => {
      const which = cv.dataset.m;
      if (which === "shape") { drawShape(cv, sr.shape); return; }
      drawMatrix(cv, sr[which]);
      const hit = (e) => { const r = cv.getBoundingClientRect(); return cellAt(e.clientX - r.left, e.clientY - r.top, sr.k, r.width); };
      cv.onmousemove = (e) => { const [i, j] = hit(e); cv.title = `${sr.names[i]} -> ${sr.names[j]}: ${sr[which][i][j]}`; };
      cv.onclick = (e) => { const [i, j] = hit(e); selectCell(key, which, i, j); };
    });
  });
}
async function selectCell(key, which, i, j) {
  await ensureEdges();
  const sr = S.cl.sources[key], list = cellEdges(S.edges, sr.of, S.lutAt, i, j, which);
  const hit = new Set();
  for (const [a, b] of list) { hit.add(a); hit.add(b); }
  const core = new Set();
  let n = 0;
  for (const id of hit) { if (n++ > 400) break; for (const t of [...closure(id, "up"), ...closure(id, "down")]) core.add(t); }
  S.sel = null; S.brush = hit; S.core = core; S.lineSel = null; S.path = null; S.tier = null; S.tierInfo = null; S.cellEdges = list;
  S.mode = { type: "cell", n: list.length, text: `${which === "comb" ? "Comb" : "Latched"}[${sr.names[i]} -> ${sr.names[j]}]` };
  await afterSelection();
}
async function showCircuit() {
  if (!S.cl) return;
  await ensureEdges();
  const keys = circuitKeys();
  $("cshapes").innerHTML = shapePanel();
  $("cpanel").innerHTML = clusterPanel(keys);
  paintClusters(keys);
}
function buildCircuitUi() {
  if (!S.cl) { $("circuit").style.display = "none"; return; }
  const opts = S.cl.order.map((k) => `<option value="${k}">${esc(S.cl.sources[k].label)} (k ${S.cl.sources[k].k})</option>`).join("");
  $("csrc").innerHTML = opts; $("csrc2").innerHTML = opts;
  S.csrc = S.cl.order.includes("hdl-block") ? "hdl-block" : S.cl.order[0];
  $("csrc").value = S.csrc;
  $("csrc2").value = S.cl.order.includes("mincut") ? "mincut" : S.cl.order[S.cl.order.length - 1];
  $("csrc").addEventListener("change", async (e) => {
    S.csrc = e.target.value; S.clCache = {};
    if (S.anchor.startsWith("kundarewich-")) { $("anchor").value = "kundarewich-" + S.csrc; await changeAnchor("kundarewich-" + S.csrc); return; }
    refreshAll(); showCircuit();
  });
  for (const id of ["csrc2", "ccompare", "cscope"]) $(id).addEventListener("change", showCircuit);
  showCircuit();
}

// ---- graph planes: switches, k-hop, labels; SCOAP colour with joins ----
function buildGraphUi() {
  const kinds = S.order.filter(isGraph);
  $("gsec").style.display = kinds.length ? "" : "none";
  $("gpanel").innerHTML = kinds.map((p) => `<label class="row"><input type="checkbox" data-g="${p}" style="width:auto"> ${p} ` +
    `(${S.planes[p].ids.length} nodes, ${S.g.data[p].edges.length} edges; key ${Object.keys(GKEYS).find((k) => GKEYS[k] === p)})</label>`).join("");
  $("gpanel").querySelectorAll("input[data-g]").forEach((c) => c.addEventListener("change", () => showGraph(c.dataset.g, c.checked)));
  $("gall").addEventListener("change", (e) => { S.g.all = e.target.checked; drawGraphs(); });
  $("ghops").addEventListener("change", (e) => { S.g.hops = Number(e.target.value); drawGraphs(); });
  $("glabels").addEventListener("change", (e) => { S.g.labels = e.target.checked; drawGraphs(); });
  $("scoapgo").addEventListener("click", () => { setColour(scoapColour($("scoapm").value, $("scoapop").value)); });
  syncGraphBoxes();
}
// metric `m` (cc0, cc1, co) on every plane: its own value where measured (lut, placed, ddg), else min, max or mean
// over the linked objects that have one (direct links, repeated so the value reaches hdl, stg and cfg)
export function scoapColour(m, op) {
  if (!meta(m) || !["min", "max", "mean"].includes(op)) throw new Error("bad scoap join");
  const name = `${m}_${op}_all`;
  const cols = Object.fromEntries(S.order.map((p) => [p, S.planes[p].metrics[m] ?? S.planes[p].ids.map(() => null)]));
  const ids = Object.fromEntries(S.order.map((p) => [p, S.planes[p].ids]));
  const out = propagate(cols, ids, (id) => [...(S.up.get(id) ?? []), ...(S.down.get(id) ?? [])],
    (id) => { const o = S.byId.get(id); return [o.plane, o.i]; }, op);
  addMetric(name, meta(m).scale, `${m}: own value where Odin III's scoap pass measured it, else ${op} over the linked objects that have one`, out);
  return name;
}

// ---- graph analytics: orbit heat, clusterings, signature compare (data from the exporter; Odin III counted) ----
const anPlanes = () => Object.keys(S.an.index.planes);
async function anData(p) {
  return (S.an.data[p] ??= await getJson(`analytics/${p}.json`));
}
function anColour(p, i) {
  const cur = S.an?.cur, lab = cur?.labels[p];
  if (!lab || lab[i] === undefined) return GREY.clone();
  return new THREE.Color(av.clusterHex(cur.sizes[p], lab[i]));
}
function anLegend() {
  const cur = S.an?.cur;
  if (!cur) return '<div class="sub">choose a clustering in Graph analytics</div>';
  return `<div class="sub">${esc(cur.text)}: colours follow cluster size (red largest); grey = plane has no such clustering</div>`;
}
async function anOrbitHeat() {
  const m = $("anmode").value, j = +$("anorbit").value, name = `gdv_${m}_o${j}`, cols = {};
  for (const p of anPlanes()) cols[p] = av.orbitColumn((await anData(p))[`gdv_${m}`], j);
  addMetric(name, "seq", `log(1 + count) of ${m === "u" ? "undirected" : "directed"} orbit ${j} per node (Odin III graphlets)`, cols);
  const mt = meta(name);
  mt.unit = "log(1+count)"; mt.source = "odin3 graphlets";
  S.colour = name; $("colour").value = name;
  refreshAll();
}
async function anPickClustering() {
  const f = $("anfeat").value, a = $("analg").value, k = $("ank").value, labels = {}, sizes = {}, info = [];
  for (const p of anPlanes()) {
    const r = av.findClustering(S.an.index.planes[p].clusterings, f, a, k);
    if (!r) continue;
    labels[p] = (await anData(p)).cl[r.key];
    sizes[p] = r.sizes;
    info.push(`${p}: ${r.k} clusters` + (r.silhouette !== null ? `, silhouette ${r.silhouette}` : "") + (r.capped ? `, AP on the ${r.cap} most frequent of ${r.distinct} distinct vectors, the rest join the nearest exemplar` : ""));
  }
  S.an.cur = { labels, sizes, text: `${f} ${a} ${k}`, feature: f, alg: a };
  S.colour = "@an"; $("colour").value = "@an";
  $("aninfo").innerHTML = info.map(esc).join("<br>") || "no plane has this clustering";
  fillAnList();
  refreshAll();
}
function fillAnList() {
  const cur = S.an.cur, p = $("anlplane").value;
  if (!cur?.labels[p]) { $("anlist").innerHTML = '<div class="sub">no clustering on this plane</div>'; return; }
  const sz = cur.sizes[p], order = sz.map((_, c) => c).sort((a, b) => sz[b] - sz[a] || a - b);
  $("anlist").innerHTML = order.slice(0, 64).map((c) => `<div class="ancl" data-c="${c}" style="cursor:pointer"><span style="color:${av.clusterHex(sz, c)}">&#9632;</span> cluster ${c} <span class="sub">${sz[c]}</span></div>`).join("") +
    (order.length > 64 ? `<div class="sub">and ${order.length - 64} more</div>` : "");
  $("anlist").querySelectorAll(".ancl").forEach((el) => el.addEventListener("click", () => anClusterGroup(p, +el.dataset.c)));
}
const AN_GROUP_CAP = 2000;
async function anClusterGroup(p, c) {
  const d = S.planes[p], all = av.members(d.ids, S.an.cur.labels[p], c), ids = all.slice(0, AN_GROUP_CAP);
  clearGroups(S.groups);
  ids.forEach((id, k) => (k ? addToCurrent(S.groups, id) : addGroup(S.groups, id)));
  applyGroups();
  $("aninfo").textContent = `cluster ${c} of ${p}: ${all.length} objects as an update-4 group` + (all.length > ids.length ? ` (first ${ids.length} used)` : "");
}
function fillAnOrbits() {
  const m = $("anmode").value, n = S.an.index.modes[m].orbits;
  $("anorbit").innerHTML = Array.from({ length: n }, (_, j) => `<option value="${j}">orbit ${j}</option>`).join("");
}
function fillAnK() {
  const ks = av.kChoices(anRuns(), $("anfeat").value, $("analg").value);
  $("ank").innerHTML = ks.map((k) => `<option>${k}</option>`).join("");
}
const anRuns = () => anPlanes().flatMap((p) => S.an.index.planes[p].clusterings);
function fillAnSig() {
  const p = $("ansp").value, m = $("ansm").value, sig = S.an.index.planes[p]?.signatures?.[m];
  const opts = (sig?.groups ?? []).map((g, i) => `<option value="${i}">${esc(g.key)} cluster ${g.cluster} (${g.nodes})</option>`).join("");
  $("ansa").innerHTML = opts; $("ansb").innerHTML = opts;
  if (sig && sig.groups.length > 1) $("ansb").value = "1";
  showAnSim();
}
function showAnSim() {
  const p = $("ansp").value, m = $("ansm").value, sig = S.an.index.planes[p]?.signatures?.[m];
  if (!sig || !sig.groups.length) { $("ansres").textContent = "no signatures for this plane and mode"; return; }
  const r = av.similarity(sig, +$("ansa").value, +$("ansb").value);
  $("ansres").innerHTML = `<table><tr><td>GDD agreement</td><td>${r.gdd.toFixed(4)}</td></tr><tr><td>cosine of log(1 + orbit totals)</td><td>${r.cosine.toFixed(4)}</td></tr><tr><td>nodes</td><td>${r.na} and ${r.nb}</td></tr></table>` +
    `<div class="sub">${esc(sig.mode)}; Odin III graphlets --compare on the signatures of the two clusters (orbit totals and GDD, counted on each cluster's own subgraph).</div>`;
}
// ---- compare any two selections (browser-side; metric code ported from Odin III sig.c, see selcompare.js) ----
const SC_CLUSTER_CAP = 64;
function scGroupIds(k) {
  const g = S.groups.groups[k], out = new Set();
  for (const id of g?.ids ?? []) { out.add(id); for (const x of closure(id, "up")) out.add(x); for (const x of closure(id, "down")) out.add(x); }
  return out;
}
// ids (all planes) of a source: "cur", "snap:i", "grp:k" or "cl:c" (cluster c of the shown clustering on the chosen plane)
function scIds(src) {
  const [kind, v] = src.split(":");
  if (kind === "cur") return highlighted();
  if (kind === "snap") return S.an.snaps[+v]?.ids ?? new Set();
  if (kind === "grp") return scGroupIds(+v);
  if (kind === "cl") { const p = $("scp").value, lab = S.an.cur?.labels[p]; return new Set(lab ? av.members(S.planes[p].ids, lab, +v) : []); }
  return new Set();
}
function scOptions() {
  const o = [`<option value="cur">current selection (${highlighted().size})</option>`];
  S.an.snaps.forEach((s, i) => o.push(`<option value="snap:${i}">${esc(s.name)}</option>`));
  S.groups.groups.forEach((g, k) => o.push(`<option value="grp:${k}">group ${k + 1} (${g.ids.length} clicked)</option>`));
  const p = $("scp").value, cur = S.an.cur;
  if (cur?.labels[p]) {
    const sz = cur.sizes[p], order = sz.map((_, c) => c).sort((a, b) => sz[b] - sz[a] || a - b);
    order.slice(0, SC_CLUSTER_CAP).forEach((c) => o.push(`<option value="cl:${c}">cluster ${c} of ${esc(cur.text)} (${sz[c]})</option>`));
  }
  return o.join("");
}
function scFill() {
  for (const id of ["sca", "scb"]) { const el = $(id), v = el.value; el.innerHTML = scOptions(); if ([...el.options].some((x) => x.value === v)) el.value = v; }
}
function scSnap() {
  const ids = new Set(highlighted());
  S.an.snaps.push({ name: `snapshot ${S.an.snaps.length + 1} (${ids.size} objects)`, ids });
  scFill();
  $("sca").value = `snap:${S.an.snaps.length - 1}`;
}
async function scIndex(p) {
  const d = await anData(p);
  return (S.an.idx[p] ??= new Map(d.ids.map((id, i) => [id, i])));
}
async function scCompare() {
  const p = $("scp").value, d = await anData(p), idx = await scIndex(p), out = {}, cnt = {};
  const modes = [["u", "undirected"], ["d", "directed"]];
  for (const [w, id] of [["A", "sca"], ["B", "scb"]]) {
    const all = scIds($(id).value), onPlane = [...all].filter((x) => S.byId.get(x)?.plane === p);
    out[w] = {};
    for (const [m] of modes) out[w][m] = sc.selectionSignature(d[`gdv_${m}`] ?? null, idx, onPlane, S.an.index.modes[m].orbits);
    cnt[w] = { all: all.size, plane: onPlane.length, other: all.size - onPlane.length };
  }
  const row = (w) => `<tr><td>${w}</td><td>${cnt[w].all}</td><td>${cnt[w].plane}</td><td>${out[w].u.withGdv}</td><td>${out[w].u.without}</td><td>${cnt[w].other}</td></tr>`;
  const mrows = modes.map(([m, label]) => {
    const r = sc.compareSignatures(out.A[m].sig, out.B[m].sig);
    return `<tr><td>${label}</td><td>${r.gdd.toFixed(4)}</td><td>${r.cosine.toFixed(4)}</td></tr>`;
  }).join("");
  $("scres").innerHTML = `<table><tr><td></td><td>all</td><td>${esc(p)}</td><td>GDV</td><td>no GDV</td><td>other</td></tr>${row("A")}${row("B")}</table>` +
    `<table><tr><td>mode</td><td>GDD</td><td>cosine</td></tr>${mrows}</table>` +
    `<div class="sub">Columns: objects of the selection (all planes), on plane ${esc(p)}, with a GDV (signed), without a GDV (counted, not signed), on other planes (not signed). GDD = GDD agreement, cosine = cosine of log(1 + orbit totals), for 73 (undirected) and 129 (directed) orbits. Signed on plane ${esc(p)}: orbit totals and GDD of the members' GDVs (counted by Odin III on the whole plane graph at export; a cluster here is not recounted on its own subgraph). Objects without a GDV (not on a plane with analytics, or outside its graph) are counted above and left out. Other-plane objects are not signed. The metrics are the code of Odin III graphlets --compare, ported to JS and pinned to it by tests.</div>`;
  return { out, cnt };
}
// graphlet types of a plane and mode, rare first; a click shows the instances (when the exporter wrote them)
function fillAnTypes() {
  const p = $("gtp").value, m = $("gtm").value, rows = S.an.index.planes[p]?.graphlet_types?.[m] ?? [];
  const have = S.man.analytics.instances ?? [];
  const inst = have.includes(`${p}.${m}`);
  $("gttab").innerHTML = "<table><tr><td>type</td><td>nodes</td><td>edges</td><td>count</td></tr>" +
    av.rareFirst(rows).map((r) => r[3] > 0 && inst
      ? `<tr class="gt" data-g="${r[0]}" style="cursor:pointer"><td>G${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`
      : `<tr class="gt0" style="color:#999"><td>G${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`).join("") + "</table>";
  $("gttab").querySelectorAll(".gt").forEach((el) => el.addEventListener("click", () => anInstances(p, m, +el.dataset.g)));
  $("gtinfo").textContent = rows.length ? (inst ? "Click a type to see its instances." : "Counts are from Odin III orbit totals; there is no instance list for this plane and mode in the bundle (too many node sets, or exported without Odin III instances: see the notes above).") : "no graph for this plane";
}
async function anInstances(p, m, g) {
  const have = S.man.analytics.instances ?? [];
  if (!have.includes(`${p}.${m}`)) { $("gtinfo").textContent = `no instance file for ${p} (${m}): this bundle was exported without Odin III graphlet instances`; return; }
  const d = (S.an.inst[`${p}.${m}`] ??= await getJson(`analytics/instances.${p}.${m}.json`));
  const t = d.types[String(g)];
  if (!t) { $("gtinfo").textContent = `instances of G${g} were not exported for ${p} (no instance of it on this plane)`; return; }
  const { colours, count } = av.dsatur(av.conflicts(t.instances, d.edges));
  const cls = av.classNodes(t.instances, colours, count), ids = S.planes[p].ids;
  clearGroups(S.groups);
  cls.forEach((nodes) => nodes.forEach((n, k) => (k ? addToCurrent : addGroup)(S.groups, ids[n])));
  applyGroups();
  $("gtinfo").textContent = `G${g}: ${t.written} of ${t.total} instances` + (t.truncated ? ` (cut at ${t.max}, not all shown)` : "") +
    `; map colouring needs ${count} colour${count === 1 ? "" : "s"}` + (count > 8 ? " (more than 8: colours repeat)" : "") + "; shared nodes are pies.";
}
function buildAnalyticsUi() {
  $("ansec").style.display = "block";
  const ix = S.an.index, ps = anPlanes();
  $("anmeta").textContent = `seed ${ix.seed}; ${ps.length} planes; counted by Odin III at export. ` + (ix.notes.length ? ix.notes.join("; ") : "");
  fillAnOrbits(); fillAnK();
  $("anmode").addEventListener("change", fillAnOrbits);
  $("anorbitgo").addEventListener("click", anOrbitHeat);
  for (const id of ["anfeat", "analg"]) $(id).addEventListener("change", fillAnK);
  $("ancgo").addEventListener("click", anPickClustering);
  $("anlplane").innerHTML = ps.map((p) => `<option>${p}</option>`).join("");
  $("anlplane").addEventListener("change", fillAnList);
  $("ansp").innerHTML = ps.map((p) => `<option>${p}</option>`).join("");
  for (const id of ["ansp", "ansm"]) $(id).addEventListener("change", fillAnSig);
  for (const id of ["ansa", "ansb"]) $(id).addEventListener("change", showAnSim);
  fillAnSig();
  $("scp").innerHTML = ps.map((p) => `<option>${p}</option>`).join("");
  scFill();
  if (ps.length > 1) $("scb").selectedIndex = Math.min(1, $("scb").options.length - 1);
  $("scsnap").addEventListener("click", scSnap);
  $("sccmp").addEventListener("click", scCompare);
  $("scp").addEventListener("change", () => { scFill(); scCompare(); });
  for (const id of ["sca", "scb"]) { $(id).addEventListener("focus", scFill); $(id).addEventListener("change", scCompare); }
  $("gtp").innerHTML = ps.map((p) => `<option>${p}</option>`).join("");
  for (const id of ["gtp", "gtm"]) $(id).addEventListener("change", fillAnTypes);
  fillAnTypes();
  const sil = ps.map((p) => {
    const r = S.an.index.planes[p].clusterings.filter((x) => x.feature === "gdv_u" && x.alg === "kmeans");
    return `${p}: ` + r.map((x) => `k${x.k} ${x.silhouette}`).join(", ");
  });
  $("ansilh").innerHTML = sil.map(esc).join("<br>");
}

// ---- switching activity (Bifrost III power data joined to the planes; v0.7) ----
async function loadActivity() {
  const ent = S.man.activity;
  const srcs = ent.sources || [{ key: ent.source, label: ent.source_label, file: "activity/activity.json" }];
  const data = await getJson(srcs[0].file);
  S.act = { data, exact: false, sources: srcs, key: srcs[0].key, cache: { [srcs[0].key]: data } };
  injectActivity();
}
async function switchActivity(key) {
  const s = S.act.sources.find((x) => x.key === key);
  if (!S.act.cache[key]) S.act.cache[key] = await getJson(s.file);
  S.act.data = S.act.cache[key];
  S.act.key = key;
  const origin = key === "odin3-vectorless" ? "Odin III activity pass" : "Bifrost III";
  for (const n of ["act_p1", "act_td"]) meta(n).source = `${origin}, ${S.act.data.source_label}`;
  injectActivity();
  buildActUi();
  refreshAll();
}
function actValues(a, p) {
  const c = a.coverage[p], n = c.net + c.line + c.link + c.none;
  return n ? `${(100 * (n - c.none) / n).toFixed(0)}% of ${n} have a value` : "empty";
}
function actCompare(a) {
  return (a.compare || []).map((c) => `<div class="sub">Against ${esc(c.other_label)} on the ${c.nets} nets both name: mean absolute difference of P(1) ${c.p1_mae}, of density ${c.density_mae} toggles per cycle.</div>`).join("");
}
function actPicker() {
  const s = S.act.sources;
  if (s.length < 2) return "";
  return `<div class="sub"><b>Activity source:</b> <select id="actsrc" style="width:auto">${s.map((x) => `<option value="${esc(x.key)}"${x.key === S.act.key ? " selected" : ""}>${esc(x.label)}</option>`).join("")}</select> (the default is a testbench if there is one)</div>`;
}
function injectActivity() {
  const d = S.act.data;
  for (const p of S.order) {
    const c = d.planes[p];
    if (!c) continue;
    for (const k of ["p1", "td", "pw"]) {
      const exact = S.act.exact && k !== "pw";
      S.planes[p].metrics[`act_${k}`] = exact ? c[k].map((v, i) => (c.basis[i] === 1 ? v : null)) : c[k];
      delete S.ranges[`act_${k}`];
    }
  }
}
const BASIS_NAME = ["none", "net", "line", "link"];
function actTotals(a) {
  const t = a.totals, mw = (w) => (w === undefined ? "-" : `${(w * 1e3).toPrecision(4)} mW`), row = (k, v) => `<div>${esc(k)}: <b>${esc(v)}</b></div>`;
  const rows = [row("total", mw(t.total_w)), row("dynamic", mw(t.dynamic_w)), row("static (leakage)", mw(t.static_w)), row("clock" + (a.target === "asic" ? " (clock-tree cells, a lower bound)" : ""), mw(t.clock_w))];
  if (t.freq_mhz !== undefined) rows.push(row("frequency", `${t.freq_mhz.toPrecision(4)} MHz`));
  if (t.energy_per_cycle_pj !== undefined) rows.push(row("energy per cycle", `${t.energy_per_cycle_pj.toPrecision(4)} pJ`));
  if (t.vectorless_total_w !== undefined) rows.push(row("vectorless (ACE2) total", mw(t.vectorless_total_w)));
  return rows.join("");
}
function actLines(a) {
  const rows = a.lines.slice(0, 30).map((r, k) => `<div class="actl" data-k="${k}" style="cursor:pointer;font-size:11px">${esc(r[0])}:${r[1]} &middot; ${r[2]} nets or cells &middot; P(1) ${r[3] === null ? "-" : r[3].toFixed(3)} &middot; ${r[4] === null ? "-" : r[4].toPrecision(3)} toggles/cycle &middot; ${r[5] === null ? "-" : r[5].toPrecision(3)} uW</div>`);
  return `<div class="sub">${a.line_power === "model" ? "power per line is a model (see below)" : a.line_power === "none" ? "no power per line for this source (activity per line is shown)" : a.line_power === "not available" ? "power per line: not available for this design (activity per line is shown)" : "power per line is per instance"}; top ${rows.length} lines${a.line_power === "not available" || a.line_power === "none" ? "" : " by power, then"} by activity</div>${rows.join("")}`;
}
function buildActUi() {
  const el = $("actbody"), a = S.act?.data;
  if (!a) {
    el.innerHTML = '<div class="sub">No switching-activity data for this page. Nothing is estimated: a design needs a Bifrost III power run (ACE2 vectorless or a testbench) or an Odin III activity file, and a silicon page needs a gate-level run of its own netlist (only mmuart, verilog_cordic_core and wb_lcd have one).</div>';
    return;
  }
  const cov = S.order.map((p) => { const c = a.coverage[p]; return `<div style="font-size:11px">${p}: ${c.net} net, ${c.line} line, ${c.link} link, ${c.none} none (${actValues(a, p)})</div>`; }).join("");
  const tb = a.testbench ? ` Testbench ${esc(a.testbench)}${a.tb_pass ? " (prints PASS)" : ""}, ${a.cycles} cycles of ${esc(a.clock)}${a.start_state ? `, latches start at ${esc(a.start_state)}` : ""}.` : "";
  const mf = typeof a.matched_fraction === "number" ? ` ${a.source === "odin3-vectorless" ? "Objects of the LUT plane named in the file" : "Activity matched on the nets"}: ${(100 * a.matched_fraction).toFixed(1)}%.` : "";
  const ps = a.power_source ? `<div class="sub">Power below is Bifrost's, computed from its own source (${esc(a.power_source)}); it is not recomputed from this activity.</div>` : "";
  el.innerHTML = actPicker() + `<div class="sub"><b>Activity source:</b> ${esc(a.source_label)}.${tb}${mf}</div>` + actCompare(a) +
    `<div class="sub">${esc(Object.values(a.tool).join("; "))}</div>${ps}${Object.keys(a.totals).length ? actTotals(a) : ""}` +
    `<div class="sub"><button id="actp1">colour: static probability</button> <button id="acttd">colour: transition density</button> <button id="actpw">colour: power</button></div>` +
    `<label class="sub"><input type="checkbox" id="actexact"> exact name matches only (grey elsewhere)</label>` +
    `<h2>Join per plane (objects by basis)</h2>${cov}` +
    `<div class="sub">net = the object's own name is the net Bifrost measured; line = mean over the nets on its HDL line; link = mean of linked objects; none = grey.</div>` +
    `<h2>Per HDL line (click to select)</h2>${actLines(a)}` +
    a.caveats.map((c) => `<div class="sub">${esc(c)}</div>`).join("") + (a.warnings.length ? `<div class="sub">Tool warnings: ${esc(a.warnings.join("; "))}</div>` : "");
  for (const k of ["p1", "td", "pw"]) {
    $(`act${k}`).addEventListener("click", () => { S.colour = `act_${k}`; $("colour").value = S.colour; refreshAll(); });
  }
  if ($("actsrc")) $("actsrc").addEventListener("change", (e) => switchActivity(e.target.value));
  $("actexact").addEventListener("change", (e) => { S.act.exact = e.target.checked; injectActivity(); refreshAll(); });
  el.querySelectorAll(".actl").forEach((tr) => tr.addEventListener("click", () => { const r = a.lines[+tr.dataset.k]; if (r[1] <= 0) return; selectLines(r[0], r[1], r[1]); if (!S.mode.n) { $("enclosing").checked = true; selectLines(r[0], r[1], r[1]); } }));
}

function buildUi() {
  fillMetricSelects();
  buildActUi();
  if (S.an) buildAnalyticsUi();
  $("colour").addEventListener("change", (e) => { S.colour = e.target.value; refreshAll(); });
  $("size").addEventListener("change", (e) => { S.size = e.target.value; refreshAll(); });
  $("ffmode").addEventListener("change", (e) => { S.ff = e.target.value; refreshAll(); });
  $("bits").addEventListener("change", (e) => { S.bits = e.target.checked; refreshAll(); });
  $("busfilter").addEventListener("input", (e) => { S.busFilter = e.target.value; fillBusList(); });
  $("height").addEventListener("change", (e) => { S.height = e.target.value; refreshAll(); });
  $("fade").addEventListener("change", (e) => { S.fade = e.target.value; refreshAll(); });
  $("anchor").innerHTML = S.man.anchors.map((a) => `<option${a === S.anchor ? " selected" : ""}>${a}</option>`).join("");
  $("anchor").addEventListener("change", (e) => changeAnchor(e.target.value));
  $("addexpr").addEventListener("click", () => {
    try {
      addExpr($("exname").value.trim(), $("extext").value, $("exscale").value);
      S.colour = $("exname").value.trim(); $("colour").value = S.colour; refreshAll();
      $("exmsg").className = "sub"; $("exmsg").textContent = `added ${S.colour}`;
    } catch (err) { $("exmsg").className = "err"; $("exmsg").textContent = err.message; }
  });
  $("addagg").addEventListener("click", () => {
    try {
      const n = addAgg($("aggmetric").value, $("aggdir").value, $("aggop").value);
      S.colour = n; $("colour").value = n; refreshAll();
      $("exmsg").className = "sub"; $("exmsg").textContent = `added ${n}`;
    } catch (err) { $("exmsg").className = "err"; $("exmsg").textContent = err.message; }
  });
  S.hops = 1; S.edgeMode = "";
  $("dplane").innerHTML = S.order.map((p) => `<option value="${p}"${p === "lut" ? " selected" : ""}>${p}</option>`).join("");
  $("brushplane").innerHTML = S.order.map((p) => `<option value="${p}"${p === "placed" ? " selected" : ""}>${p}</option>`).join("");
  $("viewmode").innerHTML = ["stack", ...S.order].map((p) => `<option value="${p}">${p === "stack" ? "3D stack" : "2D: " + p}</option>`).join("");
  $("viewmode").addEventListener("change", (e) => setView(e.target.value));
  $("dgo").addEventListener("click", discover);
  $("grouping").addEventListener("change", (e) => setGroupMode(e.target.value));
  $("edgemode").addEventListener("change", async (e) => { S.edgeMode = e.target.value; if (S.edgeMode) await ensureEdges(); drawEdges(); });
  $("hops").addEventListener("change", (e) => { S.hops = Number(e.target.value); drawEdges(); });
  const pairs = S.order.slice(0, -1).map((p, k) => `<option value="${k}">${p} to ${S.order[k + 1]}</option>`).join("");
  $("morphpair").innerHTML = pairs;
  const setMorph = () => { const k = Number($("morphpair").value); S.morph = { a: S.order[k], b: S.order[k + 1], m: Number($("morph").value) }; refreshAll(); };
  $("morph").addEventListener("input", setMorph);
  $("morphpair").addEventListener("change", () => { $("morph").value = "0"; setMorph(); });
  $("rotate").addEventListener("change", (e) => { controls.autoRotate = e.target.checked; });
  controls.autoRotate = $("rotate").checked;
  $("gap").addEventListener("input", (e) => { S.gap = Number(e.target.value); layout(); resetCamera(); });
  $("reset").addEventListener("click", resetCamera);
  $("clear").addEventListener("click", clearSel);
  const baseKey = (p) => (isGraph(p) ? Object.keys(GKEYS).find((k) => GKEYS[k] === p) : String(baseOrder().indexOf(p) + 1));
  $("planes").innerHTML = S.order.map((p) =>
    `<div class="prow"><input type="checkbox" data-p="${p}"${S.vis[p] === false ? "" : " checked"} style="width:auto"><b style="color:var(--fg);flex:0 0 52px">${baseKey(p)} ${p}</b>` +
    `<button data-f="${p}">focus</button><button data-s="${p}">solo</button></div>` +
    `<label class="row">opacity<input type="range" data-o="${p}" min="0" max="1" step="0.05" value="0.12"></label>`).join("");
  $("planes").querySelectorAll("input[data-p]").forEach((c) => c.addEventListener("change", () => {
    S.vis[c.dataset.p] = c.checked; S.solo = null;
    if (isGraph(c.dataset.p)) { layout(); resetCamera(); }
    applyVisibility();
    syncGraphBoxes();
  }));
  $("planes").querySelectorAll("button[data-f]").forEach((b) => b.addEventListener("click", () => focusPlane(b.dataset.f)));
  $("planes").querySelectorAll("button[data-s]").forEach((b) => b.addEventListener("click", () => soloPlane(b.dataset.s)));
  $("planes").querySelectorAll("input[data-o]").forEach((c) => c.addEventListener("input", () => {
    quads[c.dataset.o].q.material.opacity = Number(c.value);
  }));
  $("depthpreset").addEventListener("click", () => setColour("logic_level"));
  buildGraphUi();
  buildPathsUi();
  buildCircuitUi();
  document.querySelectorAll("button[data-tgl]").forEach((b) => b.addEventListener("click", () => togglePanel(b.dataset.tgl)));
  applyPanels();
  document.addEventListener("keydown", (e) => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") { clearSel(); return; }
    if (e.key === "?") { window.open($("helplink").href, "_blank", "noopener"); return; }
    const pk = pl.panelForKey(e.key);
    if (pk) { togglePanel(pk); return; }
    if (e.key === "0") focusPlane(null);
    else if (GKEYS[e.key]) showGraph(GKEYS[e.key]);
    else if (/^[1-9]$/.test(e.key) && baseOrder()[Number(e.key) - 1]) focusPlane(baseOrder()[Number(e.key) - 1]);
  });
  $("view").addEventListener("wheel", wheelZoom, { passive: false });
  $("title").textContent = S.man.benchmark;
  $("subtitle").textContent = `${S.man.flow} flow, top ${S.man.top}; planes ${S.order.join(" > ")}`;
  if (S.man.note) $("subtitle").textContent += ` Note: ${S.man.note}`;
  if (S.man.link_cap) $("subtitle").textContent += ` Link cap: ${S.man.link_cap.objects} provenance objects have up to ${S.man.link_cap.max_links} links to HDL constructs; the first ${S.man.link_cap.cap} of each are kept (the full count is in hdl_links).`;
  const c = S.man.counts;
  $("status").textContent = `${S.order.map((p) => `${p} ${c[p]}`).join(", ")}; ${S.man.links} links; ` +
    `${S.man.unanchored} placed by fallback; not in this bundle: ${S.man.missing_planes.join(", ")}`;
  const cv = $("view"), tip = $("tip"), box = $("brush");
  let down = null, brushing = false;
  cv.addEventListener("pointerdown", (e) => {
    down = [e.clientX, e.clientY];
    brushing = e.shiftKey;
    if (brushing) { controls.enabled = false; box.style.display = "block"; }
  });
  cv.addEventListener("pointerup", (e) => {
    controls.enabled = true; box.style.display = "none";
    if (!down) return;
    if (brushing) {
      brushing = false;
      if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) <= 4) { const h = pick(e); if (h?.id) groupClick(h.id, e.altKey); return; }
      brushSelect(down[0], down[1], e.clientX, e.clientY);
      return;
    }
    if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const h = pick(e);
    if (h?.blob) {
      if (S.group.expanded.has(h.blob.key)) S.group.expanded.delete(h.blob.key); else S.group.expanded.add(h.blob.key);
      refreshAll();
    } else if (h?.id) select(h.id); else clearSel();
  });
  cv.addEventListener("pointermove", (e) => {
    if (brushing && down) {
      const r = $("stage").getBoundingClientRect();
      Object.assign(box.style, { left: Math.min(down[0], e.clientX) - r.left + "px", top: Math.min(down[1], e.clientY) - r.top + "px",
        width: Math.abs(e.clientX - down[0]) + "px", height: Math.abs(e.clientY - down[1]) + "px" });
      return;
    }
    const h = pick(e), r = $("stage").getBoundingClientRect();
    const mx = h?.id && S.tier ? S.tierMix?.get(h.id) : null;
    const text = h?.id ? h.id + (mx ? "  " + mixText(mx, S.byId.get(h.id).plane === "clb" ? "LUTs" : "cells") : "") : (h?.blob ? `${h.plane}: ${h.blob.key} (${h.blob.members.length} objects, click to expand)` : null);
    tip.style.display = text ? "block" : "none";
    if (text) { tip.textContent = text; tip.style.left = e.clientX - r.left + 12 + "px"; tip.style.top = e.clientY - r.top + 12 + "px"; }
  });
  setupTouch(cv, () => { down = null; }); // after the handlers above, so its pointerdown runs last
  setupOrderNav();
}

// Deep links: the URL query (see urlstate.js) sets the state once the bundle is loaded. Bad names are ignored.
async function applyUrl(u) {
  if (u.panels) { panels = Object.fromEntries(pl.PANELS.map((k) => [k, u.panels.includes(k)])); applyPanels(); }
  if (u.rotate === false) { $("rotate").checked = false; controls.autoRotate = false; }
  for (const g of u.graphs ?? []) if (S.order.includes(g) && S.vis[g] === false) showGraph(g, true);
  if (u.anchor && S.man.anchors.includes(u.anchor)) { $("anchor").value = u.anchor; await changeAnchor(u.anchor); }
  if (u.csrc && S.cl?.order.includes(u.csrc)) { $("csrc").value = u.csrc; $("csrc").dispatchEvent(new Event("change")); }
  if (u.compare && S.cl?.order.includes(u.compare)) { $("ccompare").checked = true; $("csrc2").value = u.compare; await showCircuit(); }
  if (u.scoap && meta(u.scoap.m)) setColour(scoapColour(u.scoap.m, u.scoap.op));
  if (u.colour) setColour(u.colour);
  for (const [k, id, key] of [["size", "size", "size"], ["height", "height", "height"], ["fade", "fade", "fade"]]) {
    if (u[k] && meta(u[k])) { S[key] = u[k]; $(id).value = u[k]; }
  }
  if (u.ff) { S.ff = u.ff; $("ffmode").value = u.ff; }
  if (u.bits) { S.bits = true; $("bits").checked = true; }
  refreshAll();
  if (u.sel?.kind === "line") {
    const f = u.sel.file && S.texts[u.sel.file] ? u.sel.file : S.srcFile;
    if (f !== S.srcFile) showFile(f);
    $("enclosing").checked = !!u.enclosing;
    selectLines(f, u.sel.a, u.sel.b);
    if (rows[u.sel.a]) $("srclines").scrollTop = Math.max(0, rows[u.sel.a].offsetTop - $("srclines").clientHeight / 3);
  } else if (u.sel?.kind === "obj" && S.byId.has(u.sel.id)) select(u.sel.id);
  else if (u.sel?.kind === "bus" && S.busIndex.has(u.sel.id)) selectBus(u.sel.id);
  else if (u.sel?.kind === "path") { const i = S.paths.findIndex((x) => x.n === u.sel.n); if (i >= 0) showPath(i); }
  if (u.grp) for (const g of u.grp) g.filter((id) => S.byId.has(id)).forEach((id, k) => groupClick(id, k > 0));
  if (u.cell && S.cl) await selectCell(S.csrc, u.cell.which, u.cell.i, u.cell.j);
  if (u.cone) { $("pathsrc").value = "cone"; showPathPanel(); S.coneOn = true; $("conedir").value = u.cone.dir; $("conedepth").value = String(u.cone.depth); await updateCone(); markLines(); }
  if (u.view && (u.view === "stack" || S.order.includes(u.view))) setView(u.view);
  if (u.solo && S.order.includes(u.solo)) soloPlane(u.solo);
  if (u.plane && S.order.includes(u.plane)) focusPlane(u.plane);
  if (u.zoom) { const off = camera.position.clone().sub(controls.target).divideScalar(u.zoom); camera.position.copy(controls.target).add(off); controls.update(); }
}

async function main() {
  await loadBundle();
  buildScene();
  buildUi();
  new ResizeObserver(resize).observe($("stage"));
  resize();
  buildSource();
  applyVisibility();
  refreshAll();
  const loop = () => { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  loop();
  try { await applyUrl(parseQuery(location.search)); } catch (e) { console.error("deep link:", e); }
  document.body.dataset.ready = "1";
  window.__o3viz = { S, switchActivity, scCompare, scSnap, scFill, groupClick, anOrbitHeat, anPickClustering, anInstances, anClusterGroup, fillAnList, setBits: (on) => { S.bits = on; $("bits").checked = on; refreshAll(); }, selectEdge, showGraph, scoapColour, drawGraphs, khopEdges, changeAnchor, selectCell, showCircuit, characterize, setCluster: (k) => { $("csrc").value = k; $("csrc").dispatchEvent(new Event("change")); }, setCompare: (on, k) => { $("ccompare").checked = on; if (k) $("csrc2").value = k; showCircuit(); }, togglePanel, panelState: () => ({ ...panels }), select, selectBus, tierCounts, setFF: (m) => { S.ff = m; $("ffmode").value = m; refreshAll(); }, selectLines, planeCounts, coverage, focusPlane, soloPlane, showPath, updateCone, markLines, setCone: async (dir, depth) => { $("pathsrc").value = "cone"; showPathPanel(); S.coneOn = true; $("conedir").value = dir; $("conedepth").value = String(depth); await updateCone(); markLines(); }, marksOf: () => Object.fromEntries([...marks].map(([f, m]) => [f, Object.fromEntries(m)])), cam: () => ({ target: controls.target.toArray(), pos: camera.position.toArray() }), wheelAt: (x, y, dy) => wheelZoom({ preventDefault() {}, clientX: x, clientY: y, deltaY: dy, deltaMode: 0 }), discover, setView, setGroupMode, discoverMatrix, brushAll: (p) => { S.brush = new Set(S.planes[p].ids.slice(0, 30)); S.core = new Set(); refreshAll(); },
    setEdges: async (m, h) => { S.edgeMode = m; S.hops = h ?? 1; await ensureEdges(); drawEdges(); }, setMorph: (a, b, m) => { S.morph = { a, b, m }; refreshAll(); }, addExpr, addAgg, setHeight: (n) => { S.height = n; $("height").value = n; refreshAll(); },
    setAnchor: async (n) => { $("anchor").value = n; $("anchor").dispatchEvent(new Event("change")); }, setColour,
    setSize: (n) => { S.size = n; $("size").value = n; refreshAll(); }, stop: () => { controls.autoRotate = false; } };
}
window.addEventListener("error", (e) => { $("status").className = "err"; $("status").textContent = String(e.message); });
main().catch((e) => { $("subtitle").textContent = "failed to load"; $("status").className = "err"; $("status").textContent = String(e); console.error(e); });
