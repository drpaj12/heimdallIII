"""Complexity order of the index (heimdall.order)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from heimdall import order, site


def _row(
    suite: str, design: str, luts: int, ffs: int = 0, target: str = "fpga", cells: int = 0
) -> dict[str, Any]:
    return {
        "target": target, "cells": cells, "die": "", "slug": f"{suite}-{design}", "suite": suite,
        "design": design, "luts": luts, "ffs": ffs, "what": "w", "catalogue": "",
    }  # fmt: skip


ROWS = [
    _row("silicon", "big", 0, 5, "asic", 90),
    _row("opencores", "big", 12000, 5),
    _row("vtr-verilog", "sha", 2000, 9),
    _row("opencores", "mid", 1500, 7),
    _row("opencores", "small_b", 300, 9),
    _row("opencores", "small_a", 300, 2),
    _row("vtr-verilog", "tiny", 200, 4),
    _row("verilogeval", "Prob1", 3),
    _row("odin3-micro", "bm_x", 2),
    _row("mystery", "m", 1),
    _row("silicon", "lonely", 0, 1, "asic", 10),
]


class TestOrder(unittest.TestCase):
    def test_tiers_and_sizes(self) -> None:
        got = [(order.TIERS[t], r["slug"]) for t, r in order.order_rows(ROWS)]
        self.assertEqual(
            got,
            [
                ("Odin III micros (bm_*)", "odin3-micro-bm_x"),
                ("HDLBits-style problems (Prob*)", "verilogeval-Prob1"),
                ("Small VTR designs", "vtr-verilog-tiny"),
                ("OpenCores, small", "opencores-small_a"),
                ("OpenCores, small", "opencores-small_b"),
                ("OpenCores, medium", "opencores-mid"),
                ("OpenCores, large", "opencores-big"),
                ("OpenCores, large", "silicon-big"),
                ("Big VTR designs", "vtr-verilog-sha"),
                ("Other suites", "mystery-m"),
                ("Silicon pages without an FPGA twin", "silicon-lonely"),
            ],
        )

    def test_no_row_dropped_and_idempotent(self) -> None:
        text = site.index_html(ROWS, "", "http://x/cat")
        once, slugs, tiers = order.reorder_index(text)
        twice, slugs2, _ = order.reorder_index(once)
        self.assertEqual(sorted(slugs), sorted(r["slug"] for r in ROWS))
        self.assertEqual((once, slugs), (twice, slugs2))
        self.assertEqual(sum(n for _, n in tiers), len(ROWS))
        self.assertEqual(once.count('class="order"'), 1)
        self.assertEqual(once.count('<tr class="tier">'), len(tiers))

    def test_write_order_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "index.html").write_text(site.index_html(ROWS, "", "http://x/cat"))
            order.write_order(Path(d))
            slugs = json.loads((Path(d) / "_assets" / "order.json").read_text())["slugs"]
        self.assertEqual(slugs[0], "odin3-micro-bm_x")
        self.assertEqual(slugs[-1], "silicon-lonely")


if __name__ == "__main__":
    unittest.main()
