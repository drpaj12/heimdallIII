"""Targets of a bundle: which flow the planes come from (fpga, asic) or both (common).

The manifest lists planes in order and, in `plane_targets`, the target of each plane. The
viewer, the anchors and the links never assume LUTs, clusters or a VPR grid; only the plane
list, the links and the per-plane position tables (`coord`) matter.
See docs/specs/2026-11-05-heimdall-design.md section 2.
"""

from __future__ import annotations

from typing import Any

TARGETS = ("fpga", "asic", "common")

# Planes of the FPGA flow (VPR) and the planes shared by every flow.
FPGA_PLANES = ("lut", "clb", "placed")
COMMON_PLANES = ("stg", "cfg", "ddg", "hdl", "cell")
# Planes of the ASIC flow (Odin III -> OpenROAD -> GDS, sky130_fd_sc_hd); exporter: later lane.
ASIC_PLANES = ("stdcell", "die", "route")


def plane_target(plane: str) -> str:
    """The target of a plane name; unknown planes are `common`."""
    if plane in FPGA_PLANES:
        return "fpga"
    if plane in ASIC_PLANES:
        return "asic"
    return "common"


def plane_targets(planes: list[str]) -> dict[str, str]:
    return {p: plane_target(p) for p in planes}


def coord_headers(planes: list[str], grid: list[int] | None) -> dict[str, dict[str, Any]]:
    """Coordinate system of each plane with real positions: the FPGA grid, or the die in um."""
    out: dict[str, dict[str, Any]] = {}
    if grid is not None and "placed" in planes:
        out["placed"] = {"kind": "grid", "unit": "site", "origin": [0, 0], "bounds": list(grid)}
    return out
