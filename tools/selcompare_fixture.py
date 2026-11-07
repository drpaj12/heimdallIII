"""Make tests/data/selcompare/fixture.json: Odin III's own metric values for node subsets of small graphs.

Needs the Odin III Python binding (see tools/odin3_glet_bridge.py and analytics.find_bridge). Per graph the rows
come from Odin III graphlet counting; per case two subsets of the nodes are signed (orbit totals + GDD of their
rows), written as an `odin3-graphlets` signature file and compared by Odin III (`graphlets --compare`, sig.c). The
JS test (tests/js/selcompare.test.mjs) asserts that web/selcompare.js gives the same numbers. Odin III
prints these metrics with 6 decimals, so the match is to 5e-7 (rounding of the print), not 1e-9.

    PYTHONPATH=. python3 tools/selcompare_fixture.py [--out PATH]
"""

import argparse
import json
import random
import tempfile
from pathlib import Path
from typing import Any

from heimdall import analytics

ROOT = Path(__file__).resolve().parent.parent

MODES = {"u": ("undirected-5", 73, False, 5), "d": ("directed-4", 129, True, 4)}


def rand_edges(rng: random.Random, n: int, m: int, directed: bool) -> list[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    while len(out) < m:
        u, v = rng.randrange(n), rng.randrange(n)
        if u == v:
            continue
        out.add((u, v) if directed else (min(u, v), max(u, v)))
    return sorted(out)


def graphs() -> list[dict[str, Any]]:
    rng = random.Random(20261107)
    star = [(0, i) for i in range(1, 12)] + [(i, i + 1) for i in range(12, 18)] + [(3, 13), (5, 15)]
    return [
        {"name": "u14", "mode": "u", "n": 14, "edges": rand_edges(rng, 14, 22, False)},
        {"name": "u32_isolated", "mode": "u", "n": 32, "edges": rand_edges(rng, 26, 40, False)},
        {"name": "u20_hub", "mode": "u", "n": 20, "edges": star},
        {"name": "d16", "mode": "d", "n": 16, "edges": rand_edges(rng, 16, 28, True)},
        {"name": "d28_isolated", "mode": "d", "n": 28, "edges": rand_edges(rng, 24, 44, True)},
    ]


def subsets(rng: random.Random, n: int) -> list[tuple[list[int], list[int]]]:
    allv = list(range(n))
    half = rng.sample(allv, n // 2)
    rest = [v for v in allv if v not in half]
    tail = list(range(n - 4, n))  # isolated nodes on the *_isolated graphs: all-zero rows
    return [
        (half, rest),
        (allv, half),
        (half, half),
        (sorted(rng.sample(allv, 5)), sorted(rng.sample(allv, 7))),
        ([0], [1]),
        (tail, half),
        (tail, tail),
        (allv, allv),
    ]


def sig_file(path: Path, mode: str, groups: dict[str, list[list[int]]], n_orb: int) -> None:
    sigs = [analytics.sig_group(name, rows, n_orb) for name, rows in groups.items()]
    path.write_text(
        json.dumps({"mode": MODES[mode][0], "n_orbits": n_orb, "groups": sigs}, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "data" / "selcompare" / "fixture.json")
    out_path = ap.parse_args().out
    bridge = analytics.find_bridge()
    if bridge is None:
        raise SystemExit("no Odin III binding found (set HEIMDALL_ODIN3_ROOT or ODIN3_LIB)")
    rng = random.Random(7)
    result: dict[str, Any] = {"note": "Odin III metric values for node subsets; made by tools/selcompare_fixture.py", "graphs": [], "cases": []}
    with tempfile.TemporaryDirectory(prefix="heimdall-selcmp-") as td:
        for gi, g in enumerate(graphs()):
            mode = g["mode"]
            _, n_orb, directed, size = MODES[mode]
            rows = bridge.run({"op": "count", "jobs": [{"n": g["n"], "edges": g["edges"], "directed": directed}]})["rows"][0]
            result["graphs"].append({"name": g["name"], "mode": mode, "n": g["n"], "n_orbits": n_orb, "edges": g["edges"], "rows": rows})
            for ci, (a, b) in enumerate(subsets(rng, g["n"])):
                path = Path(td) / f"{gi}.{ci}.json"
                sig_file(path, mode, {"A": [rows[i] for i in a], "B": [rows[i] for i in b]}, n_orb)
                res = bridge.run({"op": "compare", "pairs": [[f"{path}#A", f"{path}#B"]]})["results"][0]
                result["cases"].append(
                    {"graph": gi, "a": a, "b": b, "gdd_agreement": res["gdd_agreement"], "cosine_log": res["cosine_log"]}
                )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(f"{len(result['graphs'])} graphs, {len(result['cases'])} cases -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
