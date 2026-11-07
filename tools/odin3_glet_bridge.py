"""Bridge to the Odin III graphlet counter (run with the Python that has the Odin III binding).

Reads one JSON job on stdin, writes one JSON result on stdout. Heimdall never imports the binding:
it
runs this file as a program (see docs/specs/2026-11-05-heimdall-design.md section 8).

Jobs:
  {"op": "count", "jobs": [{"n": N, "edges": [[u, v], ...], "directed": bool}, ...]}
      -> {"rows": [[orbit counts of node 0, ...], ...] per job}
  {"op": "instances", "jobs": [{n, edges, directed, size, graphlet, max}, ...]}
      -> {"results": [{"total": T, "instances": [[node, ...], ...]}, ...]}
  {"op": "compare", "pairs": [[fileA, fileB], ...]}   (files hold "path#group" words)
      -> {"results": [{"gdd_agreement": x, "cosine_log": y}, ...]}  (6 decimals)
  {"op": "similarity", "n_orbits": K, "pairs": [[rowsA, rowsB], ...]}   (rows of orbit counts)
      -> {"results": [{"gdd_agreement": x, "cosine_log": y}, ...]}  (full precision)
Environment: ODIN3_PY_DIR (directory holding odin3.py), ODIN3_LIB (libodin3.so).
"""

import json
import os
import sys


def main() -> int:
    sys.path.insert(0, os.environ["ODIN3_PY_DIR"])
    import odin3  # the binding of the Odin III checkout

    job = json.load(sys.stdin)
    if job["op"] == "count":
        rows = []
        for j in job["jobs"]:
            edges = [(u, v) for u, v in j["edges"]]
            directed = bool(j["directed"])
            rows.append(
                odin3.graphlet_counts(
                    j["n"],
                    edges,
                    directed=directed,
                    size=4 if directed else 5,
                    max_work=j.get("max_work", 20_000_000_000),
                )
            )
        json.dump({"rows": rows}, sys.stdout)
    elif job["op"] == "compare":
        res = []
        for a, b in job["pairs"]:
            r = odin3.graphlet_compare(a, b)
            res.append(
                {k: r[k] for k in ("gdd_agreement", "cosine_log") if k in r} | {"keys": sorted(r)}
            )
        json.dump({"results": res}, sys.stdout)
    elif job["op"] == "similarity":
        res = []
        for a, b in job["pairs"]:
            gdd, cosine = odin3.graphlet_similarity(a, b, job["n_orbits"])
            res.append({"gdd_agreement": gdd, "cosine_log": cosine})
        json.dump({"results": res}, sys.stdout)
    elif job["op"] == "instances":  # needs Odin III graphlet_instances (rel-main4 and later)
        res = []
        for j in job["jobs"]:
            edges = [(u, v) for u, v in j["edges"]]
            total, inst = odin3.graphlet_instances(
                j["n"],
                edges,
                j["graphlet"],
                directed=bool(j["directed"]),
                size=j["size"],
                max=j["max"],
            )
            res.append({"total": total, "instances": [list(i) for i in inst]})
        json.dump({"results": res}, sys.stdout)
    else:
        raise SystemExit("unknown op")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
