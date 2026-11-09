"""Switching-activity overlay (v0.7): Bifrost III power data joined to the planes of a bundle.

Input is a data directory with one sub-directory per design (written by `wyrd power run` plus the
extras listed in docs/specs/2026-11-05-heimdall-design.md section 12):
    power.json        Bifrost schema v1 (Wyrd repo, docs/specs/2026-11-06-bifrost-power-design.md)
    activity.csv      FPGA nets: net,name,file,line,p1,activity,source
    asic_nets.csv     ASIC nets: net,p1,activity
    asic_inst.csv     ASIC instances: inst,dyn_w,static_w,out_net,file,line
Heimdall does not recompute activity or power: it joins what Bifrost measured to the plane objects
and says, per object, how the join was made (`basis`).

Output: bundle/activity/activity.json (columns aligned with each plane's `ids`) and
manifest["activity"].
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = 1
UW = 1e6  # power columns are stored in microwatts
BASIS = ("none", "net", "line", "link")  # index into the `basis` column
# planes whose object names are the netlist names Bifrost used, per target
DIRECT = {"fpga": ("lut", "placed"), "asic": ("die", "stdcell", "route")}
SOURCE_LABEL = {
    "iverilog-gate": "iverilog gate-level (the design's testbench on the post-synthesis netlist)",
    "odin3-replay": "Odin III replay (RTL names, port waveform replayed)",
    "ace2": "vectorless (ACE2)",
}
CLIP = 0.98  # the viewer's colour range of act_td and act_pw ends at this quantile
LINE_CAP = 300  # rows of the per-line table kept in the file


class ActivityError(Exception):
    pass


def _f(x: str) -> float | None:
    try:
        return float(x)
    except ValueError:
        return None


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    """One design's Bifrost files, as plain dicts."""

    def __init__(self, root: Path) -> None:
        pj = root / "power.json"
        if not pj.is_file():
            raise ActivityError(f"{root}: no power.json")
        self.power: dict[str, Any] = json.loads(pj.read_text(encoding="utf-8"))
        if self.power.get("version") != 1:
            raise ActivityError(f"{pj}: schema version {self.power.get('version')}, expected 1")
        meta = root / "meta.json"  # optional: {"bifrost": "wyrd 5e9d0361"}, shown as the source
        self.bifrost: str = (
            str(json.loads(meta.read_text(encoding="utf-8")).get("bifrost", ""))
            if meta.is_file()
            else ""
        )
        # net -> (p1, td)
        self.fpga_nets: dict[str, tuple[float, float]] = {}
        self.fpga_line: dict[
            tuple[str, int], list[float]
        ] = {}  # (file, line) -> [n, sum p1, sum td]
        for r in _rows(root / "activity.csv"):
            p, a = _f(r["p1"]), _f(r["activity"])
            if p is None or a is None:
                continue
            self.fpga_nets[r["net"]] = (p, a)
            if r.get("file") and r.get("line"):
                k = (r["file"], int(r["line"]))
                acc = self.fpga_line.setdefault(k, [0.0, 0.0, 0.0])
                acc[0] += 1
                acc[1] += p
                acc[2] += a
        self.asic_nets: dict[str, tuple[float, float]] = {}
        for r in _rows(root / "asic_nets.csv"):
            p, a = _f(r["p1"]), _f(r["activity"])
            if p is not None and a is not None:
                self.asic_nets[r["net"]] = (p, a)
        # inst -> (p1|None, td|None, power_uW)
        self.asic_inst: dict[str, tuple[float | None, float | None, float]] = {}
        self.asic_line: dict[tuple[str, int], list[float]] = {}
        for r in _rows(root / "asic_inst.csv"):
            act = self.asic_nets.get(r.get("out_net", ""))
            pw = ((_f(r["dyn_w"]) or 0.0) + (_f(r["static_w"]) or 0.0)) * UW
            self.asic_inst[r["inst"]] = (act[0] if act else None, act[1] if act else None, pw)
            if act and r.get("file") and r.get("line"):
                k = (r["file"], int(r["line"]))
                acc = self.asic_line.setdefault(k, [0.0, 0.0, 0.0])
                acc[0] += 1
                acc[1] += act[0]
                acc[2] += act[1]

    def has(self, target: str) -> bool:
        t = self.power.get("targets", {}).get(target)
        return bool(t) and "error" not in t

    def has_line_power(self, target: str) -> bool:
        """False when Bifrost gave no per-line power table for the target (the page says so)."""
        return target == "fpga" or bool(self.power.get("by_line_asic"))

    def line_power(self, target: str) -> dict[tuple[str, int], float]:
        """Power per (file, line) in uW as Bifrost gave it (FPGA: model; ASIC: per instance)."""
        out: dict[tuple[str, int], float] = {}
        if target == "fpga":
            for r in self.power.get("by_line", []):
                out[(r["file"], int(r["line"]))] = r["fpga_dyn_w"] * UW
        else:
            for r in self.power.get("by_line_asic", []):
                out[(r["file"], int(r["line"]))] = (r["asic_dyn_w"] + r["asic_static_w"]) * UW
        return out


