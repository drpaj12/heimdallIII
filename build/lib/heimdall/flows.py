"""One entry point for both targets: a VPR flow run (fpga) or a silicon flow run (asic)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from heimdall import export
from heimdall.targets import asic


def is_silicon(flow: Path) -> bool:
    """True when the run's provenance index says the flow is the Odin III silicon flow."""
    idx = flow / "prov" / "index.json"
    if not idx.is_file():
        return False
    try:
        return str(json.loads(idx.read_text(encoding="utf-8")).get("flow", "")).startswith(
            "silicon"
        )
    except (OSError, ValueError):
        return False


def export_flow(
    flow: Path,
    out: Path,
    benchmark: str,
    src_dirs: list[Path],
    clusters_k: int | None = None,
    odin3: Path | None = None,
    lef: Path | None = None,
) -> dict[str, Any]:
    if is_silicon(flow):
        return asic.export_asic(flow, out, benchmark, src_dirs, lef)
    return export.export_bundle(flow, out, benchmark, src_dirs, clusters_k, odin3)
