"""`heimdall export|serve|site`: the Heimdall III 3D provenance viewer (spec 2026-11-05)."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from heimdall import activity, analytics, export, flows, serve, site
from heimdall.targets import asic


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the subcommands on `sub` (used by `heimdall` and by Wyrd's `wyrd viz`)."""
    vsub = sub
    ex = vsub.add_parser("export", help="write a bundle from an odin3-flow --prov run directory")
    ex.add_argument("flow", metavar="FLOW_DIR", help="odin3-flow output (prov/, odin3/, vpr/run/)")
    ex.add_argument("--out", required=True, metavar="BUNDLE_DIR")
    ex.add_argument("--benchmark", metavar="SUITE:DESIGN", help="name shown in the viewer")
    ex.add_argument(
        "--src", action="append", default=[], metavar="DIR", help="where the HDL files are"
    )
    ex.add_argument(
        "--clusters",
        type=int,
        metavar="K",
        help="clusters of the min-cut partition (default: from HDL)",
    )
    ex.add_argument(
        "--odin3",
        metavar="PATH",
        help="odin3 program for the extra dump run (default: the one in the flow's log); "
        "needs write_graph for the graph planes",
    )
    ex.add_argument(
        "--lef",
        metavar="FILE",
        help="sky130_fd_sc_hd.lef for cell areas (silicon runs; default: the workspace PDK)",
    )
    st = vsub.add_parser("site", help="build a static site of several benchmarks")
    st.add_argument("--out", required=True, metavar="DIR")
    st.add_argument("--base-url", default="", metavar="URL", help="canonical URL of the site root")
    st.add_argument(
        "specs",
        nargs="+",
        metavar="SPEC",
        help="SUITE:DESIGN=FLOW_DIR[,src=DIR][,what=TEXT][,catalogue=URL][,lef=FILE], "
        "or @FILE (one per line)",
    )
    st.add_argument(
        "--extend", metavar="OLD_SITE_DIR", help="copy an earlier site and add the specs to it"
    )
    st.add_argument(
        "--note", default="", metavar="HTML", help="paragraph for the index (with --extend)"
    )
    an = vsub.add_parser(
        "analytics",
        help="add graph analytics (graphlet signatures, clusterings) to a bundle or to every "
        "bundle of a built site",
    )
    an.add_argument("path", metavar="BUNDLE_OR_SITE_DIR")
    an.add_argument("--lef", metavar="FILE", help="sky130_fd_sc_hd.lef (default: workspace PDK)")
    an.add_argument("--odin3-python", metavar="PYTHON", help="Python with the Odin III binding")
    an.add_argument(
        "--silicon-flow",
        action="append",
        default=[],
        metavar="SLUG=FLOW_DIR",
        help="silicon run of a page built before edges/net.json existed (reads its DEF)",
    )
    an.add_argument("--only", metavar="SLUG", action="append", default=[], help="site pages to do")
    ac = vsub.add_parser(
        "activity",
        help="add the switching-activity overlay (Bifrost III power data) to the pages of a "
        "built site that have data",
    )
    ac.add_argument("site", metavar="SITE_DIR")
    ac.add_argument("--data", required=True, metavar="DIR", help="one sub-directory per design")
    ac.add_argument("--only", metavar="SLUG", action="append", default=[], help="site pages to do")
    rf = vsub.add_parser(
        "refresh", help="bring a built site up to this viewer (assets, pages, help); no flow is run"
    )
    rf.add_argument("site", metavar="SITE_DIR")
    rf.add_argument(
        "--note", default="", metavar="HTML", help="paragraph replacing the Update note"
    )
    sv = vsub.add_parser("serve", help="serve the viewer and one bundle on 127.0.0.1")
    sv.add_argument("bundle", metavar="BUNDLE_DIR")
    sv.add_argument("--port", type=int, default=8765)


