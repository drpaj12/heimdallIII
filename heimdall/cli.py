"""`heimdall export|serve|site`: the Heimdall III 3D provenance viewer (spec 2026-11-05)."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from heimdall import export, serve, site


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
    st = vsub.add_parser("site", help="build a static site of several benchmarks")
    st.add_argument("--out", required=True, metavar="DIR")
    st.add_argument("--base-url", default="", metavar="URL", help="canonical URL of the site root")
    st.add_argument(
        "specs",
        nargs="+",
        metavar="SPEC",
        help="SUITE:DESIGN=FLOW_DIR[,src=DIR][,what=TEXT][,catalogue=URL], or @FILE (one per line)",
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
        man = export.export_bundle(
            flow,
            Path(args.out),
            args.benchmark or flow.name,
            [Path(s) for s in args.src],
            args.clusters,
            Path(args.odin3) if args.odin3 else None,
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
        rows = site.build_site(Path(args.out), args.base_url, specs)
    except (site.SiteError, export.ExportError) as e:
        print(f"heimdall site: {e}", file=sys.stderr)
        return 2
    print(f"wrote {args.out}: {len(rows)} benchmarks")
    return 0
