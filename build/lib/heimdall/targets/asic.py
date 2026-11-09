"""ASIC target: an Odin III silicon-flow run (OpenROAD, sky130_fd_sc_hd) as a bundle.

Planes (spec 2026-11-05 section 2), top to bottom: `hdl`, `stdcell`, `die`, `route`.
- `stdcell`: one row per mapped standard cell (prov step `map`, stage `gates`): `type` is
  the library cell name; metrics area, drive, pin count, fan-in of HDL spans.
- `die`: every placed instance of the final DEF (logic, tap, clock-tree, repair and hold
  buffers) with real coordinates in micrometres (`x_um`, `y_um`, orientation, row). The die,
  core and rows are in the manifest `coord` header (kind `um`). Fill cells are not planes
  (their count is in the notes).
- `route` (optional): one object per routed net, metrics wire length, vias, layers,
  half-perimeter wire length; the polylines per layer are in `routes.json` (longest nets
  first, capped).
- Links `hdl` -> `stdcell` (cone, from the map step), `stdcell` -> `die` (name, from the
  place step) and `die` -> `route` (pin). The `recover` step (Magic extraction, Netgen LVS,
  the name-free join) gives each die object its join confidence, the metric `recover_conf`
  (4 exact .. 0 ambiguous, -1 not joined). An object whose chain leaves the HDL (tap,
  buffers) is labelled by its `origin` (`physical:...`).
The silicon prov has no `cell` plane (gates link to HDL statements directly), so none is
written.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from heimdall import anchors, anchorset, export, targets
from heimdall.targets import ASIC_PLANES

PLANES = ASIC_PLANES
ASIC_ORDER = ("hdl", "stdcell", "die", "route")
STDCELL_COLUMNS = ("id", "kind", "type", "origin", "name", "area_um2", "drive", "pins")
DIE_COLUMNS = ("id", "kind", "type", "origin", "name", "x_um", "y_um", "orient", "row")
ROUTE_SEG_CAP = 250_000  # polyline segments kept in routes.json; longest nets first
FLIPPED = {"FS", "FN", "MX", "MY", "S", "R180", "MX90", "MY90"}  # not R0; only for the metric

ASIC_METRICS: list[dict[str, Any]] = [
    {
        "name": "cells_below",
        "unit": "std cells",
        "planes": ["hdl"],
        "scale": "seq",
        "measurer": "heimdall.targets.asic: standard cells whose cone chain reaches the statement",
        "source": "odin3 prov step map",
    },
    {
        "name": "area_um2",
        "unit": "um2",
        "planes": ["stdcell", "die"],
        "scale": "seq",
        "measurer": "LEF SIZE width x height of the library cell",
        "source": "sky130_fd_sc_hd.lef",
    },
    {
        "name": "drive",
        "unit": "drive strength",
        "planes": ["stdcell", "die"],
        "scale": "seq",
        "measurer": "the _N suffix of the library cell name (die: after repair resizing)",
        "source": "cell name",
    },
    {
        "name": "pins",
        "unit": "signal pins",
        "planes": ["stdcell"],
        "scale": "seq",
        "measurer": "PIN entries with USE SIGNAL in the LEF macro",
        "source": "sky130_fd_sc_hd.lef",
    },
    {
        "name": "is_ff",
        "unit": "1 = flip-flop",
        "planes": ["stdcell", "die"],
        "scale": "seq",
        "measurer": "library cell name contains __df, __dlx or __edf",
        "source": "cell name",
    },
    {
        "name": "x_um",
        "unit": "um",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "DEF PLACED point (lower left of the cell), in um",
        "source": "OpenROAD route.def",
    },
    {
        "name": "y_um",
        "unit": "um",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "DEF PLACED point (lower left of the cell), in um",
        "source": "OpenROAD route.def",
    },
    {
        "name": "row",
        "unit": "row number",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "index of the DEF ROW whose y equals the cell y (0 = bottom)",
        "source": "OpenROAD route.def",
    },
    {
        "name": "flipped",
        "unit": "1 = not R0",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "DEF orientation other than N",
        "source": "OpenROAD route.def",
    },
    {
        "name": "legal_shift_um",
        "unit": "um",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "Manhattan move from global placement to the final legal place",
        "source": "s04_global_place.csv, route.def",
    },
    {
        "name": "recover_conf",
        "unit": "4 exact .. 0 ambiguous, -1 not joined",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "confidence of the name-free join (cell type and location) of the recover step",
        "source": "odin3 prov step recover",
    },
    {
        "name": "nets",
        "unit": "signal nets",
        "planes": ["die"],
        "scale": "seq",
        "measurer": "nets of the DEF NETS section with a pin on the instance",
        "source": "OpenROAD route.def",
    },
    {
        "name": "wire_um",
        "unit": "um",
        "planes": ["route"],
        "scale": "seq",
        "measurer": "sum of the Manhattan length of every routed segment of the net",
        "source": "OpenROAD route.def",
    },
    {
        "name": "vias",
        "unit": "vias",
        "planes": ["route"],
        "scale": "seq",
        "measurer": "via placements in the routed wiring of the net",
        "source": "OpenROAD route.def",
    },
    {
        "name": "layers",
        "unit": "metal layers",
        "planes": ["route"],
        "scale": "seq",
        "measurer": "distinct layers with a wire segment of the net",
        "source": "OpenROAD route.def",
    },
    {
        "name": "hpwl_um",
        "unit": "um",
        "planes": ["route"],
        "scale": "seq",
        "measurer": "half-perimeter of the box around the cells on the net (lower-left points)",
        "source": "OpenROAD route.def",
    },
    {
        "name": "fanout",
        "unit": "pins",
        "planes": ["route"],
        "scale": "seq",
        "measurer": "instance pins on the net",
        "source": "OpenROAD route.def",
    },
]
for _m in ASIC_METRICS:
    _m["target"] = "asic"


# ---- readers ----------------------------------------------------------------------------------


@dataclass
class Comp:
    name: str
    master: str
    x: int
    y: int
    orient: str
    status: str


@dataclass
class Net:
    name: str
    pins: list[tuple[str, str]] = field(default_factory=list)
    segs: list[tuple[str, list[tuple[int, int]]]] = field(default_factory=list)
    vias: int = 0


@dataclass
class Def:
    units: int = 1000
    die: tuple[int, int, int, int] = (0, 0, 0, 0)
    rows: list[tuple[str, int, int, str, int, int]] = field(
        default_factory=list
    )  # name x y orient n step
    comps: list[Comp] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)


_COMP = re.compile(
    r"-\s+(\S+)\s+(\S+)(?:\s+\+\s+SOURCE\s+\w+)?\s+\+\s+(PLACED|FIXED|COVER)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+(\w+)"
)
_ROW = re.compile(
    r"ROW\s+(\S+)\s+\S+\s+(-?\d+)\s+(-?\d+)\s+(\w+)\s+DO\s+(\d+)\s+BY\s+\d+\s+STEP\s+(\d+)"
)
_PT = re.compile(r"\(\s*(\S+)\s+(\S+)(?:\s+\S+)?\s*\)")
_PIN = re.compile(r"\(\s*(\S+)\s+(\S+)\s*\)")
_RECT = re.compile(r"\bRECT\s*\([^)]*\)")


def _statements(lines: Iterator[str]) -> Iterator[str]:
    cur: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        cur.append(s)
        if s.endswith(";") or (len(cur) == 1 and s.startswith("END ")):
            yield " ".join(cur)
            cur = []


def _route_pieces(text: str) -> tuple[list[tuple[str, list[tuple[int, int]]]], int]:
    """Wire segments (layer, points) and via count of the `+ ROUTED ... NEW ...` text of a net."""
    segs: list[tuple[str, list[tuple[int, int]]]] = []
    vias = 0
    text = _RECT.sub("", text.rstrip(" ;"))
    for piece in re.split(r"\bNEW\b|\+\s*ROUTED", text):
        tok = piece.split()
        if not tok or tok[0] == "(":
            continue
        layer = tok[0]
        pts: list[tuple[int, int]] = []
        px = py = 0
        for a, b in _PT.findall(piece):
            x = px if a == "*" else int(a)
            y = py if b == "*" else int(b)
            pts.append((x, y))
            px, py = x, y
        after = piece[piece.rfind(")") + 1 :].split() if ")" in piece else []
        if len(pts) >= 2:
            segs.append((layer, pts))
        elif len(pts) == 1 and after:
            vias += 1
    return segs, vias


def read_def(path: Path, want_nets: bool = True) -> Def:
    """The parts of an OpenROAD DEF (placed, routed) that the viewer needs."""
    d = Def()
    section = ""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for st in _statements(fh):
            if st.startswith("UNITS"):
                d.units = int(st.split()[3])
            elif st.startswith("DIEAREA"):
                nums = [int(n) for n in re.findall(r"-?\d+", st)]
                d.die = (nums[0], nums[1], nums[2], nums[3])
            elif st.startswith("ROW"):
                m = _ROW.match(st)
                if m:
                    d.rows.append((m[1], int(m[2]), int(m[3]), m[4], int(m[5]), int(m[6])))
            elif re.match(r"(COMPONENTS|NETS|PINS|SPECIALNETS|VIAS)\s+\d+", st):
                section = st.split()[0]
            elif st.startswith("END "):
                section = ""
            elif section == "COMPONENTS":
                m = _COMP.match(st)
                if m:
                    d.comps.append(Comp(m[1], m[2], int(m[4]), int(m[5]), m[6], m[3]))
            elif section == "NETS" and want_nets and st.startswith("-"):
                head, _, route = st.partition("+ ROUTED")
                name = head[1:].split()[0]
                body = head.split(" + ")[0]
                net = Net(
                    name, [(a, b) for a, b in _PIN.findall(body[body.find(name) + len(name) :])]
                )
                if route:
                    net.segs, net.vias = _route_pieces(route)
                d.nets.append(net)
    return d


@dataclass
class Macro:
    w: float = 0.0
    h: float = 0.0
    pins: int = 0
    outs: set[str] = field(default_factory=set)  # output pin names (LEF DIRECTION OUTPUT)


def read_global(path: Path) -> dict[str, tuple[int, int]]:
    """Instance -> (x, y) in DEF units after global placement (before legalisation): the
    `s04_global_place.csv` that the flow dumps (columns inst,master,x,y,orient,status,step)."""
    out: dict[str, tuple[int, int]] = {}
    if not path.is_file():
        return out
    for ln in path.read_text(encoding="utf-8").splitlines()[1:]:
        f = ln.split(",")
        if len(f) >= 4:
            out[f[0]] = (int(f[2]), int(f[3]))
    return out


def read_lef(path: Path | None) -> dict[str, Macro]:
    """MACRO name -> size (um) and signal pin count from a LEF file."""
    out: dict[str, Macro] = {}
    if path is None or not path.is_file():
        return out
    cur: Macro | None = None
    pin = False
    pin_name = ""
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = ln.split()
        if not t:
            continue
        if t[0] == "MACRO":
            cur = out.setdefault(t[1], Macro())
        elif cur is not None and t[0] == "SIZE" and len(t) >= 4:
            cur.w, cur.h = float(t[1]), float(t[3])
        elif cur is not None and t[0] == "PIN" and len(t) >= 2:
            pin = True
            pin_name = t[1]
        elif cur is not None and t[0] == "DIRECTION" and len(t) >= 2 and t[1] == "OUTPUT":
            cur.outs.add(pin_name)
        elif cur is not None and pin and t[0] == "USE":
            if t[1] == "SIGNAL":
                cur.pins += 1
            pin = False
        elif t[0] == "END" and len(t) == 2 and t[1] in out:
            cur, pin = None, False
    return out


OUT_PINS = {"X", "Y", "Q", "Q_N", "SUM", "COUT", "HI", "LO", "GCLK", "Z", "ZN"}


def net_edges(df: Def, macros: dict[str, Macro], names: set[str]) -> list[tuple[str, str]]:
    """(driver instance, sink instance) of every DEF net, one pair per distinct sink. A driver pin
    is an
    output pin of the LEF macro (else a pin named like a sky130 output); PIN (ports) are skipped."""
    master = {c.name: c.master for c in df.comps}
    out: list[tuple[str, str]] = []
    for net in df.nets:
        drv: list[str] = []
        snk: list[str] = []
        for inst, pin in net.pins:
            if inst not in names or inst not in master:
                continue
            m = macros.get(master[inst])
            is_out = pin in m.outs if m is not None and m.outs else pin in OUT_PINS
            (drv if is_out else snk).append(inst)
        out.extend((d, s) for d in drv for s in sorted(set(snk)) if s != d)
    return out


# ---- helpers ----------------------------------------------------------------------------------

_SPAN = re.compile(r"(\d+)\.(\d+)-(\d+)\.(\d+)")


def span_key(span: str) -> tuple[int, int, int, int] | None:
    m = _SPAN.fullmatch(span)
    return (int(m[1]), int(m[2]), int(m[3]), int(m[4])) if m else None


def nest_parents(objs: list[dict[str, Any]]) -> dict[str, str]:
    """child -> parent HDL statement: the smallest enclosing span in the same file."""
    by_file: dict[str, list[tuple[tuple[int, int, int, int], str]]] = {}
    for o in objs:
        for s in o.get("src", [])[:1]:
            k = span_key(s["span"])
            if k:
                by_file.setdefault(s["file"], []).append((k, o["id"]))
    parent: dict[str, str] = {}
    for items in by_file.values():
        items.sort(key=lambda it: (it[0][0], it[0][1], -it[0][2], -it[0][3], it[1]))
        stack: list[tuple[tuple[int, int, int, int], str]] = []
        for k, oid in items:
            while stack and (stack[-1][0][2], stack[-1][0][3]) < (k[2], k[3]):
                stack.pop()
            if stack and stack[-1][0] != k:
                parent[oid] = stack[-1][1]
            stack.append((k, oid))
    return parent


def drive_of(master: str) -> float | None:
    m = re.search(r"_(\d+)$", master)
    return float(m[1]) if m else None


def is_ff(master: str) -> bool:
    return any(t in master for t in ("__df", "__dlx", "__edf", "__sdf"))


def read_objs(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                out.append(json.loads(ln))
    return out


def find_def(flow: Path) -> Path:
    for cand in (flow / "or" / "route.def", flow / "route.def"):
        if cand.is_file():
            return cand
    raise export.ExportError(f"no or/route.def in {flow}: need a finished silicon flow run")


def _step_file(prov: Path, stem: str) -> Path | None:
    hits = sorted(prov.glob(f"[0-9][0-9]-{stem}.objects.jsonl"))
    return hits[0] if hits else None


def default_lef() -> Path | None:
    """The sky130_fd_sc_hd LEF of the workspace PDK, when one is installed (None otherwise)."""
    import os

    roots = [Path(os.environ["PDK_ROOT"])] if os.environ.get("PDK_ROOT") else []
    roots += [Path.home() / "odin3-ws" / "work" / "tools" / "pdk"]
    for r in roots:
        hits = sorted(r.glob("**/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"))
        if hits:
            return hits[0]
    return None


# ---- the planes ---------------------------------------------------------------------------------


def build_asic_planes(
    flow: Path, lef: Path | None
) -> tuple[
    dict[str, export.Plane],
    list[tuple[str, str, str, str]],
    dict[str, str],
    dict[str, anchors.Pos],
    dict[str, Any],
]:
    """Planes, links (upper, lower, kind, confidence), HDL parents, positions and meta."""
    prov = flow / "prov"
    if not (prov / "index.json").is_file():
        raise export.ExportError(f"no prov/index.json in {flow}")
    index = json.loads((prov / "index.json").read_text(encoding="utf-8"))
    macros = read_lef(lef)
    df = read_def(find_def(flow))
    u = float(df.units)

    hdl_objs = read_objs(_step_file(prov, "read") or prov / "missing")
    gate_objs = read_objs(_step_file(prov, "map") or prov / "missing")
    place_objs = {o["name"]: o for o in read_objs(_step_file(prov, "place") or prov / "missing")}
    rec_file = _step_file(prov, "recover")
    recovered: dict[str, str] = {}
    if rec_file:
        for o in read_objs(rec_file):
            jc = next(
                (lk["confidence"] for lk in o["links"] if lk["kind"] == "location_match"), None
            )
            recovered[o["name"]] = jc if o["attrs"].get("join") == "matched" and jc else ""

    links: list[tuple[str, str, str, str]] = []
    hdl = export.Plane("hdl")
    parent = nest_parents(hdl_objs)
    for o in hdl_objs:
        hdl.add(
            o["id"],
            o["kind"],
            o.get("attrs", {}).get("level", o["kind"]),
            o["origin"],
            o["name"],
            export.src_of(o),
        )
    hdl_ids = set(hdl.ids)
    depth: dict[str, float] = {}
    kids: dict[str, float] = {}
    for oid in hdl.ids:
        d, cur = 0, oid
        while cur in parent and d < 10_000:
            cur = parent[cur]
            d += 1
        depth[oid] = float(d)
        if oid in parent:
            kids[parent[oid]] = kids.get(parent[oid], 0.0) + 1
    hdl.set_metric("depth", depth)
    hdl.set_metric("children", {i: kids.get(i, 0.0) for i in hdl.ids})
    hdl.set_metric(
        "span_lines",
        {
            i: v
            for i, s in zip(hdl.ids, hdl.src, strict=True)
            if s and (v := export.span_lines(s[0][1])) is not None
        },
    )

    std = export.Plane("stdcell")
    below: dict[str, int] = {}
    spans: dict[str, float] = {}
    composed = False
    ir_hdl: dict[str, list[str]] = {}
    if any(lk["to"].startswith("ir:") for o in gate_objs[:50] for lk in o["links"]):
        # an older prov: gates link to ir cells, those to HDL statements (fine): compose the chain
        for o in read_objs(_step_file(prov, "elab") or prov / "missing"):
            ir_hdl[o["id"]] = [lk["to"] for lk in o["links"] if lk["kind"] == "fine"]
    for o in gate_objs:
        master = o.get("type", "")
        std.add(o["id"], "cell", master, o["origin"], o["name"], export.src_of(o))
        mac = macros.get(master)
        spans[o["id"]] = float(len(o["links"]))
        seen: set[str] = set()
        for lk in o["links"]:
            targets_ = [(lk["to"], lk["confidence"])]
            if lk["to"].startswith("ir:"):
                targets_ = [(h, lk["confidence"]) for h in ir_hdl.get(lk["to"], ())]
                composed = composed or bool(targets_)
            for h, hconf in targets_:
                if h in hdl_ids and h not in seen:
                    seen.add(h)
                    links.append((h, o["id"], lk["kind"], hconf))
                    below[h] = below.get(h, 0) + 1
    hdl.set_metric("cells_below", {i: float(below.get(i, 0)) for i in hdl.ids})
    std_by_name = dict(zip(std.name, std.ids, strict=True))
    std_set = set(std.ids)
    std.set_metric(
        "area_um2",
        {
            i: macros[t].w * macros[t].h
            for i, t in zip(std.ids, std.type, strict=True)
            if t in macros
        },
    )
    std.set_metric(
        "drive",
        {i: v for i, t in zip(std.ids, std.type, strict=True) if (v := drive_of(t)) is not None},
    )
    std.set_metric(
        "pins",
        {i: float(macros[t].pins) for i, t in zip(std.ids, std.type, strict=True) if t in macros},
    )
    std.set_metric("is_ff", {i: 1.0 for i, t in zip(std.ids, std.type, strict=True) if is_ff(t)})
    std.set_metric("hdl_spans", spans)

    rows_y = sorted({r[2] for r in df.rows})
    row_of = {y: k for k, y in enumerate(rows_y)}
    pitch = (rows_y[1] - rows_y[0]) if len(rows_y) > 1 else 0
    die = export.Plane("die")
    cx: dict[str, float] = {}
    cy: dict[str, float] = {}
    rowm: dict[str, float] = {}
    flip: dict[str, float] = {}
    conf: dict[str, float] = {}
    pos: dict[str, anchors.Pos] = {}
    gpos: dict[str, anchors.Pos] = {}
    shift: dict[str, float] = {}
    glob = read_global(flow / "or" / "s04_global_place.csv")
    fill = 0
    for c in df.comps:
        if "__fill_" in c.master or "__decap_" in c.master or c.name.startswith("FILLER_"):
            fill += 1
            continue
        po = place_objs.get(c.name)
        origin = po["origin"] if po else ("hdl" if c.name in std_by_name else "unknown")
        kind = "logic" if origin == "hdl" else origin.split(":", 1)[-1]
        did = f"die:{c.name}"
        die.add(did, kind, c.master, origin, c.name)
        mac = macros.get(c.master)
        x, y = c.x / u, c.y / u
        cx[did], cy[did] = x, y
        pos[did] = (
            round(x + (mac.w / 2 if mac else 0.0), 3),
            round(y + (mac.h / 2 if mac else 0.0), 3),
        )
        g = glob.get(c.name)
        if g:
            gx, gy = g[0] / u, g[1] / u
            gpos[did] = (pos[did][0] + gx - x, pos[did][1] + gy - y)
            shift[did] = round(abs(gx - x) + abs(gy - y), 3)
        elif glob:
            gpos[did] = pos[did]  # inserted after global placement (CTS, repair): final place
        if c.y in row_of:
            rowm[did] = float(row_of[c.y])
        flip[did] = 1.0 if c.orient in FLIPPED else 0.0
        rc = recovered.get(c.name)
        conf[did] = float(export.CONF_RANK[rc]) if rc else -1.0
        if po:
            for lk in po["links"]:
                if lk["to"] in std_set:
                    links.append((lk["to"], did, "name", lk["confidence"]))
    die.set_metric("x_um", cx)
    die.set_metric("y_um", cy)
    die.set_metric("row", rowm)
    die.set_metric("flipped", flip)
    die.set_metric("legal_shift_um", shift)
    die.set_metric("recover_conf", conf)
    die.set_metric(
        "area_um2",
        {
            i: macros[t].w * macros[t].h
            for i, t in zip(die.ids, die.type, strict=True)
            if t in macros
        },
    )
    die.set_metric(
        "drive",
        {i: v for i, t in zip(die.ids, die.type, strict=True) if (v := drive_of(t)) is not None},
    )
    die.set_metric("is_ff", {i: 1.0 for i, t in zip(die.ids, die.type, strict=True) if is_ff(t)})

    route = export.Plane("route")
    ncount: dict[str, float] = {}
    rpos: dict[str, anchors.Pos] = {}
    members: dict[str, list[str]] = {}
    metrics: dict[str, dict[str, float]] = {
        k: {} for k in ("wire_um", "vias", "layers", "hpwl_um", "fanout")
    }
    routes: list[tuple[float, str, list[tuple[str, list[tuple[float, float]]]]]] = []
    dups: set[tuple[str, str]] = set()
    for net in df.nets:
        inst = [(i, p) for i, p in net.pins if f"die:{i}" in pos]
        if len(inst) < 2 or not net.segs:
            continue
        rid = f"route:{net.name}"
        route.add(rid, "net", "signal", "hdl", net.name)
        length = 0.0
        layers = set()
        poly: list[tuple[str, list[tuple[float, float]]]] = []
        for layer, pts in net.segs:
            layers.add(layer)
            length += (
                sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(pts, pts[1:], strict=False))
                / u
            )
            poly.append((layer, [(x / u, y / u) for x, y in pts]))
        xs = [cx[f"die:{i}"] for i, _ in inst]
        ys = [cy[f"die:{i}"] for i, _ in inst]
        metrics["wire_um"][rid] = round(length, 3)
        metrics["vias"][rid] = float(net.vias)
        metrics["layers"][rid] = float(len(layers))
        metrics["hpwl_um"][rid] = round(max(xs) - min(xs) + max(ys) - min(ys), 3)
        metrics["fanout"][rid] = float(len(inst))
        rpos[rid] = (round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3))
        members[rid] = [f"die:{i}" for i, _p in inst]
        routes.append((length, rid, poly))
        for i, _p in inst:
            if (f"die:{i}", rid) not in dups:
                dups.add((f"die:{i}", rid))
                links.append((f"die:{i}", rid, "pin", "exact"))
                ncount[f"die:{i}"] = ncount.get(f"die:{i}", 0.0) + 1
    for key, col in metrics.items():
        route.set_metric(key, col)
    die.set_metric("nets", ncount)

    ox0, oy0, ox1, oy1 = (v / u for v in df.die)
    cx0 = min((r[1] for r in df.rows), default=df.die[0]) / u
    cx1 = max((r[1] + r[4] * r[5] for r in df.rows), default=df.die[2]) / u
    cy0 = rows_y[0] / u if rows_y else oy0
    cy1 = (rows_y[-1] + pitch) / u if rows_y else oy1
    planes: dict[str, export.Plane] = {"hdl": hdl, "stdcell": std, "die": die}
    notes = (
        ["gates link to ir cells in this prov: hdl -> stdcell links are composed (cone, medium)"]
        if composed
        else []
    )
    if route.ids:
        planes["route"] = route
    meta: dict[str, Any] = {
        "index": index,
        "die_box": [ox0, oy0, ox1, oy1],
        "core_box": [cx0, cy0, cx1, cy1],
        "rows": {
            "count": len(rows_y),
            "pitch_um": pitch / u,
            "y0_um": cy0,
            "x0_um": cx0,
            "x1_um": cx1,
        },
        "fill_cells": fill,
        "notes": notes,
        "routes": routes,
        "route_pos": rpos,
        "gpos": gpos,
        "members": members,
        "net_edges": net_edges(df, macros, {c.name for c in df.comps if f"die:{c.name}" in pos}),
        "macros": len(macros),
        "recovered": sum(1 for c in conf.values() if c >= 0),
        "unjoined": sum(1 for c in conf.values() if c < 0),
    }
    return planes, links, parent, {**pos, **rpos}, meta


def _route_file(meta: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """routes.json: the polylines of the longest nets until ROUTE_SEG_CAP segments."""
    layers: list[str] = []
    nets: dict[str, list[list[Any]]] = {}
    total = 0
    dropped = 0
    for _len, rid, poly in sorted(meta["routes"], key=lambda r: (-r[0], r[1])):
        if total + len(poly) > ROUTE_SEG_CAP:
            dropped += 1
            continue
        total += len(poly)
        segs: list[list[Any]] = []
        for layer, pts in poly:
            if layer not in layers:
                layers.append(layer)
            flat: list[float] = []
            for x, y in pts:
                flat += [round(x, 3), round(y, 3)]
            segs.append([layers.index(layer), *flat])
        nets[rid] = segs
    return {"unit": "um", "layers": layers, "nets": nets}, dropped


def write_net_edges(bundle: Path, flow: Path, lef: Path | None = None) -> int:
    """Write bundle/edges/net.json from the DEF of a silicon run (for pages built before it
    existed)."""
    df = read_def(find_def(flow))
    macros = read_lef(lef or default_lef())
    pairs = net_edges(df, macros, {c.name for c in df.comps})
    export.write_json(bundle / "edges" / "net.json", [list(e) for e in pairs])
    return len(pairs)


def export_asic(
    flow: Path,
    out: Path,
    benchmark: str = "",
    src_dirs: list[Path] | None = None,
    lef: Path | None = None,
) -> dict[str, Any]:
    """Write the bundle of a silicon-flow run (`flow` holds prov/ and or/route.def)."""
    lef = lef or default_lef()
    planes, links, parent, pos, meta = build_asic_planes(flow, lef)
    order = [p for p in ASIC_ORDER if p in planes]
    ids = {p: planes[p].ids for p in order}
    all_ids = {i for p in order for i in ids[p]}
    kept = sorted({lk for lk in links if lk[0] in all_ids and lk[1] in all_ids})
    dropped = len(set(links)) - len(kept)
    ulinks = [(a, b) for a, b, _, _ in kept]
    box = meta["die_box"]
    # anchor y runs up the screen: y' = die top - y (the coord header carries flip_y)
    pos = {i: (x, round(box[3] - y, 3)) for i, (x, y) in pos.items()}
    centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    apos, un = anchors.placement_anchor(order, ids, ulinks, pos, centre, parent, [])
    apos = anchors.strip_unanchored(apos, un, 2.0)
    b = anchors.bounds_of(apos, 0.0)
    place = anchorset.packed(
        apos, un, [min(b[0], box[0]), min(b[1], box[1]), max(b[2], box[2]), max(b[3], box[3])]
    )
    sets = {"placement": place, "ast": anchorset.ast_anchor(order, planes, ulinks, parent)}
    if meta["gpos"]:
        gbot = {i: (x, round(box[3] - y, 3)) for i, (x, y) in meta["gpos"].items()}
        for rid, mem in meta["members"].items():
            gbot[rid] = (
                round(sum(gbot[m][0] for m in mem) / len(mem), 3),
                round(sum(gbot[m][1] for m in mem) / len(mem), 3),
            )
        gp, gun = anchors.placement_anchor(order, ids, ulinks, gbot, centre, parent, [])
        gp = anchors.strip_unanchored(gp, gun, 2.0)
        gb = anchors.bounds_of(gp, 0.0)
        sets["global"] = anchorset.packed(
            gp,
            gun,
            [min(gb[0], box[0]), min(gb[1], box[1]), max(gb[2], box[2]), max(gb[3], box[3])],
        )

    src_search = [*(src_dirs or []), flow.parent, flow]
    sources = export.find_sources(meta["index"], planes, src_search)
    hashes: dict[str, str] = {}
    import hashlib

    for name, path in sources.items():
        dest = out / "hdl" / re.sub(r"[<>]", "_", name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for p in order:
        export.write_json(out / "planes" / f"{p}.json", export.plane_json(planes[p]))
    export.write_json(out / "links.json", export.compact_links(order, planes, kept))
    export.write_json(out / "edges" / "lut.json", [])
    export.write_json(out / "edges" / "net.json", [list(e) for e in meta["net_edges"]])
    notes = [
        *meta["notes"],
        f"asic target: {meta['fill_cells']} fill and decap cells are not planes",
        "no cell plane: the silicon prov links gates to HDL statements directly (cone, medium)",
    ]
    if "route" in planes:
        rf, rdrop = _route_file(meta)
        export.write_json(out / "routes.json", rf)
        if rdrop:
            notes.append(
                f"routes.json: {rdrop} shortest nets have no polyline (cap {ROUTE_SEG_CAP})"
            )
    for name, aset in sets.items():
        export.write_json(out / "anchors" / f"{name}.json", aset)
    tools = {
        t["id"]: f"{t.get('version', '')}".splitlines()[0]
        for t in meta["index"].get("tools", [])
        if t.get("version")
    }
    box_c = meta["core_box"]
    coord: dict[str, Any] = {}
    for p in ("die", "route"):
        if p in planes:
            coord[p] = {
                "kind": "um",
                "unit": "um",
                "origin": [box[0], box[1]],
                "flip_y": box[3],
                "bounds": box,
                "core": box_c,
                "rows": meta["rows"],
            }
    metrics = [
        m
        for m in ASIC_METRICS
        + [
            {
                "name": n,
                "unit": u,
                "planes": ["hdl"],
                "scale": "seq",
                "measurer": f"heimdall.targets.asic: {n} of the HDL statement",
                "source": "odin3 prov step read",
                "target": "common",
            }
            for n, u in (("depth", "levels"), ("children", "statements"), ("span_lines", "lines"))
        ]
        if any(
            planes[p].metrics.get(m["name"])
            and any(v is not None for v in planes[p].metrics[m["name"]])
            for p in order
            if p in m["planes"]
        )
    ]
    metrics.append(
        {
            "name": "hdl_spans",
            "unit": "HDL spans",
            "planes": ["stdcell"],
            "scale": "seq",
            "measurer": "cone links of the gate to HDL statements",
            "source": "odin3 prov step map",
            "target": "asic",
        }
    )
    manifest = {
        "bundle_version": export.BUNDLE_VERSION,
        "benchmark": benchmark,
        "flow": "silicon",
        "plane_targets": targets.plane_targets(order),
        "coord": coord,
        "design": meta["index"].get("design", ""),
        "top": meta["index"].get("top", ""),
        "tools": tools,
        "inputs": hashes,
        "planes": order,
        "counts": {p: len(planes[p].ids) for p in order},
        "links": len(kept),
        "paths": 0,
        "dropped_links": dropped,
        "unanchored": len(place["unanchored"]),
        "anchors": sorted(sets),
        "metrics": metrics,
        "missing_planes": ["ir", "cell"] + ([] if "route" in planes else ["route"]),
        "buses": [],
        "notes": notes,
        "select_cells": 0,
        "grid": [],
        "graphs": {},
        "asic": {
            "die_um": [box[2] - box[0], box[3] - box[1]],
            "core_um": [box_c[2] - box_c[0], box_c[3] - box_c[1]],
            "fill_cells": meta["fill_cells"],
            "recovered": meta["recovered"],
            "unjoined": meta["unjoined"],
            "lef": bool(meta["macros"]),
        },
    }
    export.write_json(out / "manifest.json", manifest)
    return manifest