class LineTable:
    """Per-file line arrays with prefix sums: n, sum p1, sum td, power over a line range."""

    def __init__(
        self, stats: dict[tuple[str, int], list[float]], power: dict[tuple[str, int], float]
    ) -> None:
        self.files: dict[str, dict[int, list[float]]] = defaultdict(dict)
        for (f, ln), (n, sp, st) in stats.items():
            self.files[f][ln] = [n, sp, st, 0.0]
        for (f, ln), w in power.items():
            self.files[f].setdefault(ln, [0.0, 0.0, 0.0, 0.0])[3] = w

    def range(self, f: str, a: int, b: int) -> tuple[float, float, float, float] | None:
        rows = self.files.get(f)
        if not rows:
            return None
        hit = [v for ln, v in rows.items() if a <= ln <= b]
        if not hit:
            return None
        return (
            sum(v[0] for v in hit),
            sum(v[1] for v in hit),
            sum(v[2] for v in hit),
            sum(v[3] for v in hit),
        )


_SPAN = re.compile(r"^(\d+)\.\d+-(\d+)\.\d+$")


def first_span(src: list[Any]) -> tuple[str, int, int] | None:
    """(file basename, first line, last line) of the first span of an object, or None."""
    for f, s in src:
        m = _SPAN.match(s)
        if m:
            return Path(f).name, int(m.group(1)), int(m.group(2))
    return None


def _read(bundle: Path, rel: str, parts: dict[str, list[str]]) -> Any:
    if rel in parts:
        blob = b"".join((bundle / f).read_bytes() for f in parts[rel])
        return json.loads(gzip.decompress(blob))
    return json.loads((bundle / rel).read_text(encoding="utf-8"))


def _neighbours(
    links: dict[str, Any], order: list[str], planes: dict[str, dict[str, Any]]
) -> dict[int, list[int]]:
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b, *_ in links["rows"]:
        adj[a].append(b)
        adj[b].append(a)
    return adj


