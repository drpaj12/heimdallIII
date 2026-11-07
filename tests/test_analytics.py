import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from heimdall import analytics


def tiny_bundle(root: Path) -> Path:
    """A bundle with only a lut plane holding the 5-node path a-b-c-d-e (driver to sink)."""
    names = ["a", "b", "c", "d", "e"]
    ids = [f"luts:t/{n}" for n in names]
    (root / "planes").mkdir(parents=True)
    (root / "edges").mkdir()
    (root / "planes" / "lut.json").write_text(
        json.dumps({"ids": ids, "name": names, "metrics": {}}), encoding="utf-8"
    )
    edges = [[ids[i], ids[i + 1], "names"] for i in range(4)]
    (root / "edges" / "lut.json").write_text(json.dumps(edges), encoding="utf-8")
    (root / "links.json").write_text(json.dumps({"kinds": [], "rows": []}), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"planes": ["lut"]}), encoding="utf-8")
    return root


class TestGraph(unittest.TestCase):
    def test_make_graph_drops_loops_unknown_and_duplicates(self) -> None:
        g = analytics.make_graph(
            "p", ["a", "b", "c"], [("a", "b"), ("a", "b"), ("b", "b"), ("c", "x")], False, "t"
        )
        self.assertEqual(g.edges, [(0, 1)])

    def test_global_fanout_rule(self) -> None:
        ids = ["h", *[f"s{i}" for i in range(analytics.GLOBAL_FANOUT)], "x"]
        pairs = [("h", f"s{i}") for i in range(analytics.GLOBAL_FANOUT)] + [("x", "s0")]
        g = analytics.make_graph("p", ids, pairs, True, "t")
        self.assertEqual(g.excluded, 1)
        self.assertEqual(g.edges, [(len(ids) - 1, 1)])
        kept = analytics.make_graph("p", ids, pairs, False, "t")
        self.assertEqual(kept.excluded, 0)
        self.assertEqual(len(kept.edges), analytics.GLOBAL_FANOUT + 1)

    def test_gdd_and_signature_by_hand(self) -> None:
        rows = [[1, 2], [0, 2], [3, 0]]  # three nodes, two orbits
        self.assertEqual(analytics.gdd_of(rows, 2), [[[1, 1], [3, 1]], [[2, 2]]])
        sig = analytics.sig_group("g", rows, 2)
        self.assertEqual(sig["orbit_totals"], [4, 4])
        self.assertEqual(sig["reported"], 3)

    def test_induced(self) -> None:
        g = analytics.PlaneGraph("p", list("abcd"), [(0, 1), (1, 2), (2, 3)])
        self.assertEqual(analytics.induced(g, [1, 2, 3]), (3, [(0, 1), (1, 2)]))

    def test_feature_columns_drop_constants(self) -> None:
        rows = [[1, 5, 0], [2, 5, 0], [3, 5, 0]]
        self.assertEqual(analytics.feature_columns(rows), [0])


