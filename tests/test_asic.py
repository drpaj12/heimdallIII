"""ASIC target: DEF and LEF readers and the silicon bundle, on a hand-made tiny run."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
import unittest
from pathlib import Path
from typing import Any

from heimdall import flows, site
from heimdall.targets import asic

DATA = Path(__file__).resolve().parent / "data" / "silicon"
LEF = DATA / "design_t.lef"


def col(plane: dict[str, Any], name: str) -> dict[str, Any]:
    return dict(zip(plane["ids"], plane["metrics"][name], strict=True))


class TestReaders(unittest.TestCase):
    def test_def(self) -> None:
        d = asic.read_def(DATA / "or" / "route.def")
        self.assertEqual(d.die, (0, 0, 20000, 20000))
        self.assertEqual(len(d.rows), 2)
        self.assertEqual(len(d.comps), 5)
        g2 = next(c for c in d.comps if c.name == "g2")
        self.assertEqual((g2.x, g2.y, g2.orient), (5600, 4720, "FS"))
        n1 = d.nets[0]
        self.assertEqual(n1.pins, [("g1", "Y"), ("g2", "D")])
        self.assertEqual(n1.segs[0], ("met1", [(2000, 3000), (6000, 3000)]))
        self.assertEqual(n1.segs[1], ("met2", [(6000, 3000), (6000, 5000)]))
        self.assertEqual(n1.vias, 1)
        self.assertEqual(d.nets[2].segs, [])

    def test_lef(self) -> None:
        m = asic.read_lef(LEF)
        self.assertEqual(m["sky130_fd_sc_hd__nand2_1"].pins, 3)
        self.assertAlmostEqual(m["sky130_fd_sc_hd__dfxtp_1"].w, 17.48)

    def test_nest_parents(self) -> None:
        objs = [
            {"id": i, "src": [{"file": "d.v", "span": s}]}
            for i, s in (("a", "1.1-4.10"), ("b", "2.1-2.20"), ("c", "2.3-2.9"), ("d", "4.1-4.5"))
        ]
        self.assertEqual(asic.nest_parents(objs), {"b": "a", "c": "b", "d": "a"})


class TestBundle(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "b"
        self.man = asic.export_asic(DATA, self.out, "silicon:t", [DATA], LEF)

    def load(self, rel: str) -> Any:
        return json.loads((self.out / rel).read_text(encoding="utf-8"))

    def test_manifest(self) -> None:
        m = self.man
        self.assertEqual(m["flow"], "silicon")
        self.assertEqual(m["planes"], ["hdl", "stdcell", "die", "route"])
        self.assertEqual(m["counts"], {"hdl": 4, "stdcell": 2, "die": 4, "route": 1})
        self.assertEqual(
            m["plane_targets"], {"hdl": "common", "stdcell": "asic", "die": "asic", "route": "asic"}
        )
        c = m["coord"]["die"]
        self.assertEqual((c["kind"], c["unit"]), ("um", "um"))
        self.assertEqual(c["bounds"], [0.0, 0.0, 20.0, 20.0])
        self.assertEqual(c["core"], [1.0, 2.0, 5.6, 7.44])
        self.assertEqual(c["rows"]["count"], 2)
        self.assertAlmostEqual(c["rows"]["pitch_um"], 2.72)
        self.assertEqual(m["asic"]["fill_cells"], 1)
        self.assertEqual((m["asic"]["recovered"], m["asic"]["unjoined"]), (1, 3))
        for metric in m["metrics"]:
            self.assertTrue(set(metric["planes"]) <= set(m["planes"]))
            self.assertIn(metric["target"], ("asic", "common"))
        self.assertEqual(m["anchors"], ["ast", "placement"])

    def test_links(self) -> None:
        lj = self.load("links.json")
        kinds = Counter(lj["kinds"][r[2]] + "/" + lj["confidences"][r[3]] for r in lj["rows"])
        self.assertEqual(dict(kinds), {"cone/medium": 4, "name/exact": 2, "pin/exact": 2})
        self.assertEqual(self.man["links"], 8)

    def test_die_plane(self) -> None:
        die = self.load("planes/die.json")
        self.assertEqual(die["ids"], ["die:g1", "die:g2", "die:TAP_0", "die:clkbuf_0_clk"])
        self.assertEqual(die["kind"], ["logic", "logic", "tap", "cts_buffer"])
        self.assertEqual(col(die, "x_um")["die:g2"], 5.6)
        self.assertEqual(col(die, "y_um")["die:g2"], 4.72)
        self.assertEqual(col(die, "row")["die:g1"], 0.0)
        self.assertEqual(col(die, "row")["die:g2"], 1.0)
        self.assertEqual(col(die, "flipped")["die:g2"], 1.0)
        self.assertEqual(col(die, "recover_conf")["die:g1"], 3.0)  # high
        self.assertEqual(col(die, "recover_conf")["die:g2"], -1.0)  # unmatched
        self.assertEqual(col(die, "nets")["die:g1"], 1.0)
        self.assertAlmostEqual(col(die, "area_um2")["die:g1"], 3.68 * 2.72)

    def test_stdcell_and_route(self) -> None:
        std = self.load("planes/stdcell.json")
        self.assertEqual(std["type"], ["sky130_fd_sc_hd__nand2_1", "sky130_fd_sc_hd__dfxtp_1"])
        self.assertEqual(col(std, "pins")["gates:g1"], 3.0)
        self.assertEqual(col(std, "drive")["gates:g2"], 1.0)
        self.assertEqual(col(std, "is_ff")["gates:g2"], 1.0)
        rt = self.load("planes/route.json")
        self.assertEqual(rt["ids"], ["route:n1"])
        self.assertAlmostEqual(col(rt, "wire_um")["route:n1"], 6.0)
        self.assertEqual(col(rt, "vias")["route:n1"], 1.0)
        self.assertEqual(col(rt, "layers")["route:n1"], 2.0)
        self.assertAlmostEqual(col(rt, "hpwl_um")["route:n1"], 7.32)
        poly = self.load("routes.json")
        self.assertEqual(poly["layers"], ["met1", "met2"])
        self.assertEqual(
            poly["nets"]["route:n1"], [[0, 2.0, 3.0, 6.0, 3.0], [1, 6.0, 3.0, 6.0, 5.0]]
        )

    def test_hdl_plane(self) -> None:
        hdl = self.load("planes/hdl.json")
        self.assertEqual(col(hdl, "depth")["hdl:d.v:2.1-2.20"], 1.0)
        below = col(hdl, "cells_below")
        self.assertEqual([below[i] for i in hdl["ids"]], [2.0, 1.0, 1.0, 0.0])

    def test_placement_anchor_in_um(self) -> None:
        a = self.load("anchors/placement.json")
        self.assertEqual(a["pos"]["die"]["die:g1"], [2.84, 3.36])  # lower left + half the LEF size
        self.assertEqual(a["pos"]["die"]["die:g2"], [14.34, 6.08])
        self.assertEqual(a["pos"]["stdcell"]["gates:g1"], [2.84, 3.36])
        self.assertEqual(a["pos"]["hdl"]["hdl:d.v:2.1-2.20"], [2.84, 3.36])
        self.assertEqual(a["pos"]["hdl"]["hdl:d.v:1.1-4.10"], [8.59, 4.72])
        self.assertEqual(a["unanchored"], ["hdl:d.v:4.1-4.5"])
        self.assertEqual(a["bounds"][:4][0:2], [0.0, 0.0])
        self.assertEqual(a["bounds"][2:], [20.0, 20.0])

    def test_source_copied(self) -> None:
        self.assertTrue((self.out / "hdl" / "d.v").is_file())
        self.assertIn("d.v", self.man["inputs"])


class TestDispatchAndSite(unittest.TestCase):
    def test_is_silicon(self) -> None:
        self.assertTrue(flows.is_silicon(DATA))
        self.assertFalse(flows.is_silicon(DATA.parent / "flow"))

    def test_site_extend(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "old"
            (old / "fpga-x" / "bundle").mkdir(parents=True)
            (old / "index.html").write_text(
                '<p class="dim"><b>Update 4</b>: old note.</p>\n<p class="nav">nav</p>\n'
                "<table><thead><tr><th>design</th><th>suite</th><th>LUTs</th><th>FFs</th>\n"
                "<th>what it does</th><th>catalogue</th></tr></thead>\n<tbody>\n"
                '<tr><td><a href="fpga-x/">x</a></td><td>fpga</td><td class="n">3</td>'
                '<td class="n">1</td><td>w</td><td>c</td></tr>\n</tbody></table>\n',
                encoding="utf-8",
            )
            out = Path(d) / "new"
            spec = site.parse_spec(f"silicon:t={DATA},lef={LEF},what=tiny")
            rows = site.build_site(out, "", [spec], extend=old, note="<p>Update 5</p>")
            self.assertEqual(rows[0]["target"], "asic")
            self.assertEqual((rows[0]["cells"], rows[0]["die"]), (2, "20 x 20"))
            idx = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("<th>target</th>", idx)
            self.assertIn('<td>fpga</td><td class="n">3</td>', idx)
            self.assertIn("<td>asic</td>", idx)
            self.assertNotIn("Update 4", idx)
            self.assertIn("<p>Update 5</p>", idx)
            self.assertTrue((out / "silicon-t" / "bundle" / "manifest.json").is_file())
            self.assertTrue((out / "fpga-x" / "bundle").is_dir())


if __name__ == "__main__":
    unittest.main()
