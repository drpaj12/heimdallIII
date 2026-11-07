"""Graph analytics of a bundle: graphlet signatures, clusterings, signature comparison (stdlib
only).

Odin III does the counting and the metrics; this module only builds the edge lists, calls the bridge
program `tools/odin3_glet_bridge.py` and clusters the returned rows. See the design spec section 8.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from heimdall import cluster

GLOBAL_FANOUT = (
    16  # a driver with this many sinks or more gives no edges (Odin III --exclude-global)
)
MAX_WORK = 2_000_000_000
DIMS = 24  # clustering features: the DIMS orbit columns of largest variance
MAX_SIG_GROUPS = 24  # clusters per algorithm that get a signature
MODES = {"u": ("undirected-5", 73, False, 5), "d": ("directed-4", 129, True, 4)}
FEATURES = ("gdv_u", "gdv_d", "xy")
BRIDGE = Path(__file__).resolve().parent.parent / "tools" / "odin3_glet_bridge.py"
ODIN3_ROOT = Path.home() / "odin3-ws" / "odin3"


@dataclass
class PlaneGraph:
    plane: str
    ids: list[str]
    edges: list[tuple[int, int]]  # directed, simple, no self loops
    excluded: int = 0  # drivers dropped by the global-fanout rule
    pos: list[tuple[float, float]] | None = None
    source: str = ""


@dataclass
class Bridge:
    python: Path
    py_dir: Path
    lib: Path
    calls: int = 0
    seconds: float = 0.0
    log: list[str] = field(default_factory=list)

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        env = {**os.environ, "ODIN3_PY_DIR": str(self.py_dir), "ODIN3_LIB": str(self.lib)}
        t0 = time.time()
        p = subprocess.run(
            [str(self.python), "-I", str(BRIDGE)],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.seconds += time.time() - t0
        self.calls += 1
        if p.returncode != 0:
            lines = p.stderr.strip().splitlines()
            # Odin III logs why a count stops (work bound: hub nodes make too many node sets) before
            # the exception line; keep that line.
            why = [ln for ln in lines if "connected node sets" in ln] or lines[-1:]
            raise RuntimeError(f"odin3 bridge failed: {why}")
        out: dict[str, Any] = json.loads(p.stdout)
        return out


def find_bridge(python: Path | None = None) -> Bridge | None:
    """The bridge settings from the argument, $HEIMDALL_ODIN3_PYTHON, or the Odin III checkout."""
    py = python or (
        Path(os.environ["HEIMDALL_ODIN3_PYTHON"])
        if os.environ.get("HEIMDALL_ODIN3_PYTHON")
        else None
    )
    root = Path(os.environ.get("HEIMDALL_ODIN3_ROOT", str(ODIN3_ROOT)))
    py = py or root / ".venv" / "bin" / "python"
    lib = Path(os.environ.get("ODIN3_LIB", str(root / "build" / "rel-main4" / "libodin3.so")))
    py_dir = root / "plugins" / "python"
    if py.is_file() and lib.is_file() and (py_dir / "odin3.py").is_file():
        return Bridge(py, py_dir, lib)
    return None


# ---- graph assembly -------------------------------------------------------------------------


def make_graph(
    plane: str,
    ids: Sequence[str],
    pairs: Sequence[tuple[str, str]],
    exclude_global: bool,
    source: str,
) -> PlaneGraph:
    """Simple directed graph on `ids` from (driver id, sink id) pairs; pairs with an unknown end and
    self loops are dropped. With exclude_global a driver of GLOBAL_FANOUT or more sinks loses its
    edges."""
    at = {x: i for i, x in enumerate(ids)}
    out: dict[int, set[int]] = {}
    for a, b in pairs:
        i, j = at.get(a), at.get(b)
        if i is not None and j is not None and i != j:
            out.setdefault(i, set()).add(j)
    excluded = 0
    edges: list[tuple[int, int]] = []
    for i in sorted(out):
        if exclude_global and len(out[i]) >= GLOBAL_FANOUT:
            excluded += 1
            continue
        edges.extend((i, j) for j in sorted(out[i]))
    return PlaneGraph(plane, list(ids), edges, excluded, None, source)


class BundleReader:
    """Reads the JSON files of a bundle directory, plain or packed (manifest `parts`)."""

    def __init__(self, bundle: Path) -> None:
        self.bundle = bundle
        self.man: dict[str, Any] = json.loads(
            (bundle / "manifest.json").read_text(encoding="utf-8")
        )
        self.parts: dict[str, list[str]] = self.man.get("parts") or {}

    def has(self, rel: str) -> bool:
        return rel in self.parts or (self.bundle / rel).is_file()

    def read(self, rel: str) -> Any:
        if rel in self.parts:
            blob = b"".join((self.bundle / f).read_bytes() for f in self.parts[rel])
            return json.loads(gzip.decompress(blob))
        return json.loads((self.bundle / rel).read_text(encoding="utf-8"))


def _col(plane: dict[str, Any], key: str) -> list[Any] | None:
    v = plane.get("metrics", {}).get(key)
    return v if isinstance(v, list) else None


def _xy(plane: dict[str, Any], kx: str, ky: str) -> list[tuple[float, float]] | None:
    xs, ys = _col(plane, kx), _col(plane, ky)
    if not xs or not ys or any(v is None for v in xs) or any(v is None for v in ys):
        return None
    return [(float(a), float(b)) for a, b in zip(xs, ys, strict=True)]


def bundle_graphs(rd: BundleReader) -> tuple[list[PlaneGraph], list[str]]:
    """The plane graphs a bundle holds, derived from its own files, and notes for the planes
    without."""
    man = rd.man
    order: list[str] = man["planes"]
    planes = {p: rd.read(f"planes/{p}.json") for p in order}
    notes: list[str] = []
    out: list[PlaneGraph] = []
    if "lut" in planes and rd.has("edges/lut.json"):
        lut = planes["lut"]
        raw = rd.read("edges/lut.json")
        g = make_graph("lut", lut["ids"], [(a, b) for a, b, _ in raw], True, "BLIF nets")
        out.append(g)
        kept = {(g.ids[i], g.ids[j]) for i, j in g.edges}
        lj = rd.read("links.json")
        allids = [i for p in order for i in planes[p]["ids"]]
        kinds = lj["kinds"]
        pk = kinds.index("pack") if "pack" in kinds else -1
        nm = kinds.index("name") if "name" in kinds else -1
        lut_set = set(lut["ids"])
        for plane, kind_i, src in (("clb", pk, "pack"), ("placed", nm, "name")):
            if plane not in planes:
                continue
            ids = set(planes[plane]["ids"])
            lift: dict[str, str] = {}
            for a, b, k, _c in lj["rows"]:
                if k == kind_i and allids[a] in lut_set and allids[b] in ids:
                    lift.setdefault(allids[a], allids[b])
            pairs = [(lift[a], lift[b]) for a, b in kept if a in lift and b in lift]
            pg = make_graph(
                plane, planes[plane]["ids"], pairs, False, f"LUT edges lifted through {src} links"
            )
            pg.pos = _xy(planes[plane], "x", "y")
            out.append(pg)
    elif "lut" in planes:
        notes.append("lut: no edges file")
    for kind in ("stg", "cfg", "ddg"):
        if kind in planes and rd.has(f"graphs/{kind}.json"):
            gd = rd.read(f"graphs/{kind}.json")
            out.append(
                make_graph(
                    kind,
                    planes[kind]["ids"],
                    [(e[0], e[1]) for e in gd["edges"]],
                    False,
                    "odin3 write_graph",
                )
            )
    if rd.has("edges/net.json"):
        pairs_n = rd.read("edges/net.json")
        for plane in ("stdcell", "die"):
            if plane not in planes:
                continue
            pl = planes[plane]
            by = {n: i for n, i in zip(pl["name"], pl["ids"], strict=True)}
            pr = [(by[a], by[b]) for a, b in pairs_n if a in by and b in by]
            pg = make_graph(plane, pl["ids"], pr, True, "DEF nets, driver from LEF pin direction")
            pg.pos = _xy(pl, "x_um", "y_um")
            out.append(pg)
    if "cell" in planes:
        notes.append("cell (ir): the bundle has no cell edges, not analysed")
    return [g for g in out if g.ids], notes


# ---- features -------------------------------------------------------------------------------


def feature_columns(rows: Sequence[Sequence[int]]) -> list[int]:
    """The DIMS orbit columns with the largest variance of log1p (constant columns are dropped)."""
    if not rows:
        return []
    n, m = len(rows), len(rows[0])
    cols: list[tuple[float, int]] = []
    for j in range(m):
        vals = [math.log1p(r[j]) for r in rows]
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        if var > 1e-12:
            cols.append((var, j))
    return sorted(j for _, j in sorted(cols, key=lambda c: (-c[0], c[1]))[:DIMS])


def log_features(rows: Sequence[Sequence[int]], keep: Sequence[int]) -> list[list[float]]:
    return [[math.log1p(r[j]) for j in keep] for r in rows]


# ---- signatures -----------------------------------------------------------------------------


def gdd_of(rows: Sequence[Sequence[int]], n_orbits: int) -> list[list[list[int]]]:
    """Per orbit the pairs [count, nodes touching the orbit that often] (count >= 1), sorted."""
    out: list[list[list[int]]] = []
    for j in range(n_orbits):
        h: dict[int, int] = {}
        for r in rows:
            if r[j] > 0:
                h[r[j]] = h.get(r[j], 0) + 1
        out.append([[k, h[k]] for k in sorted(h)])
    return out


def sig_group(name: str, rows: Sequence[Sequence[int]], n_orbits: int) -> dict[str, Any]:
    totals = [sum(r[j] for r in rows) for j in range(n_orbits)]
    return {
        "name": name,
        "reported": len(rows),
        "orbit_totals": totals,
        "gdd": gdd_of(rows, n_orbits),
    }


def catalogue(bridge: Bridge, directed: bool) -> list[tuple[int, int, int, int, int]]:
    """Odin III's orbit catalogue (`glet_count [--directed] --catalogue`, next to libodin3):
    rows (orbit, graphlet, nodes, edges, orbit size in nodes)."""
    prog = bridge.lib.parent / "glet_count"
    cmd = [str(prog), *(["--directed"] if directed else []), "--catalogue"]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"glet_count --catalogue failed: {p.stderr.strip()[-80:]}")
    rows = []
    for ln in p.stdout.splitlines():
        f = ln.split()
        if len(f) >= 5:
            rows.append((int(f[0]), int(f[1]), int(f[2]), int(f[3]), int(f[4])))
    return rows


def graphlet_table(
    cat: Sequence[tuple[int, int, int, int, int]], totals: Sequence[int], n_orbits: int
) -> list[list[int]]:
    """[graphlet, nodes, edges, count] per graphlet: its orbit total over all nodes divided by the
    orbit's size in nodes is the number of its (induced, connected) occurrences."""
    out: dict[int, list[int]] = {}
    for orbit, g, nodes, edges, mult in cat:
        if orbit < n_orbits and g not in out and mult > 0:
            out[g] = [g, nodes, edges, totals[orbit] // mult]
    return [out[g] for g in sorted(out)]


def induced(graph: PlaneGraph, members: Sequence[int]) -> tuple[int, list[tuple[int, int]]]:
    at = {m: k for k, m in enumerate(members)}
    return len(members), [(at[i], at[j]) for i, j in graph.edges if i in at and j in at]


def _sizes(labels: Sequence[int]) -> list[int]:
    out = [0] * (max(labels) + 1 if labels else 0)
    for x in labels:
        out[x] += 1
    return out


def analyse_plane(
    graph: PlaneGraph, bridge: Bridge, tmp: Path, cat_cache: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The index entry and the data file of one plane."""
    n = len(graph.ids)
    t0 = time.time()
    info: dict[str, Any] = {
        "nodes": n,
        "edges": len(graph.edges),
        "excluded_drivers": graph.excluded,
        "global_fanout": GLOBAL_FANOUT,
        "source": graph.source,
    }
    res = bridge.run(
        {
            "op": "count",
            "jobs": [
                {"n": n, "edges": graph.edges, "directed": False, "max_work": MAX_WORK},
                {"n": n, "edges": graph.edges, "directed": True, "max_work": MAX_WORK},
            ],
        }
    )
    info["_count_s"] = round(time.time() - t0, 2)
    gdv = {"u": res["rows"][0], "d": res["rows"][1]}
    data: dict[str, Any] = {"ids": graph.ids, "gdv_u": gdv["u"], "gdv_d": gdv["d"], "cl": {}}
    keep = {"gdv_u": feature_columns(gdv["u"]), "gdv_d": feature_columns(gdv["d"])}
    feats: dict[str, list[list[float]]] = {
        "gdv_u": log_features(gdv["u"], keep["gdv_u"]),
        "gdv_d": log_features(gdv["d"], keep["gdv_d"]),
    }
    info["feature_orbits"] = keep
    if graph.pos:
        feats["xy"] = [list(p) for p in graph.pos]
    runs: list[dict[str, Any]] = []
    t1 = time.time()
    for feat, rows in feats.items():
        if not rows or not rows[0]:
            continue
        km = cluster.run_kmeans(rows)
        for i, r in enumerate(km["runs"]):
            key = f"{feat}/kmeans/{r['k']}"
            data["cl"][key] = r["labels"]
            runs.append(
                {
                    "key": key,
                    "feature": feat,
                    "alg": "kmeans",
                    "k": r["k"],
                    "silhouette": r["silhouette"],
                    "default": i == km["default"],
                    "sizes": _sizes(r["labels"]),
                    "distinct": km["distinct"],
                }
            )
        ap = cluster.run_affinity(rows)
        key = f"{feat}/ap"
        data["cl"][key] = ap["labels"]
        runs.append(
            {
                "key": key,
                "feature": feat,
                "alg": "ap",
                "k": ap["k"],
                "silhouette": None,
                "default": True,
                "sizes": _sizes(ap["labels"]),
                "distinct": ap["distinct"],
                "capped": ap["capped"],
                "cap": ap["cap"],
            }
        )
    info["_cluster_s"] = round(time.time() - t1, 2)
    info["clusterings"] = runs
    t2 = time.time()
    info["graphlet_types"] = {}
    for mk, (_mode, n_orb, directed, _size) in MODES.items():
        if mk not in cat_cache:
            cat_cache[mk] = catalogue(bridge, directed)
        tot = [sum(r[j] for r in gdv[mk]) for j in range(n_orb)]
        info["graphlet_types"][mk] = graphlet_table(cat_cache[mk], tot, n_orb)
    info["signatures"] = signatures(graph, runs, data["cl"], gdv, bridge, tmp)
    info["_sig_s"] = round(time.time() - t2, 2)
    return info, data


def signatures(
    graph: PlaneGraph,
    runs: list[dict[str, Any]],
    labels: dict[str, list[int]],
    gdv: dict[str, list[list[int]]],
    bridge: Bridge,
    tmp: Path,
) -> dict[str, Any]:
    """Per mode: signatures of the clusters of the default k-means and the AP clustering of that
    mode's
    feature (largest MAX_SIG_GROUPS each) and the two Odin III similarities of every pair."""
    out: dict[str, Any] = {}
    for mk, (mode, n_orb, directed, _size) in MODES.items():
        groups: list[dict[str, Any]] = []
        members: list[list[int]] = []
        for r in runs:
            if r["feature"] != f"gdv_{mk}" or not r["default"]:
                continue
            lab = labels[r["key"]]
            order = sorted(range(len(r["sizes"])), key=lambda c: (-r["sizes"][c], c))[
                :MAX_SIG_GROUPS
            ]
            for c in order:
                members.append([i for i, x in enumerate(lab) if x == c])
                groups.append(
                    {
                        "key": r["key"],
                        "cluster": c,
                        "name": f"{r['alg']}{c}",
                        "nodes": r["sizes"][c],
                    }
                )
        if len(groups) < 1:
            continue
        counted = bridge.run(
            {
                "op": "count",
                "jobs": [
                    {"n": nn, "edges": ed, "directed": directed, "max_work": MAX_WORK}
                    for nn, ed in (induced(graph, m) for m in members)
                ],
            }
        )["rows"]
        sigs = [sig_group(g["name"], rows, n_orb) for g, rows in zip(groups, counted, strict=True)]
        path = tmp / f"{graph.plane}.{mode}.json"
        path.write_text(
            json.dumps({"mode": mode, "n_orbits": n_orb, "groups": sigs}, separators=(",", ":")),
            encoding="utf-8",
        )
        pairs = [[f"{path}#{a['name']}", f"{path}#{b['name']}"] for a in groups for b in groups]
        cmp_res = bridge.run({"op": "compare", "pairs": pairs})["results"]
        g = len(groups)
        gdd = [[round(cmp_res[i * g + j]["gdd_agreement"], 4) for j in range(g)] for i in range(g)]
        cos = [[round(cmp_res[i * g + j]["cosine_log"], 4) for j in range(g)] for i in range(g)]
        out[mk] = {
            "mode": mode,
            "groups": [
                {**gr, "totals": s["orbit_totals"]} for gr, s in zip(groups, sigs, strict=True)
            ],
            "gdd_agreement": gdd,
            "cosine_log": cos,
        }
    return out


# ---- partition files ------------------------------------------------------------------------


def write_partitions(
    out: Path, graph: PlaneGraph, info: dict[str, Any], data: dict[str, Any]
) -> list[str]:
    """Mimir partition-table import files: `# key: value` header lines, then `object
    id<TAB>cluster`."""
    names: list[str] = []
    for r in info["clusterings"]:
        if not r["default"]:
            continue
        name = f"partition.{graph.plane}.{r['feature']}.{r['alg']}.tsv"
        head = [
            f"# plane: {graph.plane}",
            f"# feature: {r['feature']}",
            f"# algorithm: {r['alg']}",
            f"# k: {r['k']}",
            f"# seed: {cluster.SEED}",
            "# columns: object_id, cluster_id",
        ]
        lab = data["cl"][r["key"]]
        body = [f"{i}\t{c}" for i, c in zip(graph.ids, lab, strict=True)]
        (out / name).write_text("\n".join([*head, *body]) + "\n", encoding="utf-8")
        names.append(name)
    return names


def analyse_bundle(
    bundle: Path, bridge: Bridge | None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Write bundle/analytics/* (plain JSON) and set manifest["analytics"]; None without a
    bridge."""
    if bridge is None:
        return None
    rd = BundleReader(bundle)
    graphs, notes = bundle_graphs(rd)
    adir = bundle / "analytics"
    adir.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {
        "version": 1,
        "seed": cluster.SEED,
        "modes": {k: {"name": v[0], "orbits": v[1]} for k, v in MODES.items()},
        "kmeans_ks": list(cluster.KS),
        "dims": DIMS,
        "ap": {"damping": 0.9, "preference": "median", "cap": cluster.AP_CAP},
        "counter": "odin3_graphlets_count via tools/odin3_glet_bridge.py",
        "planes": {},
        "notes": notes,
    }
    t0 = time.time()
    timing: dict[str, Any] = {}
    cat_cache: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="heimdall-sig-") as td:
        for g in graphs:
            if not g.edges:
                index["notes"].append(f"{g.plane}: no edges, skipped")
                continue
            try:
                info, data = analyse_plane(g, bridge, Path(td), cat_cache)
            except RuntimeError as e:
                index["notes"].append(f"{g.plane}: {e}")
                continue
            timing[g.plane] = {
                "nodes": info["nodes"],
                "count_s": info.pop("_count_s"),
                "cluster_s": info.pop("_cluster_s"),
                "signature_s": info.pop("_sig_s"),
            }
            info["partitions"] = write_partitions(adir, g, info, data)
            index["planes"][g.plane] = info
            (adir / f"{g.plane}.json").write_text(
                json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
            )
    timing["total_s"] = round(
        time.time() - t0, 2
    )  # not stored: bundles must rebuild byte-identically
    (adir / "index.json").write_text(
        json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    entry = {"planes": sorted(index["planes"])}
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    man["analytics"] = entry
    (bundle / "manifest.json").write_text(
        json.dumps(man, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    t1 = time.time()
    add_instances(bundle, bridge)
    timing["instances_s"] = round(time.time() - t1, 2)
    return entry, timing


def pack_new(bundle: Path, part_bytes: int = 40_000_000) -> None:
    """For a packed bundle: gzip the plain analytics/*.json into parts and list them in
    manifest.parts."""
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    parts = man.setdefault("parts", {})
    files = sorted((bundle / "analytics").glob("*.json"))
    net = bundle / "edges" / "net.json"
    if net.is_file() and "edges/net.json" not in parts:
        files.append(net)
    for f in files:
        rel = f.relative_to(bundle).as_posix()
        blob = gzip.compress(f.read_bytes(), compresslevel=9, mtime=0)
        names = []
        for i in range(0, max(len(blob), 1), part_bytes):
            name = f"{rel}.gz.{i // part_bytes:03d}"
            (bundle / name).write_bytes(blob[i : i + part_bytes])
            names.append(name)
        parts[rel] = names
        f.unlink()
    (bundle / "manifest.json").write_text(
        json.dumps(man, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )


INSTANCE_TYPES = 6  # the rarest graphlet types of a plane and mode that get an instance list
INSTANCE_MAX = 400  # instances kept per type; the file says when a type was cut
# One Odin III run enumerates every connected node set of the plane graph once per type. A plane
# and mode with more sets than this (about 30 s per type) gets no instance list; the index notes
# it (the criterion is the counts, not the clock, so bundles still rebuild byte-identically).
INSTANCE_MAX_SETS = 300_000_000


class Runner(Protocol):
    def run(self, job: dict[str, Any]) -> dict[str, Any]: ...


def add_instances(bundle: Path, bridge: Runner) -> list[str]:
    """Ask Odin III for the instances of the rarest graphlet types of every analysed plane and mode,
    write analytics/instances.<plane>.<mode>.json (plane object indices, plus the plane's edge list
    for the viewer's conflict graph). Needs Odin III `graphlets --instances` (spec
    2026-11-06-odin3-graphlet-instances.md; rel-main4 or later). A plane and mode with more than
    INSTANCE_MAX_SETS connected node sets, or one the bridge fails on, is skipped with a note in
    analytics/index.json. Returns the "<plane>.<mode>" names written, which are listed in
    manifest["analytics"]["instances"]."""
    rd = BundleReader(bundle)
    graphs = {g.plane: g for g in bundle_graphs(rd)[0]}
    ipath = bundle / "analytics" / "index.json"
    index = json.loads(ipath.read_text(encoding="utf-8"))
    written: list[str] = []
    for plane, info in sorted(index["planes"].items()):
        g = graphs.get(plane)
        if g is None:
            continue
        for mk, (mode, _n_orb, directed, size) in MODES.items():
            table = info["graphlet_types"][mk]
            sets = sum(r[3] for r in table)
            rows = [r for r in table if r[3] > 0]
            rare = sorted(rows, key=lambda r: (r[3], r[0]))[:INSTANCE_TYPES]
            if not rare:
                continue
            if sets > INSTANCE_MAX_SETS:
                index["notes"].append(
                    f"{plane} ({mode}): no instance list, {sets} connected node sets "
                    f"(limit {INSTANCE_MAX_SETS})"
                )
                continue
            jobs = [
                {
                    "n": len(g.ids),
                    "edges": g.edges,
                    "directed": directed,
                    "size": size,
                    "graphlet": r[0],
                    "max": INSTANCE_MAX,
                }
                for r in rare
            ]
            try:
                res = bridge.run({"op": "instances", "jobs": jobs})["results"]
            except RuntimeError as e:
                index["notes"].append(f"{plane} ({mode}): no instance list: {e}")
                continue
            types = {
                str(r[0]): {
                    "total": x["total"],
                    "written": len(x["instances"]),
                    "truncated": int(len(x["instances"]) < x["total"]),
                    "max": INSTANCE_MAX,
                    "instances": x["instances"],
                }
                for r, x in zip(rare, res, strict=True)
            }
            doc = {
                "plane": plane,
                "mode": mode,
                "edges": [list(e) for e in g.edges],
                "types": types,
            }
            name = f"{plane}.{mk}"
            (bundle / "analytics" / f"instances.{name}.json").write_text(
                json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
            )
            written.append(name)
    ipath.write_text(
        json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    man["analytics"]["instances"] = written
    (bundle / "manifest.json").write_text(
        json.dumps(man, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return written
