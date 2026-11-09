# Heimdall III

The watchman who sees all nine worlds and guards the Bifrost. Heimdall III is the 3D provenance viewer of
Yggdrasil III: one benchmark as a stack of planes, from the HDL down to the placed chip, with every object linked
to the HDL line it came from. It was `o3viz` inside Wyrd III and is now its own project, with its history kept.

![Heimdall III on VTR ch_intrinsics](docs/user/images/o3viz-ch_intrinsics.png)

Purpose: teaching and research view of what HDL becomes at every stage of a flow (provenance at every
granularity; graph analysis of netlist structure). Two targets by design: the FPGA flow (LUT, cluster, placed
atoms on the VPR grid) today, and the ASIC flow (Odin III, OpenROAD, GDS, `sky130_fd_sc_hd`) later; the ASIC
exporter is a stub (`heimdall/targets/asic.py`). Spec: `docs/specs/2026-11-05-heimdall-design.md`.

## Install

Python 3.11 or later; the runtime uses the standard library only.

    python3 -m venv .venv
    .venv/bin/pip install git+https://github.com/drpaj12/heimdallIII.git     # or: git clone ..., then pip install .
    .venv/bin/heimdall --help

To make bundles you also need Odin III 1.5.0 or later (`odin3`, `odin3-flow`, `odin3-prov-post`, `odin3-prov-steps`;
the graph analytics also need its Python binding, found from `$HEIMDALL_ODIN3_ROOT`, an Odin III checkout) and VPR for
the FPGA pages. Install those from https://github.com/drpaj12/odin3 (manual: https://drpaj12.github.io/odin3/); the
other outside tools and their versions are on the hub page
https://github.com/drpaj12/YggdrasilIII/blob/main/docs/tools.md. Viewing an existing bundle or site needs none of them.

## Use

    heimdall export RUN_DIR --out design.o3viz --benchmark suite:design --src HDL_DIR
    heimdall serve design.o3viz                 # http://127.0.0.1:8765/ ; --port N for another ; Ctrl-C to stop
    heimdall site --out SITE --base-url https://example.org/HEIMDALL/ SPEC...
    heimdall analytics SITE                     # graph analytics on every page (needs the Odin III binding)
    heimdall activity SITE --data DIR           # switching-activity overlay
    heimdall refresh SITE                       # new viewer on a built site, no flow run

`RUN_DIR` is an `odin3-flow --prov --keep-results` run after `odin3-prov-post` and `odin3-prov-steps`.
Details, controls and screenshots: `docs/user/viz.md`; build a site and package a release: `docs/user/build-site.md`;
the viewer has its own help page (press `?`) and a worked guide (`guide.html` on a built site).
Current version: v0.9.3 (`heimdall.__version__`).

## The site

The built site is a plain directory of static files (no server code). It is published at
`https://drpeterjamieson.com/RESEARCH/HEIMDALL/` (the `--base-url`); the Mimir III catalogue links each design that has
a page there. Nothing is uploaded by the tools. How a site is built, extended, checked and packaged as a full release:
`docs/user/build-site.md`.

Current site (v0.9.3): 60 pages in tiers from simple to complex, smallest first inside each tier: Odin III micros (one
construct each, 15 pages), HDLBits-style problems (12 VerilogEval problems chosen by size quartile), VTR designs
(`ch_intrinsics`, `sha`), and OpenCores designs (24 FPGA pages and seven `silicon-` ASIC pages). Pages were built from
`odin3-flow --prov` runs of Odin III 1.5.1 to 1.6.0 with the VPR k6 architecture, one at a time under a 4 GB memory
cap. A design whose flow fails, or whose exporter fails, has no page; the list of pages is the site index. The viewer's
help page and guide say what each release added.

## Citations

- P. D. Kundarewich, "Synthetic Circuit Generation Using Clustering and Iteration", MASc thesis, University of
  Toronto, 2002 (Comb and Latched matrices, sections 2.1, 3.1 to 3.3, 5.1).
- M. Hutton, J. Rose, J. Grossman and D. Corneil, "Characterization and parameterized generation of synthetic
  combinational circuits", IEEE TCAD 17(10):985-996, 1998, and M. Hutton, J. Rose and D. Corneil, "Generation of
  synthetic sequential benchmark circuits", FPGA 1997; used as the thesis describes them.
- J. Rose et al., "The VTR project", 2012, and VTR 9 (TRETS 2025), for the flow the FPGA planes come from.

## Licence

MIT, as Wyrd III. three.js is vendored under `heimdall/web/vendor` (MIT, licence file kept).
