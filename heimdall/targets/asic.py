"""ASIC target (Odin III silicon flow: Odin III -> OpenROAD -> GDS, sky130_fd_sc_hd). STUB.

Planes (spec 2026-11-05 section 2):
- `stdcell`: one row per standard-cell instance mapped by `abc --gates` and `dfflibmap`;
  `type` is the library cell name; metrics area, drive, pin counts.
- `die`: the placed cells with real coordinates in micrometres (x, y, orientation, row);
  die and core bounds go in the manifest `coord` header (`kind: "um"`).
- `route` (optional): nets as polylines per layer; metrics wire length, via count, layer use.
- links `die` -> `stdcell` -> `cell` -> `hdl` come from the `recover` step (Magic extraction,
  Netgen LVS, the name-free join), with the same confidence field as the FPGA links.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from heimdall.targets import ASIC_PLANES

PLANES = ASIC_PLANES

STDCELL_COLUMNS = ("id", "kind", "type", "origin", "name", "area_um2", "drive", "pins")
DIE_COLUMNS = ("id", "kind", "type", "origin", "name", "x_um", "y_um", "orient", "row")


def export_asic(flow: Path, out: Path) -> dict[str, Any]:
    """Write the ASIC planes of an `odin3-flow --silicon` run into the bundle `out`."""
    raise NotImplementedError("TODO: ASIC exporter, a later lane after the silicon flow work")
