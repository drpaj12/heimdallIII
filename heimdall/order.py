"""Complexity order of the index (v0.9.2): tiers from micro ideas upwards, then a measured size.

The key, in one sentence (also printed on the index page): pages are grouped in tiers from the
smallest ideas to real designs (Odin III micros, HDLBits-style problems, small VTR designs,
OpenCores small / medium / large, big VTR designs), and inside a tier ordered by LUT count, then
flip-flop count, then name; a silicon page follows its FPGA twin (same design name), and a silicon
page without a twin goes last. The tier comes from the suite of the page and its LUT count, both
read from the index rows (which come from the bundle's lut plane); a page that fits no rule goes to
the tier "Other suites", never dropped.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

SMALL_LUTS = 1000  # below: "small" (VTR, OpenCores)
LARGE_LUTS = 10000  # from here: the OpenCores "large" tier

TIERS = [
    "Odin III micros (bm_*)",
    "HDLBits-style problems (Prob*)",
    "Small VTR designs",
    "OpenCores, small",
    "OpenCores, medium",
    "OpenCores, large",
    "Big VTR designs",
    "Other suites",
    "Silicon pages without an FPGA twin",
]

CSS = "tr.tier th{background:#e8eef7;padding-top:.7em}.order{color:#444}\n"

KEY_SENTENCE = (
    "Order of the pages, simplest first: tiers from micro ideas upwards (Odin III micros, "
    f"HDLBits-style problems, VTR designs under {SMALL_LUTS} LUTs, OpenCores under {SMALL_LUTS}, "
    f"{SMALL_LUTS} to {LARGE_LUTS - 1} and {LARGE_LUTS} or more LUTs, VTR designs of {SMALL_LUTS} "
    "LUTs or more), then inside a tier by LUT count, flip-flop count and name; "
    "each silicon page sits directly after its FPGA twin."
)


def tier_of(suite: str, target: str, luts: int) -> int:
    """Tier index in TIERS for one page (silicon twins are placed by `order_rows`)."""
    if suite == "odin3-micro":
        return 0
    if suite == "verilogeval":
        return 1
    if suite.startswith("vtr"):
        return 2 if luts < SMALL_LUTS else 6
    if suite == "opencores":
        return 3 if luts < SMALL_LUTS else 4 if luts < LARGE_LUTS else 5
    return 8 if target == "asic" else 7


def _size(r: dict[str, Any]) -> tuple[int, int, str]:
    return (r["luts"] or r["cells"], r["ffs"], r["design"])


def order_rows(rows: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """(tier, row) in display order. Rows need slug, suite, design, target, luts, ffs, cells."""
    fpga = [r for r in rows if r["target"] != "asic"]
    twins: dict[str, list[dict[str, Any]]] = {}
    fpga_designs = {r["design"] for r in fpga}
    asic = [r for r in rows if r["target"] == "asic"]
    orphans = []
    for r in asic:
        if r["design"] in fpga_designs:
            twins.setdefault(r["design"], []).append(r)
        else:
            orphans.append(r)
    out: list[tuple[int, dict[str, Any]]] = []
    for r in sorted(fpga, key=lambda r: (tier_of(r["suite"], "fpga", r["luts"]), _size(r))):
        t = tier_of(r["suite"], "fpga", r["luts"])
        out.append((t, r))
        out.extend((t, s) for s in sorted(twins.get(r["design"], []), key=_size))
    out.extend((8, r) for r in sorted(orphans, key=_size))
    return out


def _num(s: str) -> int:
    return int(s) if s.strip().isdigit() else 0


_ROW = re.compile(r"<tr><td><a href=\"([^\"]*)/\">[^<]*</a></td>.*?</tr>", re.S)
_CELLS = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TBODY = re.compile(r"<tbody>\n.*?</tbody>", re.S)
_ORDER_P = re.compile(r'<p class="order">.*?</p>\n', re.S)


def parse_rows(index: str) -> list[tuple[dict[str, Any], str]]:
    """The benchmark rows of an index page as (fields, original row html)."""
    out = []
    for m in _ROW.finditer(index):
        c = _CELLS.findall(m[0])
        out.append(
            (
                {
                    "slug": m[1],
                    "design": html.unescape(re.sub(r"<[^>]+>", "", c[0])),
                    "suite": html.unescape(c[1]),
                    "target": c[2],
                    "luts": _num(c[3]),
                    "ffs": _num(c[4]),
                    "cells": _num(c[5]),
                },
                m[0],
            )
        )
    return out


def reorder_index(index: str) -> tuple[str, list[str], list[tuple[str, int]]]:
    """The index with tier heading rows and the new order: (html, slugs in order, tier counts).
    Idempotent: heading rows and the key paragraph of an earlier pass are replaced."""
    parsed = parse_rows(index)
    by_slug = {f["slug"]: raw for f, raw in parsed}
    ordered = order_rows([f for f, _ in parsed])
    counts: dict[int, int] = {}
    for t, _ in ordered:
        counts[t] = counts.get(t, 0) + 1
    lines: list[str] = []
    cur = -1
    for t, r in ordered:
        if t != cur:
            cur = t
            head = f"{html.escape(TIERS[t])} ({counts[t]})"
            lines.append(f'<tr class="tier"><th colspan="9" id="tier{t}">{head}</th></tr>')
        lines.append(by_slug[r["slug"]])
    tiers = [(TIERS[t], counts[t]) for t in sorted(counts)]
    text = _TBODY.sub(lambda _m: "<tbody>\n" + "\n".join(lines) + "\n</tbody>", index, count=1)
    para = f'<p class="order">{html.escape(KEY_SENTENCE)}</p>\n'
    text = _ORDER_P.sub("", text)
    text = text.replace("<table>", para + "<table>", 1)
    if CSS not in text:
        text = text.replace("</style>", CSS + "</style>", 1)
    return text, [r["slug"] for _, r in ordered], tiers


def write_order(site: Path, aid: str = "") -> list[tuple[str, int]]:
    """Reorder site/index.html and write site/_assets/<aid>/order.json (slugs, simplest first)."""
    idx = site / "index.html"
    text, slugs, tiers = reorder_index(idx.read_text(encoding="utf-8"))
    idx.write_text(text, encoding="utf-8")
    assets = site / "_assets" / aid if aid else site / "_assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "order.json").write_text(
        json.dumps({"slugs": slugs}, indent=1) + "\n", encoding="utf-8"
    )
    return tiers