def run(args: argparse.Namespace) -> int:
    """Run the parsed subcommand."""
    if args.viz_command == "export":
        return _export(args)
    if args.viz_command == "site":
        return _site(args)
    if args.viz_command == "refresh":
        n = site.refresh_site(Path(args.site), args.note)
        print(f"refreshed {n} pages in {args.site}")
        return 0
    if args.viz_command == "analytics":
        return _analytics(args)
    if args.viz_command == "activity":
        return _activity(args)
    return _serve(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="heimdall", description="Heimdall III: 3D provenance viewer"
    )
    sub = parser.add_subparsers(dest="viz_command", required=True)
    add_parser(sub)
    return run(parser.parse_args(argv))


def _export(args: argparse.Namespace) -> int:
    flow = Path(args.flow)
    try:
        man = flows.export_flow(
            flow,
            Path(args.out),
            args.benchmark or flow.name,
            [Path(s) for s in args.src],
            args.clusters,
            Path(args.odin3) if args.odin3 else None,
            Path(args.lef) if args.lef else None,
        )
    except export.ExportError as e:
        print(f"heimdall export: {e}", file=sys.stderr)
        return 2
    counts = ", ".join(f"{p} {n}" for p, n in man["counts"].items())
    print(
        f"wrote {args.out}: planes {counts}; {man['links']} links; {man['unanchored']} unanchored"
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    if not (bundle / "manifest.json").is_file():
        print(f"heimdall serve: no manifest.json in {bundle}", file=sys.stderr)
        return 2
    srv = serve.make_server(bundle, args.port)
    print(f"serving {bundle.name} at http://127.0.0.1:{srv.server_address[1]}/  (Ctrl-C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0


def _site(args: argparse.Namespace) -> int:
    try:
        specs = site.parse_specs(args.specs)
        rows = site.build_site(
            Path(args.out),
            args.base_url,
            specs,
            extend=Path(args.extend) if args.extend else None,
            note=args.note,
        )
    except (site.SiteError, export.ExportError) as e:
        print(f"heimdall site: {e}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}: {len(rows)} benchmarks")
    return 0


def _activity(args: argparse.Namespace) -> int:
    root, data = Path(args.site), Path(args.data)
    done = 0
    for m in sorted(root.glob("*/bundle/manifest.json")):
        b = m.parent
        slug = b.parent.name
        if args.only and slug not in args.only:
            continue
        tgt = activity.target_of(b)
        dd = data / activity.design_of(slug)
        if tgt is None or not (dd / "power.json").is_file():
            continue
        try:
            ds = activity.Dataset(dd)
            if not ds.has(tgt):
                print(f"{slug}: no {tgt} power in {dd}, skipped")
                continue
            entry = activity.apply(b, ds, tgt)
        except activity.ActivityError as e:
            print(f"heimdall activity: {slug}: {e}", file=sys.stderr)
            return 2
        done += 1
        print(f"{slug}: {entry['source']} on {len(entry['planes'])} planes")
    print(f"{done} pages")
    return 0


def _analytics(args: argparse.Namespace) -> int:
    root = Path(args.path)
    bridge = analytics.find_bridge(Path(args.odin3_python) if args.odin3_python else None)
    if bridge is None:
        print(
            "heimdall analytics: no Odin III binding found (set HEIMDALL_ODIN3_ROOT)",
            file=sys.stderr,
        )
        return 2
    bundles = (
        [root]
        if (root / "manifest.json").is_file()
        else sorted(m.parent for m in root.glob("*/bundle/manifest.json"))
    )
    for b in bundles:
        slug = b.parent.name if b != root else b.name
        if args.only and slug not in args.only:
            continue
        for item in args.silicon_flow:
            sl, _, fd = item.partition("=")
            if sl == slug:
                asic.write_net_edges(b, Path(fd), Path(args.lef) if args.lef else None)
        packed = bool(json.loads((b / "manifest.json").read_text(encoding="utf-8")).get("parts"))
        res = analytics.analyse_bundle(b, bridge)
        if packed:
            analytics.pack_new(b)
        print(f"{slug}: {res[0] if res else None} timing {json.dumps(res[1]) if res else ''}")
    return 0
