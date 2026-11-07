# Heimdall III: the 3D provenance viewer as its own project (design, 2026-11-05)

Status: draft for the controller. No code moved yet. The move waits for the Wyrd help-page PR
(`docs/o3viz-help`, drpaj12/wyrd #55) to merge.

Purpose: a teaching and research view of what HDL becomes at every stage of a flow, hosted as a static site next to
the Mimir benchmark catalogue (Peter 2026-11-05). Research link: provenance at every granularity (Odin III
provenance files) and graph analysis of netlist structure. Measure of success: a static site with one viewer page
per chosen benchmark, a help page and an index, linked from the Mimir catalogue; `wyrd viz` still works.

Peter's name decision: Heimdall III, new public repo https://github.com/drpaj12/heimdallIII, static site on his
webpage. Lineage cited in the README: Kundarewich 2002 (MASc) and Hutton et al., as in the viewer help page.

## 1. Package layout

Python package `heimdall`, standard library only at runtime (same rule as Wyrd core), Python >= 3.11, MIT licence
(same as Wyrd). Odin III, OpenROAD and VPR are used only as programs, never imported.

```
heimdallIII/
  heimdall/
    __init__.py
    cli.py            # heimdall export | serve | site
    export.py         # flow dir -> bundle (from wyrd/o3viz/export.py)
    targets/
      fpga.py         # cell, lut, clb, placed planes (VPR .net/.place); the current code
      asic.py         # STUB: std-cell, die, route planes; raises NotImplementedError with TODO
    anchors.py anchorset.py partition.py hutton.py nets.py cells.py circuit.py circuitviz.py
    graphs.py blif.py vprfiles.py serve.py
    site.py           # static site builder (section 3)
    web/              # viewer: index.html help.html app.js ... vendor/ (three, pinned, licence kept) images/
  tests/              # test_*.py (unittest), js/*.test.mjs (node), data/ fixtures
  tools/shot.py       # screenshots (serves on 8779, must stop the server)
  docs/specs docs/plans docs/user/viz.md
  README.md LICENSE CLAUDE.md pyproject.toml
  .github/workflows/ci.yml   # ruff, mypy --strict, unittest, node tests
```

CLI: `heimdall export FLOW_DIR --out BUNDLE ...` and `heimdall serve BUNDLE [--port]` keep the current
`wyrd viz` arguments; `heimdall site` is new. `pyproject.toml` ships `web/**/*` as package data.
Dependency direction: Wyrd gets an optional extra `viz = ["heimdall"]`; `wyrd viz ...` imports `heimdall.cli`
when installed, otherwise prints how to install. Heimdall never imports Wyrd.

## 2. Two-target plane model

The bundle manifest already lists planes in order. Add one field per plane, `target`: `fpga | asic | common`.
The viewer, anchors and joins read only the plane list, the links and the per-plane position tables. They must
not assume LUTs, clusters or a VPR grid. Rules:

- `common` planes: HDL (AST objects, spans), graph planes (STG, CFG, DDG), and the technology-independent cell
  plane (Odin III generic cells). These appear for both targets.
- `fpga` planes (today's code): `lut` (mapped LUTs and FFs), `clb` (clusters), `placed` (atoms on the VPR grid;
  coordinates are integer grid sites).
- `asic` planes (from the Odin III silicon flow, `odin3 docs/user/silicon-flow.md`; Odin III to OpenROAD to GDS,
  `sky130_fd_sc_hd`):
  - `stdcell`: cells mapped with `abc --gates` and `dfflibmap`; one row per standard-cell instance, `type` =
    library cell name, metrics area, drive, power-pin counts.
  - `die`: the placed cells; real coordinates in micrometres on the die (`x`, `y`, orientation, row), die and
    core bounds in the manifest. Unit and origin are declared in the plane header, not assumed.
  - `route` (optional): nets as polylines per layer; metrics wire length, via count, layer use.
  - Provenance: the `recover` step joins extracted cells (Magic, Netgen LVS) back to placed cells and so to the
    HDL. That join becomes the `die` -> `stdcell` -> `cell` -> `hdl` links, with the same confidence field.
- Manifest additions: `target` per plane; `flow` already exists (`vtr` or `silicon`); plane header gains
  `coord`: `{kind: "grid"|"um", unit, origin, bounds}`. A bundle may hold planes of one target plus `common`.
  A later two-target bundle (same design through both flows) is allowed; planes then carry distinct ids.
- Anchors: `placement` means "bottom plane is the real physical layout" for either target (VPR grid or die);
  `ast`, `pipeline` and `level` use only links and graph structure and need no change.
- Metric catalogue entries already name the planes they apply to; add `target` filtering so the UI only offers
  metrics for planes present.
- `heimdall/targets/asic.py` (update 5) reads an Odin III silicon-flow run: the prov step files (read, map, place, recover), `or/route.def`
  (DEF: die, rows, components, nets with routes), `or/s04_global_place.csv` and the sky130 LEF (cell areas). It writes the planes `stdcell`,
  `die`, `route` and the anchors `placement` (final legal place) and `global`. `heimdall export` picks the target from `prov/index.json`
  (`flow` = `silicon-*`). Details: `docs/user/viz.md`, "Update 5". Not built: a `cell` plane (the silicon prov links gates to HDL statements).

## 3. Static site builder

`heimdall site --out DIR --base-url URL SPEC...` where a SPEC is `suite:design=FLOW_DIR[,src=DIR]` or a list file.

```
DIR/
  index.html            # table: name, suite, LUTs, FFs, what it does, viewer link, Mimir catalogue row link
  <suite>-<design>/
    index.html          # the viewer (same web/ assets; shared assets are copied once under DIR/_assets and referenced)
    help.html
    bundle/manifest.json, planes/*.json.gz parts ...
```

- Bundles are exported once, then each large JSON file is gzipped and split into parts of at most 40 MB
  compressed (hard limit 50 MB per file; sha's bundle is about 90 MB raw). A part list is written into the
  manifest (`parts`: ordered file names and sha256).
- The viewer fetches parts and decompresses with `DecompressionStream("gzip")`; the loader (`loadBundle`) is the
  single place to change. Fallback for browsers without it: plain `.json` is not shipped; the help page states the
  browser requirement (current Chrome, Firefox, Safari).
- No server is needed: works from any static host. `python -m http.server` is used only for testing and is stopped
  afterwards. Links are relative; `--base-url` is only used for the absolute canonical links and the Mimir link
  back.
- Output is deterministic (sorted keys, fixed gzip mtime = 0) so rebuilds diff cleanly.
- The index reads LUT/FF counts and the description from the bundle manifest, and the catalogue anchor from the
  Mimir design name (`catalogue.html#<design>`).

## 4. Benchmark selection (first site)

Rule, deterministic. Source: Mimir `data/benchmarks/measures.tsv`, suite `verilogeval`, key `l6_luts`
(6-LUT count). 154 of the 156 designs have a value (two failed `read_slang`; they are excluded and listed in the
README). Sort ascending by (l6_luts, design name). Cut into four quartiles by rank (rank/154 rounded: sizes 38,
39, 39, 38). In each quartile take the median design (index len//2) and its two neighbours. 12 designs:

| quartile | LUT range | designs (LUTs) |
|---|---|---|
| Q1 | 0-1 | Prob010_mt2015_q4a (1), Prob011_norgate (1), Prob012_xnorgate (1) |
| Q2 | 1-3 | Prob009_popcount3 (2), Prob024_hadd (2), Prob025_reduction (2) |
| Q3 | 3-10 | Prob142_lemmings2 (4), Prob086_lfsr5 (5), Prob096_review2015_fsmseq (5) |
| Q4 | 10-1966 | Prob123_bugs_addsubz (22), Prob154_fsm_ps2data (28), Prob066_edgecapture (32) |

Note: the quartile ranges are low because the suite is mostly tiny; the Mimir catalogue has no `vtr_stage`
measure for these yet, so the flow run (one at a time) is the first test that they reach VPR. A pick that fails
the VTR flow is replaced by the next neighbour in rank order and the README says so.

Odin III micros: `odin3/tests/micro/verilog/micro/*.v` (68 files; one construct each, from the VTR odin_ii
regression set). Candidates are the ones in `tests/hardmap/micros.txt` plus a hand pick of one per construct
class (mux, encoder, adder, shift register, flip-flop, ALU, FSM-like, latch, generate, parameter, multiply). The
final list is fixed when the flows are run, by the rule "the flow reaches `route`", and recorded in the README.
Keep `ch_intrinsics` and `sha` (existing demos; sha via `tools/heavy-run`).

Flows: Odin III binary `/home/jamiespa/odin3-ws/odin3/build/rel-main3` (main e5efb64e; not rebuilt), small runs
one at a time under `systemd-run --user --scope -p MemoryMax=4G`, outputs under
`/home/jamiespa/odin3-ws/work/heimdall-runs/`.

## 5. Links

- Mimir (PR to mimirIII, worktree `work/mimir-heimdall`): add a `view` column in `catalogue.md` and `.html` for
  rows with a Heimdall page. The URL is `<heimdall_base_url>/<suite>-<design>/`, with `heimdall_base_url` a config
  key (`https://drpeterjamieson.com/RESEARCH/HEIMDALL/`; empty = no column links). Mimir stays free of Heimdall code.
- Yggdrasil hub (PR to drpaj12/YggdrasilIII, worktree `work/ygg-heimdall`): `heimdallIII` as submodule under
  `components/` like the others; add Heimdall III to `docs/` (architecture, pieces, features, versions) and to the
  tree picture. The picture is TikZ: `images/src/fig_yggdrasil.tex`, rendered by `make` in `images/` (needs
  latexmk and the venv python); add a node and a line connecting the Wyrd III node and the Mimir III fruit, then
  regenerate `yggdrasil-tree.{png,svg}`. Read the figure source before editing; keep the existing styles.

## 6. Move plan

Preconditions: Wyrd PR #55 merged. Worktrees: `work/wyrd-heimdall-move` (Wyrd side), `/home/jamiespa/odin3-ws/heimdall`
(this repo). `git filter-repo` is not installed (`python3 -c "import git_filter_repo"` fails) and nothing is
installed. Method, in order of preference: (a) `git subtree split --prefix=wyrd/o3viz` per path and merge the
split histories with `--allow-unrelated-histories`; (b) a scripted `git log --follow` replay of each path as
commits with original author and date. Paths: `wyrd/o3viz/`, `tests/test_o3viz*.py`, `tests/js/*`,
`tests/data/o3viz/`, `tools/o3viz_shot.py`, `docs/user/viz.md` and images, `docs/specs/2026-11-03-o3viz-design.md`,
`docs/plans/2026-11-03-o3viz-plan.md`, the help page and its images. Then rename `wyrd.o3viz` to `heimdall`, the
`wyrd viz` text to `heimdall`, and move files to the layout in section 1.

Because this spec lands first, `main` of heimdallIII starts with a README stub; the history merge uses
`--allow-unrelated-histories`. After the first move push, changes go by PR only (draft while working, ready at
the end, merged with `mw.sh`).

Wyrd side: delete `wyrd/o3viz/`, moved tests, tools and docs; `wyrd/vizcli.py` becomes a thin shim for
`wyrd viz` (calls `heimdall.cli.main` when importable, else prints `pip install heimdall` or the repo URL and exits
2); `pyproject.toml` adds extra `viz`; `docs/user/viz.md` becomes a short pointer. Both repos stay green
(ruff, mypy --strict, unittest, node tests; Wyrd's wrapper test covers the missing-package message).

Order of work after the green light: move + CI + README; site builder; flows and the 14-ish site build; Mimir PR;
Yggdrasil PR; report.

## 7. Decisions (Peter 2026-11-05)

1. `heimdall_base_url = https://drpeterjamieson.com/RESEARCH/HEIMDALL/`, Heimdall's own directory next to the Mimir
   material on Peter's webpage. Peter uploads the built site directory there; nothing is uploaded by the tools.
2. Not published to PyPI. Local package `heimdall`, project name heimdallIII.

## 8. Graph analytics (update 6, 2026-11-06)

Purpose: graph analysis of netlist structure linked to HDL (Peter 2026-11-06); research question: are structure
signatures usable as reverse-engineering hints. Measure: per page the analytics load in under 30 s, 0 console
errors, and every cluster, orbit or signature selection lights objects on all planes and HDL lines.

Counting and metrics belong to Odin III and are never reimplemented here. The exporter calls Odin III through a
bridge program (`tools/odin3_glet_bridge.py`), run as a subprocess with the Python that has the Odin III binding
(`--odin3-python`, default `$HEIMDALL_ODIN3_PYTHON` or the Odin III checkout's `.venv`) and `ODIN3_LIB`. The
`heimdall` package never imports the binding. The bridge reads one JSON job on stdin and writes the result on
stdout: `count` (edge list to orbit rows, `odin3_graphlets_count`) and `compare` (two signature files,
`graphlets --compare`: GDD agreement and cosine of log(1 + orbit totals)). Heimdall writes only the signature
file layout of schema `odin3-graphlets` (`mode`, `n_orbits`, `groups[{name, reported, orbit_totals, gdd}]`); the
GDD histogram is a count of nodes per (orbit, count) taken from the rows Odin III returned.

Graphs (nodes = the plane's objects, edges = driver to sink, simple graph, self loops dropped):
`lut` (BLIF nets), `placed` (BLIF nets over atoms incl. pads), `clb` (LUT edges lifted through the pack links),
`die` and `stdcell` (DEF nets; driver from the LEF pin direction, else the pin named X, Y, Q, Q_N, SUM, COUT),
`ddg`, `cfg`, `stg` (write_graph edges), `cell` when the plane has no edges is skipped with a note. Two
signatures per node: undirected size 5 (73 orbits, Przulj) and directed size 4 (129 orbits, Sarajlic style, Odin
III numbering). The `--exclude-global` rule of the pass (nets of fan-out 16 or more give no edges) is applied
to the netlist graphs before counting and recorded.

Bundle files (all optional; absent = no analytics): `analytics/index.json` (parameters, seed, per plane: node
and edge counts, count seconds, features, clusterings, signature sets, compare matrices, notes) and
`analytics/<plane>.json` (`ids` order = plane order; `gdv_u`, `gdv_d` rows of ints; `pos` x,y when the plane has
placement). Also `analytics/partition.<plane>.<feature>.<alg>.tsv`: `name<TAB>cluster` plus a `# params` header,
importable into Mimir's partition table (file only).

Clustering (stdlib, seed 20261106 in the manifest): k-means (k-means++, k in 2, 4, 8, 16, 32 capped by the
number of distinct vectors; silhouette per k on at most 1500 sampled points; default = best silhouette) and
affinity propagation (similarity = negative squared distance, preference = median, damping 0.9, 200 iterations,
on distinct vectors weighted by multiplicity; cap 400 distinct vectors: if more, the 400 most frequent are
clustered and every other vector joins the nearest exemplar; stated on the page). Features: undirected GDV
log1p, directed GDV log1p, x/y (placement planes `placed`, `clb`, `die`).

Viewer: panel "Graph analytics" with (1) orbit heat (plane colour by log1p of one orbit, mode u or d), (2)
clustering (feature, algorithm, k; cluster colours from the rainbow palette, list with sizes; a click makes the
cluster an update-4 group, lighting all planes and HDL lines), (3) signature compare of two named groups
(clusters of the shown clustering plus the current update-4 groups are signed on demand only when precomputed;
the metrics come only from Odin III results in the bundle). Ad hoc selections are signed by the exporter for
clusters only; this limit is stated in the panel.

## 12. Switching-activity overlay (update 7, 2026-11-07)

Purpose: show where a design's testbench makes nets toggle and where the power goes, on every plane and per HDL line
(RQ: structure and activity as RE hints; measure: static probability, transition density, power in watts). Heimdall
draws what Bifrost III measured (Wyrd spec `docs/specs/2026-11-06-bifrost-power-design.md`, schema version 1); it never
recomputes activity or power.

Input, one directory per design (`heimdall activity SITE_DIR --data DIR`; the design is the page slug after the first
dash, the target is fpga for a `vtr` flow and asic for a `silicon` flow):
- `power.json`: Bifrost schema v1 (totals, by_line for the FPGA model, by_line_asic).
- `activity.csv`: FPGA nets, `net,name,file,line,p1,activity,source` (Bifrost's file).
- `asic_nets.csv`: `net,p1,activity` of the gate-level run on the silicon `final.v`.
- `asic_inst.csv`: `inst,dyn_w,static_w,out_net,file,line` (OpenROAD per-instance power; out_net from `final.v`; file and
  line from the silicon flow `prov.csv`). Wyrd writes the first two files; the last two need a small driver around
  `wyrd.bifrost.power.flow` (kept outside both repos) until Wyrd emits them.

Output: `bundle/activity/activity.json` (packed like the other files) and `manifest["activity"]`
(`target`, `source`, `source_label`, `planes`); manifest metrics `act_p1` (P(1)), `act_td` (toggles per cycle),
`act_pw` (microwatts), the last two with `clip` 0.98 (the viewer ends the colour range at that quantile).
The file holds one column per plane per metric aligned with the plane `ids`, plus `basis` per object.

Join, in order, per object: (net) its name is a net or instance Bifrost measured, on the target's own planes (FPGA lut and
placed; ASIC die, stdcell, route); (line) the first span's line range in the per-line table built from Bifrost's
file:line per net or instance (mean P(1) and activity; power only on hdl objects, as Bifrost gave it); (link) the mean of
linked objects that have a net or line value (ASIC power: from one linked plane, summed for hdl objects). Anything else is
null (grey). The FPGA pages were built from an Odin III flow netlist that differs from Bifrost's own synthesis (soft
adders, `flatten`), so on FPGA pages part of the objects take the line or link basis; the viewer reports counts per plane
and offers "exact name matches only".

Labelled in the panel, from Bifrost: the activity source (iverilog gate-level, Odin III replay, vectorless), the FPGA
per-line power is a model, the ASIC split is per instance, ASIC clock power is the clock-tree cells (a lower bound),
glitch power is not counted, activity is that of one testbench. A page with no `activity` in its manifest says so.
Check: `tools/activity_check.py` (load time, console errors, measured objects on every listed plane per colour, a line click).
