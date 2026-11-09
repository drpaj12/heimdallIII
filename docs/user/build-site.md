# Build a Heimdall III site and package a release

A site is a plain directory of static files built from several bundles. This page covers the whole path: flow runs,
specs, `heimdall site`, extending and refreshing a site, checks, and packaging a release. Commands were checked
against Heimdall III v0.9.3.

Needs: Heimdall installed (README), Odin III 1.5.0 or later with the `odin3-flow` tools, and VPR for the FPGA pages.
Where to get Odin III, VTR and the other outside tools, with versions: the hub page
[docs/tools.md](https://github.com/drpaj12/YggdrasilIII/blob/main/docs/tools.md). The pages of the published site
were made with Odin III 1.5.1 to 1.6.0 and the VTR 9 k6 architecture; a page records its own flow in `manifest.json`.

## 1. One flow run per page

For each design (HDL files `DIR/design.v`):

    odin3-flow DIR/design.v --prov --keep-results --out RUNS/design
    odin3-prov-post RUNS/design
    odin3-prov-steps RUNS/design

Large designs: run them one at a time under a memory cap, for example
`systemd-run --user --scope -q -p MemoryMax=4G -p MemorySwapMax=0 odin3-flow ...`. Odin III options and the silicon
(ASIC) flow are in the Odin III manual, https://drpaj12.github.io/odin3/.

## 2. A spec per page

A spec is `SUITE:DESIGN=FLOW_DIR[,src=DIR][,what=TEXT][,catalogue=URL][,lef=FILE]`. Put one per line in a file and
pass `@FILE`; the same specs can be given on the command line. Example `specs.txt`:

    vtr-verilog:ch_intrinsics=RUNS/ch_intrinsics,src=DIR,what=memory initialisation FSM
    odin3-micro:bm_DL_74381_ALU=RUNS/alu,src=MICRO_DIR,what=4-bit ALU

`SUITE:DESIGN` becomes the page name (`SUITE-DESIGN`). The order of the specs is the order of the index inside its tier.
`lef=FILE` (sky130_fd_sc_hd.lef) gives cell areas on silicon pages.

## 3. Build

    heimdall site --out SITE --base-url https://example.org/HEIMDALL/ @specs.txt

`SITE` then holds `index.html`, `help.html`, `guide.html`, `_assets/` (the viewer, shared) and one directory per page
with `index.html`, `help.html` and `bundle/`. A bundle is cut into gzip parts of at most 40 MB, so no file passes
the 50 MB limit of common static hosts. `--base-url` is the canonical URL of the site root.

Add graph analytics to every page (needs the Odin III Python binding; see the README, `HEIMDALL_ODIN3_ROOT`), and the
switching-activity overlay where you have activity data (one sub-directory per design):

    heimdall analytics SITE
    heimdall activity SITE --data ACTIVITY_DIR

## 4. Extend or refresh

Add pages to an earlier site without rerunning the old ones (the old directory is copied, the new specs added):

    heimdall site --out SITE2 --extend SITE --note "<p>New: ...</p>" @new-specs.txt

After a Heimdall update, bring the viewer, the pages' HTML and the help up to date on a built site; no flow is run:

    heimdall refresh SITE [--note HTML]

## 5. Check

- `python -m http.server 8779 --bind 127.0.0.1` in `SITE`, open `http://127.0.0.1:8779/`, then stop the server.
  Use a port that is not in use by anything else.
- The page-load check used for releases: `python tools/help_shots.py SITE OUT_DIR` and `python tools/guide_shots.py
  SITE OUT_DIR` (need `playwright` and its Chromium; they serve `SITE` on port 8779 for the run only, exit code 1 on a
  console error) also retake the screenshots of the help page and the guide when the viewer changed. The shot list of
  the guide is `tools/guide_shot_list.py`.
- No file over 50 MB, no symlinks, no absolute home paths in the pages: `find SITE -size +49M`, `find SITE -type l`,
  `grep -rl "/home/" SITE --include=*.html --include=*.js`.

## 6. Package and upload

A release is always the FULL site, not a delta, so one copy is enough. Make a directory holding:

- `site/`: the whole site;
- `HEIMDALL-full-vX.Y.Z.zip`: the same files zipped with no wrapper directory (`cd site && zip -r ../HEIMDALL-full-vX.Y.Z.zip .`);
- `UPLOAD.txt`: the version and date, which earlier release it supersedes, where to copy it (over the site folder on
  the host, overwrite, nothing to delete), what changed since the last release, the size (pages, files, largest file)
  and the checks done;
- `SHA256SUMS`: `sha256sum` of the zip and of every file in `site/`, so `sha256sum -c SHA256SUMS` in that directory
  verifies it.

New viewer features also get a "What's new (vX.Y)" section in `heimdall/web/help.html` and `heimdall/web/guide.html`,
and a row in the version table of [viz.md](viz.md). The version lives in one place, `heimdall/__init__.py`. After a
release is packaged and merged, tag it (`git tag vX.Y.Z`).

The published site is static files only; there is no server code, and nothing is uploaded by the tools.