class TestBundle(unittest.TestCase):
    def test_graph_from_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rd = analytics.BundleReader(tiny_bundle(Path(td) / "b"))
            graphs, notes = analytics.bundle_graphs(rd)
            self.assertEqual(notes, [])
            self.assertEqual([g.plane for g in graphs], ["lut"])
            self.assertEqual(graphs[0].edges, [(0, 1), (1, 2), (2, 3), (3, 4)])

    def test_analyse_with_odin3(self) -> None:
        bridge = analytics.find_bridge()
        if bridge is None:
            self.skipTest("no Odin III binding")
        with tempfile.TemporaryDirectory() as td:
            b = tiny_bundle(Path(td) / "b")
            res = analytics.analyse_bundle(b, bridge)
            self.assertIsNotNone(res)
            self.assertEqual(res[0]["planes"] if res else None, ["lut"])
            data = json.loads((b / "analytics" / "lut.json").read_text(encoding="utf-8"))
            # hand count on the path a-b-c-d-e, undirected: degree of the ends 1, of the middle 2
            self.assertEqual([r[0] for r in data["gdv_u"]], [1, 2, 2, 2, 1])
            # orbit 1 = end of a 3-node path: node a is the end of a-b-c
            self.assertEqual(data["gdv_u"][0][1], 1)
            self.assertEqual(data["gdv_u"][2][2], 1)  # c is the centre of exactly b-c-d (orbit 2)
            self.assertEqual(data["ids"][0], "luts:t/a")
            index = json.loads((b / "analytics" / "index.json").read_text(encoding="utf-8"))
            info = index["planes"]["lut"]
            self.assertEqual((info["nodes"], info["edges"]), (5, 4))
            sig = info["signatures"]["u"]
            for i in range(len(sig["groups"])):
                self.assertEqual(sig["gdd_agreement"][i][i], 1.0)
                self.assertEqual(sig["cosine_log"][i][i], 1.0)
            types = {g: (n, e, c) for g, n, e, c in info["graphlet_types"]["u"]}
            # the path a-b-c-d-e holds 4 edges, 3 paths of 3 nodes, 2 of 4 nodes, 1 of 5 nodes
            self.assertEqual(types[0], (2, 1, 4))
            self.assertEqual(types[1], (3, 2, 3))
            self.assertEqual(types[2], (3, 3, 0))
            self.assertEqual([c for g, (n, e, c) in types.items() if n == 4 and e == 3 and c], [2])
            self.assertEqual(sum(c for n, e, c in types.values() if n == 5), 1)
            self.assertTrue((b / "analytics" / "partition.lut.gdv_u.kmeans.tsv").is_file())
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(man["analytics"]["planes"], ["lut"])


class FakeBridge:
    """Stands in for the bridge: canned instances."""

    calls: list[dict[str, Any]]

    def __init__(self) -> None:
        self.calls = []

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(job)
        return {"results": [{"total": 5, "instances": [[0, 1, 2], [1, 2, 3]]} for _ in job["jobs"]]}