def build(bundle: Path, ds: Dataset, target: str) -> dict[str, Any]:
    """The activity.json content of one bundle."""
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    parts = man.get("parts") or {}
    order: list[str] = man["planes"]
    ptarget: dict[str, str] = man.get("plane_targets", {})
    planes = {p: _read(bundle, f"planes/{p}.json", parts) for p in order}
    links = _read(bundle, "links.json", parts)
    pwl = ds.line_power(target)
    line_pw = ds.has_line_power(target)
    table = LineTable(ds.fpga_line if target == "fpga" else ds.asic_line, pwl)
    direct = {p for p in DIRECT[target] if p in planes and ptarget.get(p) == target}
    vals: dict[str, dict[str, list[Any]]] = {}
    for p in order:
        n = len(planes[p]["ids"])
        vals[p] = {"p1": [None] * n, "td": [None] * n, "pw": [None] * n, "basis": [0] * n}
    # tier 1: the object's own name is a net or instance Bifrost measured
    for p in direct:
        v = vals[p]
        for i, name in enumerate(planes[p]["name"]):
            if target == "fpga" and name in ds.fpga_nets:
                v["p1"][i], v["td"][i] = ds.fpga_nets[name]
                v["basis"][i] = 1
            elif target == "asic" and name in ds.asic_inst:
                a, b, w = ds.asic_inst[name]
                v["p1"][i], v["td"][i], v["pw"][i], v["basis"][i] = a, b, w, 1
            elif target == "asic" and name in ds.asic_nets:
                v["p1"][i], v["td"][i] = ds.asic_nets[name]
                v["basis"][i] = 1
    # tier 2: the HDL line range of the object's first span (hdl objects, and objects Bifrost named
    # differently)
    for p in order:
        v = vals[p]
        src = planes[p].get("src") or []
        for i in range(len(planes[p]["ids"])):
            if v["basis"][i] or i >= len(src) or not src[i]:
                continue
            sp = first_span(src[i])
            r = table.range(*sp) if sp else None
            if r is None:
                continue
            cnt, sp1, std, lw = r
            if cnt:
                v["p1"][i], v["td"][i] = sp1 / cnt, std / cnt
            if p == "hdl" and lw:
                v["pw"][i] = lw
            if cnt or (p == "hdl" and lw):
                v["basis"][i] = 2
    # tier 3: mean of the linked objects that have a value
    off = {}
    base = 0
    for p in order:
        off[p] = base
        base += len(planes[p]["ids"])
    where = [(p, i) for p in order for i in range(len(planes[p]["ids"]))]
    adj = _neighbours(links, order, planes)
    for p in order:
        v = vals[p]
        for i in range(len(planes[p]["ids"])):
            if v["basis"][i]:
                continue
            ps, ts = [], []
            wq: dict[str, list[float]] = defaultdict(list)
            for g in adj.get(off[p] + i, []):
                q, j = where[g]
                if q == "hdl" or vals[q]["basis"][j] not in (1, 2):
                    continue
                if vals[q]["p1"][j] is not None:
                    ps.append(vals[q]["p1"][j])
                    ts.append(vals[q]["td"][j])
                if (
                    target == "asic"
                    and (line_pw or p != "hdl")
                    and vals[q]["pw"][j] is not None
                    and vals[q]["basis"][j] == 1
                ):
                    wq[q].append(vals[q]["pw"][j])
            if ps:
                v["p1"][i], v["td"][i] = sum(ps) / len(ps), sum(ts) / len(ts)
                v["basis"][i] = 3
            if wq:
                ws = max(wq.values(), key=len)  # one plane only: no double counting
                v["pw"][i] = sum(ws) if p == "hdl" else sum(ws) / len(ws)
                v["basis"][i] = 3
    cov = {
        p: {b: sum(1 for x in vals[p]["basis"] if x == k) for k, b in enumerate(BASIS)}
        for p in order
    }
    for p in order:
        for k in ("p1", "td", "pw"):
            vals[p][k] = [None if x is None else float(f"{x:.6g}") for x in vals[p][k]]
    pw = ds.power
    t = pw["targets"][target]
    src_key = pw.get("activity", {}).get("source", "iverilog-gate")
    lines = _line_rows(table, pwl)
    out: dict[str, Any] = {
        "version": VERSION,
        "design": pw["design"],
        "target": target,
        "source": src_key,
        "source_label": SOURCE_LABEL.get(src_key, src_key),
        "testbench": pw.get("testbench"),
        "tb_pass": pw.get("tb_pass"),
        "clock": pw.get("clock"),
        "cycles": pw.get("cycles"),
        "start_state": t.get("start_state", pw.get("start_state")),
        "matched_fraction": t.get(
            "matched_fraction", pw.get("activity", {}).get("matched_fraction")
        ),
        "totals": {
            k: t[k] for k in t if isinstance(t[k], (int, float)) and not isinstance(t[k], bool)
        },
        "tool": {
            **({"bifrost": f"Bifrost III ({ds.bifrost})"} if ds.bifrost else {}),
            **{k: t[k] for k in ("arch", "tech", "method", "pdk", "parasitics") if k in t},
        },
        "warnings": t.get("warnings", []),
        "caveats": caveats(target),
        "line_power": (
            "model" if target == "fpga" else "per-instance" if line_pw else "not available"
        ),
        "lines": lines,
        "coverage": cov,
        "planes": {p: vals[p] for p in order},
    }
    return out


