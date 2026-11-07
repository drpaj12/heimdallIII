import csv
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


class TestActivity(unittest.TestCase):
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

    def test_first_span(self) -> None:
        self.assertEqual(activity.first_span([["x/a.v", "3.1-5.2"]]), ("a.v", 3, 5))
        self.assertIsNone(activity.first_span([]))


if __name__ == "__main__":
    unittest.main()