class TestInstances(unittest.TestCase):
    def test_add_instances_with_fake_bridge(self) -> None:
        real = analytics.find_bridge()
        if real is None:
            self.skipTest("no Odin III binding for the signature step")
        with tempfile.TemporaryDirectory() as td:
            b = tiny_bundle(Path(td) / "b")
            analytics.analyse_bundle(b, real)
            fake = FakeBridge()
            names = analytics.add_instances(b, fake)
            self.assertIn("lut.u", names)
            doc = json.loads((b / "analytics" / "instances.lut.u.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["edges"], [[0, 1], [1, 2], [2, 3], [3, 4]])
            t = doc["types"]["1"]
            self.assertEqual((t["total"], t["written"], t["truncated"]), (5, 2, 1))
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("lut.u", man["analytics"]["instances"])
            # every type with a nonzero count has a list; none without
            index = json.loads((b / "analytics" / "index.json").read_text(encoding="utf-8"))
            for mk in ("u", "d"):
                d = json.loads(
                    (b / "analytics" / f"instances.lut.{mk}.json").read_text(encoding="utf-8")
                )
                nonzero = {str(r[0]) for r in index["planes"]["lut"]["graphlet_types"][mk] if r[3]}
                self.assertEqual(set(d["types"]), nonzero)
                for t in d["types"].values():
                    self.assertLessEqual(t["written"], t["max"])
            # lazy layout: instance files are not listed for preloading in the index or plane data
            self.assertNotIn("instances", json.dumps(index["planes"]))
            self.assertTrue(
                all(len(c["jobs"]) >= 1 for c in fake.calls), "one bridge call per plane and mode"
            )


def _reads_instances(bridge: Any) -> bool:
    try:
        bridge.run(
            {
                "op": "instances",
                "jobs": [
                    {
                        "n": 2,
                        "edges": [(0, 1)],
                        "directed": False,
                        "size": 5,
                        "graphlet": 0,
                        "max": 1,
                    }
                ],
            }
        )
    except RuntimeError:
        return False
    return True


class TestRealInstances(unittest.TestCase):
    """The instance files from the real Odin III: the exact total of every written type equals the
    count of the type table, which analytics derives from the orbit totals of the same graph."""

    def test_totals_equal_orbit_derived_counts(self) -> None:
        real = analytics.find_bridge()
        if real is None or not _reads_instances(real):
            self.skipTest("no Odin III binding with graphlet_instances (rel-main4 or later)")
        with tempfile.TemporaryDirectory() as td:
            b = tiny_bundle(Path(td) / "b")
            analytics.analyse_bundle(b, real)
            index = json.loads((b / "analytics" / "index.json").read_text(encoding="utf-8"))
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(man["analytics"]["instances"], ["lut.u", "lut.d"])
            for mk in ("u", "d"):
                doc = json.loads(
                    (b / "analytics" / f"instances.lut.{mk}.json").read_text(encoding="utf-8")
                )
                table = {str(r[0]): r for r in index["planes"]["lut"]["graphlet_types"][mk]}
                self.assertTrue(doc["types"])
                for g, t in doc["types"].items():
                    self.assertEqual(t["total"], table[g][3], f"{mk} G{g}")
                    self.assertEqual(t["written"], t["total"])
                    self.assertEqual(t["truncated"], 0)
                    for inst in t["instances"]:
                        self.assertEqual(inst, sorted(inst))
                        self.assertEqual(len(inst), table[g][1])

    def test_truncation_is_reported(self) -> None:
        real = analytics.find_bridge()
        if real is None or not _reads_instances(real):
            self.skipTest("no Odin III binding with graphlet_instances (rel-main4 or later)")
        old = analytics.INSTANCE_MAX
        analytics.INSTANCE_MAX = 1
        try:
            with tempfile.TemporaryDirectory() as td:
                b = tiny_bundle(Path(td) / "b")
                analytics.analyse_bundle(b, real)
                doc = json.loads(
                    (b / "analytics" / "instances.lut.u.json").read_text(encoding="utf-8")
                )
                cut = [t for t in doc["types"].values() if t["total"] > 1]
                self.assertTrue(cut)
                for t in cut:
                    self.assertEqual((t["written"], t["truncated"], t["max"]), (1, 1, 1))
        finally:
            analytics.INSTANCE_MAX = old


class TestBridgeErrors(unittest.TestCase):
    def test_work_bound_says_why(self) -> None:
        real = analytics.find_bridge()
        if real is None:
            self.skipTest("no Odin III binding")
        star = [(0, i) for i in range(1, 40)]  # a hub: C(39, 4) five-node node sets
        job = {
            "op": "count",
            "jobs": [{"n": 40, "edges": star, "directed": False, "max_work": 1000}],
        }
        with self.assertRaises(RuntimeError) as cm:
            real.run(job)
        self.assertIn("connected node sets", str(cm.exception))


class TestInstanceLimits(unittest.TestCase):
    def test_a_huge_plane_gets_a_note_not_a_run(self) -> None:
        real = analytics.find_bridge()
        if real is None:
            self.skipTest("no Odin III binding for the signature step")
        old = analytics.INSTANCE_MAX_SETS
        analytics.INSTANCE_MAX_SETS = 1
        try:
            with tempfile.TemporaryDirectory() as td:
                b = tiny_bundle(Path(td) / "b")
                analytics.analyse_bundle(b, real)
                fake = FakeBridge()
                self.assertEqual(analytics.add_instances(b, fake), [])
                self.assertEqual(fake.calls, [])
                index = json.loads((b / "analytics" / "index.json").read_text(encoding="utf-8"))
                self.assertTrue(any("no instance list" in n for n in index["notes"]))
        finally:
            analytics.INSTANCE_MAX_SETS = old


if __name__ == "__main__":
    unittest.main()
