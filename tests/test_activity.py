import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from heimdall import activity


def write_bundle(root: Path) -> Path:
    """hdl: module and two statements (a.v lines 1, 2). lut: x (named in the data), y (not, line 2),
    z (no span, linked from x). placed: q linked from z."""
    (root / "planes").mkdir(parents=True)
    hdl = {
        "ids": ["hdl:m", "hdl:s1", "hdl:s2"],
        "name": ["m", "s1", "s2"],
        "src": [[["a.v", "1.1-2.9"]], [["a.v", "1.1-1.9"]], [["a.v", "2.1-2.9"]]],
        "metrics": {},
    }
    lut = {
        "ids": ["luts:t/x", "luts:t/y", "luts:t/z"],
        "name": ["x", "y", "z"],
        "src": [[["a.v", "1.1-1.9"]], [["a.v", "2.1-2.9"]], []],
        "metrics": {},
    }
    placed = {"ids": ["placed:q"], "name": ["q"], "src": [[]], "metrics": {}}
    for n, p in (("hdl", hdl), ("lut", lut), ("placed", placed)):
        (root / "planes" / f"{n}.json").write_text(json.dumps(p), encoding="utf-8")
    # object numbers: hdl 0-2, lut 3-5, placed 6
    rows = [[0, 1, 0, 0], [1, 3, 0, 0], [3, 5, 0, 0], [5, 6, 0, 0]]
    (root / "links.json").write_text(json.dumps({"kinds": ["k"], "rows": rows}), encoding="utf-8")
    man: dict[str, Any] = {
        "planes": ["hdl", "lut", "placed"],
        "plane_targets": {"hdl": "common", "lut": "fpga", "placed": "fpga"},
        "flow": "vtr",
        "metrics": [],
    }
    (root / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return root


def write_data(root: Path) -> Path:
    root.mkdir(parents=True)
    pj = {
        "version": 1,
        "design": "t",
        "testbench": "tb.v",
        "tb_pass": True,
        "clock": "clk",
        "cycles": 10,
        "activity": {"source": "iverilog-gate", "matched_fraction": 1.0},
        "targets": {
            "fpga": {"total_w": 0.001, "dynamic_w": 0.0006, "static_w": 0.0004, "clock_w": 0.0001}
        },
        "by_line": [{"file": "a.v", "line": 1, "fpga_dyn_w": 5e-4, "nets": 1}],
    }
    (root / "power.json").write_text(json.dumps(pj), encoding="utf-8")
    with (root / "activity.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["net", "name", "file", "line", "p1", "activity", "source"])
        w.writerow(["x", "x", "a.v", "1", "0.25", "0.5", "iverilog-gate"])
        w.writerow(["w1", "w1", "a.v", "2", "0.5", "0.1", "iverilog-gate"])
        w.writerow(["w2", "w2", "a.v", "2", "0.7", "0.3", "iverilog-gate"])
    return root


def write_vl(root: Path) -> None:
    """odin3-activity json: x and y named in the bundle (hash names), plus one it lacks."""
    js = {
        "schema": "odin3-activity",
        "version": 1,
        "source": "odin3-vectorless",
        "iterations": 3,
        "converged": True,
        "nets": [
            {"id": 0, "name": "x", "p1": 0.5, "d": 0.2, "kind": "comb"},
            {"id": 1, "name": "y", "p1": 0.3, "d": 0.1, "kind": "ff"},
            {"id": 2, "name": "gone", "p1": 0.9, "d": 0.0, "kind": "comb"},
        ],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "odin3-activity.json").write_text(json.dumps(js), encoding="utf-8")


class TestActivity(unittest.TestCase):
    def test_vectorless_only_design(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            d = Path(td) / "d"
            write_vl(d)
            ds = activity.Dataset(d)
            self.assertEqual(ds.sources("fpga"), ["odin3-vectorless"])
            self.assertEqual(ds.sources("asic"), [])
            out = activity.build(b, ds, "fpga")
        lut = out["planes"]["lut"]
        self.assertEqual(lut["basis"][:2], [1, 1])
        self.assertEqual((lut["p1"][0], lut["td"][1]), (0.5, 0.1))
        self.assertEqual(lut["basis"][2], 3)  # z: link
        self.assertEqual(out["source"], "odin3-vectorless")
        self.assertEqual(out["line_power"], "none")
        self.assertAlmostEqual(out["matched_fraction"], 2 / 3)
        hdl = out["planes"]["hdl"]  # line table derived from the named objects
        self.assertEqual(hdl["basis"], [2, 2, 2])
        self.assertAlmostEqual(hdl["p1"][1], 0.5)
        self.assertAlmostEqual(hdl["p1"][2], 0.3)
        self.assertTrue(all(p is None for p in out["planes"]["hdl"]["pw"]))

    def test_two_sources_default_and_compare(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            d = write_data(Path(td) / "d")
            write_vl(d)
            ds = activity.Dataset(d)
            self.assertEqual(ds.sources("fpga"), ["iverilog-gate", "odin3-vectorless"])
            entry = activity.apply(b, ds, "fpga")
            files = sorted(f.name for f in (b / "activity").iterdir())
            vl = json.loads(
                (b / "activity" / "activity-odin3-vectorless.json").read_text(encoding="utf-8")
            )
            main = json.loads((b / "activity" / "activity.json").read_text(encoding="utf-8"))
        self.assertEqual(files, ["activity-odin3-vectorless.json", "activity.json"])
        self.assertEqual(
            [x["key"] for x in entry["sources"]], ["iverilog-gate", "odin3-vectorless"]
        )
        self.assertEqual(main["source"], "iverilog-gate")
        # common nets: x only (0.25/0.5 against 0.5/0.2)
        cmp = main["compare"][0]
        self.assertEqual((cmp["nets"], cmp["p1_mae"], cmp["density_mae"]), (1, 0.25, 0.3))
        self.assertEqual(vl["compare"][0]["other"], "iverilog-gate")
        self.assertEqual(vl["power_source"], activity.SOURCE_LABEL["iverilog-gate"])
        self.assertAlmostEqual(vl["totals"]["total_w"], 0.001)  # Bifrost's, not recomputed

    def test_packed_bundle_second_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            man["parts"] = {}
            (b / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
            for n in ("hdl", "lut", "placed"):  # pack the planes and links as the exporter does
                raw = (b / "planes" / f"{n}.json").read_bytes()
                (b / "planes" / f"{n}.json.gz.000").write_bytes(gzip.compress(raw))
                man["parts"][f"planes/{n}.json"] = [f"planes/{n}.json.gz.000"]
            (b / "links.json.gz.000").write_bytes(gzip.compress((b / "links.json").read_bytes()))
            man["parts"]["links.json"] = ["links.json.gz.000"]
            (b / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
            d = write_data(Path(td) / "d")
            write_vl(d)
            activity.apply(b, activity.Dataset(d), "fpga")
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("activity/activity-odin3-vectorless.json", man["parts"])
        self.assertIn("activity/activity.json", man["parts"])

    def test_tiers_by_hand(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            ds = activity.Dataset(write_data(Path(td) / "d"))
            out = activity.build(b, ds, "fpga")
        lut = out["planes"]["lut"]
        self.assertEqual(lut["basis"], [1, 2, 3])  # x by name, y by line 2, z by link
        self.assertEqual(lut["p1"][0], 0.25)
        self.assertAlmostEqual(lut["p1"][1], 0.6)  # mean of 0.5 and 0.7 on line 2
        self.assertAlmostEqual(lut["td"][1], 0.2)
        self.assertEqual(
            lut["p1"][2], 0.25
        )  # z has no span; its linked objects with a value: x only
        hdl = out["planes"]["hdl"]
        self.assertEqual(hdl["basis"], [2, 2, 2])
        self.assertAlmostEqual(hdl["p1"][0], (0.25 + 0.5 + 0.7) / 3, places=5)  # module: lines 1-2
        self.assertAlmostEqual(hdl["pw"][1], 500.0)  # uW of line 1 as Bifrost gave it
        self.assertIsNone(hdl["pw"][2])  # line 2 has no power row
        self.assertEqual(out["planes"]["placed"]["basis"], [0])  # link values do not chain

    def test_apply_writes_manifest_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            ds = activity.Dataset(write_data(Path(td) / "d"))
            entry = activity.apply(b, ds, "fpga")
            man = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            data = json.loads((b / "activity" / "activity.json").read_text(encoding="utf-8"))
        self.assertEqual(entry["source"], "iverilog-gate")
        self.assertEqual(man["activity"]["target"], "fpga")
        self.assertEqual([m["name"] for m in man["metrics"]], ["act_p1", "act_td", "act_pw"])
        self.assertEqual(data["line_power"], "model")
        self.assertIn("model", data["caveats"][0])

    def test_schema_version_checked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = write_data(Path(td) / "d")
            pj = json.loads((d / "power.json").read_text(encoding="utf-8"))
            pj["version"] = 2
            (d / "power.json").write_text(json.dumps(pj), encoding="utf-8")
            with self.assertRaises(activity.ActivityError):
                activity.Dataset(d)

    def test_asic_line_power_not_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = write_data(Path(td) / "d")
            pj = json.loads((d / "power.json").read_text(encoding="utf-8"))
            pj["targets"]["asic"] = {"total_w": 0.001}
            (d / "power.json").write_text(json.dumps(pj), encoding="utf-8")
            ds = activity.Dataset(d)
            self.assertTrue(ds.has_line_power("fpga"))
            self.assertFalse(ds.has_line_power("asic"))
            pj["by_line_asic"] = [
                {"file": "a.v", "line": 1, "asic_dyn_w": 1e-6, "asic_static_w": 0}
            ]
            (d / "power.json").write_text(json.dumps(pj), encoding="utf-8")
            self.assertTrue(activity.Dataset(d).has_line_power("asic"))

    def test_bifrost_source_in_tool(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            b = write_bundle(Path(td) / "b")
            d = write_data(Path(td) / "d")
            (d / "meta.json").write_text(json.dumps({"bifrost": "wyrd 5e9d0361"}), encoding="utf-8")
            out = activity.build(b, activity.Dataset(d), "fpga")
        self.assertEqual(out["tool"]["bifrost"], "Bifrost III (wyrd 5e9d0361)")

    def test_first_span(self) -> None:
        self.assertEqual(activity.first_span([["x/a.v", "3.1-5.2"]]), ("a.v", 3, 5))
        self.assertIsNone(activity.first_span([]))


if __name__ == "__main__":
    unittest.main()
