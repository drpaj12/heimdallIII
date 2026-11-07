import json
import tempfile
import unittest
from pathlib import Path

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
            self.assertTrue((b / "analytics" / "partition.lut.gdv_u.kmeans.tsv").is_file())
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(man["analytics"]["planes"], ["lut"])


if __name__ == "__main__":
    unittest.main()