def caveats(target: str) -> list[str]:
    common = [
        "Activity is that of the design's own testbench (a short directed test, not a "
        "workload); glitch power is not counted.",
        "Per-net values need the net's name to agree with the name Bifrost used. Where "
        "it does not, "
        "an object takes the mean of the nets Bifrost measured on the same HDL line "
        "(basis 'line') or of its linked objects (basis 'link'); the basis is stored per "
        "object.",
    ]
    if target == "fpga":
        return [
            "The FPGA power split per HDL line is a model: VPR reports power per block "
            "type, so "
            "Bifrost spreads the dynamic non-clock power over nets by activity x (fanout + "
            "1) and sums per line. The total is VPR's; static and clock power are not "
            "split. No per-net or per-cell power exists on the FPGA planes.",
            *common,
        ]
    return [
        "The ASIC split is per instance (OpenSTA, exact apportionment); an instance's "
        "HDL line is the first line of its provenance chain in the single-file design.v. "
        "Cells inserted by the flow (tap, clock buffers) have no HDL line.",
        "ASIC clock power is the power of the clock-tree cells only; the clock-pin power "
        "inside the flip-flops is in their own internal power, so the clock figure is a "
        "lower bound.",
        "Wire load is estimated from placement (no SPEF).",
        *common,
    ]


def _line_rows(table: LineTable, power: dict[tuple[str, int], float]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for f, d in table.files.items():
        for ln, (n, sp, st, w) in d.items():
            rows.append(
                [
                    f,
                    ln,
                    int(n),
                    round(sp / n, 4) if n else None,
                    round(st / n, 6) if n else None,
                    float(f"{w:.6g}") if (f, ln) in power else None,
                ]
            )
    rows.sort(key=lambda r: (-(r[5] or 0.0), -(r[4] or 0.0), r[0], r[1]))
    return rows[:LINE_CAP]


def metric_entries(target: str, planes: list[str], source: str) -> list[dict[str, Any]]:
    on = [p for p in planes]
    how = {
        "fpga": "Bifrost III vpr --power",
        "asic": "Bifrost III OpenROAD report_power",
    }[target]
    return [
        {
            "name": "act_p1",
            "unit": "P(1)",
            "planes": on,
            "scale": "seq",
            "target": target,
            "source": f"Bifrost III, {source}",
            "measurer": "static probability: time at 1 / time at 0 or 1 over the testbench",
        },
        {
            "name": "act_td",
            "unit": "toggles/cycle",
            "planes": on,
            "scale": "seq",
            "clip": CLIP,
            "target": target,
            "source": f"Bifrost III, {source}",
            "measurer": "transition density: 0<->1 transitions per rising clock edge",
        },
        {
            "name": "act_pw",
            "unit": "uW",
            "planes": on,
            "scale": "seq",
            "clip": CLIP,
            "target": target,
            "source": how,
            "measurer": "power: ASIC per instance (dynamic + leakage); FPGA per HDL line (a model)",
        },
    ]


def apply(bundle: Path, ds: Dataset, target: str, part_bytes: int = 40_000_000) -> dict[str, Any]:
    """Write bundle/activity/activity.json (packed like the other files when the bundle is) and
    update the manifest. Returns the manifest entry."""
    data = build(bundle, ds, target)
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    adir = bundle / "activity"
    adir.mkdir(exist_ok=True)
    raw = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    parts = man.get("parts")
    if parts is not None:
        blob = gzip.compress(raw, compresslevel=9, mtime=0)
        names = []
        for i in range(0, max(len(blob), 1), part_bytes):
            name = f"activity/activity.json.gz.{i // part_bytes:03d}"
            (bundle / name).write_bytes(blob[i : i + part_bytes])
            names.append(name)
        parts["activity/activity.json"] = names
    else:
        (adir / "activity.json").write_bytes(raw)
    planes = [
        p
        for p in man["planes"]
        if any(x is not None for x in data["planes"][p]["p1"])
        or any(x is not None for x in data["planes"][p]["pw"])
    ]
    man["metrics"] = [m for m in man["metrics"] if not m["name"].startswith("act_")]
    man["metrics"] += metric_entries(target, planes, data["source_label"])
    entry = {
        "target": target,
        "source": data["source"],
        "source_label": data["source_label"],
        "planes": planes,
    }
    man["activity"] = entry
    (bundle / "manifest.json").write_text(
        json.dumps(man, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return entry


def target_of(bundle: Path) -> str | None:
    """fpga for a vtr-flow bundle, asic for a silicon-flow bundle."""
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    return {"vtr": "fpga", "silicon": "asic"}.get(man.get("flow", ""))


SUITE_PREFIX = ("odin3-micro-", "vtr-verilog-", "verilogeval-", "opencores-", "silicon-")


def design_of(slug: str) -> str:
    """The design directory name of a page slug (the suite prefix removed)."""
    for pre in SUITE_PREFIX:
        if slug.startswith(pre):
            return slug[len(pre) :]
    return slug.partition("-")[2]
