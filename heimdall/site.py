"""Static site builder: `heimdall site --out DIR --base-url URL SPEC...` (spec 2026-11-05, 3).

Layout of DIR:
  index.html              table of the benchmarks
  help.html, guide.html   the one help page and the "How to use" guide (images in _assets/images)
  _assets/                viewer assets shared by every benchmark (app.js, vendor/, images/, ...)
  <suite>-<design>/       index.html (viewer), bundle/ (manifest.json plus gzip parts)

Every bundle JSON file is gzipped (mtime 0, so rebuilds are byte-identical) and cut into parts
of at most PART_BYTES; the manifest `parts` map lists the parts of each file in order. The
viewer joins and gunzips them.
Links are relative, so the site works from any static host. Standard library only.
"""

from __future__ import annotations

import gzip
import html
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from heimdall import __version__, analytics, flows
from heimdall.serve import WEB

PART_BYTES = 40_000_000  # hard limit per file is 50 MB
DEFAULT_CATALOGUE = "https://drpaj12.github.io/mimirIII/benchmarks/catalogue.html"
BASE_URL_DEFAULT = "https://drpeterjamieson.com/RESEARCH/HEIMDALL/"


class SiteError(Exception):
    pass


@dataclass(frozen=True)
class Spec:
    suite: str
    design: str
    flow: Path
    src: tuple[Path, ...] = ()
    what: str = ""
    catalogue: str = ""
    lef: Path | None = None

    @property
    def slug(self) -> str:
        return f"{self.suite}-{self.design}"


def parse_spec(text: str) -> Spec:
    """`SUITE:DESIGN=FLOW_DIR[,src=DIR][,what=TEXT][,catalogue=URL]` (no comma inside values)."""
    head, sep, rest = text.partition("=")
    suite, colon, design = head.partition(":")
    if not (sep and colon and suite and design):
        raise SiteError(f"bad spec {text!r}: want SUITE:DESIGN=FLOW_DIR[,key=value...]")
    fields = rest.split(",")
    src: list[Path] = []
    what = catalogue = ""
    lef: Path | None = None
    for f in fields[1:]:
        k, _, v = f.partition("=")
        if k == "src":
            src.append(Path(v))
        elif k == "what":
            what = v
        elif k == "catalogue":
            catalogue = v
        elif k == "lef":
            lef = Path(v)
        elif what and "=" not in f:
            what += "," + f  # a comma inside the description
        else:
            raise SiteError(f"bad spec {text!r}: unknown key {k!r}")
    return Spec(suite, design, Path(fields[0]), tuple(src), what, catalogue, lef)


def parse_specs(args: list[str]) -> list[Spec]:
    """Each argument is a spec, or `@FILE` with one spec per line (blank and `#` lines skipped)."""
    out: list[Spec] = []
    for a in args:
        if a.startswith("@"):
            for line in Path(a[1:]).read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    out.append(parse_spec(line.strip()))
        else:
            out.append(parse_spec(a))
    slugs = [s.slug for s in out]
    if len(set(slugs)) != len(slugs):
        raise SiteError("duplicate benchmark in specs")
    return out


def pack_bundle(bundle: Path, dest: Path, part_bytes: int = PART_BYTES) -> dict[str, list[str]]:
    """Copy `bundle` to `dest`: JSON files become gzip parts, other files (hdl/) are copied.
    Returns the manifest `parts` map; manifest.json itself stays plain and gets the map."""
    parts: dict[str, list[str]] = {}
    for f in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = f.relative_to(bundle).as_posix()
        if rel == "manifest.json":
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix != ".json":
            shutil.copyfile(f, out)
            continue
        blob = gzip.compress(f.read_bytes(), compresslevel=9, mtime=0)
        names = []
        for i in range(0, max(len(blob), 1), part_bytes):
            name = f"{rel}.gz.{i // part_bytes:03d}"
            (dest / name).write_bytes(blob[i : i + part_bytes])
            names.append(name)
        parts[rel] = names
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    man["parts"] = parts
    (dest / "manifest.json").write_text(
        json.dumps(man, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return parts


def lut_ff_counts(bundle: Path) -> tuple[int, int]:
    """(LUTs, flip-flops) from the lut plane of an exported bundle: type `latch` is a flip-flop."""
    path = bundle / "planes" / "lut.json"
    if not path.is_file():
        return 0, 0
    types = json.loads(path.read_text(encoding="utf-8")).get("type", [])
    ffs = sum(1 for t in types if t == "latch")
    return len(types) - ffs, ffs


def _viewer_page(text: str) -> str:
    return (
        text.replace("./vendor/", "../_assets/vendor/")
        .replace("./app.js", "../_assets/app.js")
        .replace('href="help.html"', 'href="../help.html"')
    )


def version_label() -> str:
    """The label of `heimdall.__version__` (the one place): v0.7 for 0.7.0, v0.7.1 for 0.7.1."""
    v = __version__[:-2] if __version__.endswith(".0") else __version__
    return f"v{v}"


def _root_page(text: str) -> str:
    """help.html and guide.html live at the site root; their pictures are in _assets/images."""
    text = text.replace('src="images/', 'src="_assets/images/')
    return text.replace("@@VERSION@@", version_label())


_TRY = re.compile(r'<a class="tryit" href="@([^/"]+)/([^"]*)">(.*?)</a>', re.S)


def guide_page(text: str, slugs: set[str]) -> str:
    """Try-it links are written `@SLUG/?query` in the template; a benchmark that is not in this
    build loses its link (so every link in the built site resolves)."""

    def fix(m: re.Match[str]) -> str:
        slug, rest, label = m.groups()
        if slug in slugs:
            return f'<a class="tryit" href="{slug}/{rest}">{label}</a>'
        note = f"benchmark {html.escape(slug)} is not in this build"
        return f'<span class="tryit dim">{label} ({note})</span>'

    return _TRY.sub(fix, _root_page(text))


def copy_assets(out: Path) -> None:
    assets = out / "_assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(
        WEB, assets, ignore=shutil.ignore_patterns("index.html", "help.html", "guide.html")
    )


def build_one(
    spec: Spec, out: Path, work: Path, bridge: analytics.Bridge | None = None
) -> dict[str, Any]:
    raw = work / spec.slug
    man = flows.export_flow(
        spec.flow, raw, f"{spec.suite}:{spec.design}", list(spec.src), lef=spec.lef
    )
    analytics.analyse_bundle(raw, bridge)
    bench = out / spec.slug
    bench.mkdir(parents=True, exist_ok=True)
    pack_bundle(raw, bench / "bundle")
    (bench / "index.html").write_text(
        _viewer_page((WEB / "index.html").read_text(encoding="utf-8")), encoding="utf-8"
    )
    luts, ffs = lut_ff_counts(raw)
    asic = man.get("asic")
    if asic:
        std = json.loads((raw / "planes" / "stdcell.json").read_text(encoding="utf-8"))["metrics"]
        luts, ffs = 0, sum(1 for v in std.get("is_ff", []) if v)
    return {
        "target": "asic" if asic else "fpga",
        "cells": man["counts"].get("stdcell", 0),
        "die": f"{asic['die_um'][0]:.0f} x {asic['die_um'][1]:.0f}" if asic else "",
        "slug": spec.slug,
        "suite": spec.suite,
        "design": spec.design,
        "luts": luts,
        "ffs": ffs,
        "what": spec.what,
        "catalogue": spec.catalogue,
        "planes": man["planes"],
    }


def index_html(rows: list[dict[str, Any]], base_url: str, catalogue: str) -> str:
    e = html.escape
    body = []
    for r in rows:
        cat = r["catalogue"] or f"{catalogue}#{r['design']}"
        body.append(
            f'<tr><td><a href="{e(r["slug"])}/">{e(r["design"])}</a></td><td>{e(r["suite"])}</td>'
            f"<td>{e(r.get('target', 'fpga'))}</td>"
            f'<td class="n">{r["luts"] or ""}</td><td class="n">{r["ffs"]}</td>'
            f'<td class="n">{r.get("cells") or ""}</td><td class="n">{e(r.get("die", ""))}</td>'
            f"<td>{e(r['what'])}</td>"
            f'<td><a href="{e(cat)}">Mimir catalogue</a></td></tr>'
        )
    canon = f'<link rel="canonical" href="{e(base_url)}">\n' if base_url else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Heimdall III: benchmarks</title>
{canon}<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:2em auto;max-width:70em;padding:0 1em;color:#222}}
table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid #ddd;padding:.35em .6em;text-align:left}}
td.n{{text-align:right}} th{{background:#f3f3f3}}
.nav{{background:#fff6e5;border-left:4px solid #ffb454;padding:.5em .8em}}
</style></head><body>
<h1>Heimdall III <span style="font-size:.5em;color:#888">{version_label()}</span></h1>
<p>The watchman who sees all nine worlds. Each benchmark below is shown as a stack of planes,
from the HDL down to the placed chip; click an object to see its column up to the HDL line.
Rotate with the mouse, press <b>?</b> in a viewer for the help page.
Part of Yggdrasil III; the benchmarks come from the
<a href="{e(catalogue)}">Mimir III catalogue</a>.</p>
<p class="nav"><a href="guide.html"><b>How to use Heimdall</b></a>: worked examples with
screenshots, each with a link that opens the exact view. &nbsp;
<a href="help.html"><b>Help</b></a>: every control, the keys and the deep-link parameters.</p>
<table><thead><tr><th>design</th><th>suite</th><th>target</th><th>LUTs</th><th>FFs</th>
<th>std cells</th><th>die (um)</th><th>what it does</th><th>catalogue</th></tr></thead>
<tbody>
{chr(10).join(body)}
</tbody></table>
</body></html>
"""


_THEAD = re.compile(r"<table><thead>.*?</thead>", re.S)
_OLD_ROW = re.compile(
    r'(<tr><td><a href="[^"]*">[^<]*</a></td><td>[^<]*</td>)'
    r'(<td class="n">\d*</td><td class="n">\d*</td>)'
)
_NEW_HEAD = (
    "<table><thead><tr><th>design</th><th>suite</th><th>target</th><th>LUTs</th><th>FFs</th>\n"
    "<th>std cells</th><th>die (um)</th><th>what it does</th><th>catalogue</th></tr></thead>"
)


def row_html(r: dict[str, Any], catalogue: str) -> str:
    e = html.escape
    cat = r["catalogue"] or f"{catalogue}#{r['design']}"
    return (
        f'<tr><td><a href="{e(r["slug"])}/">{e(r["design"])}</a></td><td>{e(r["suite"])}</td>'
        f"<td>{e(r.get('target', 'fpga'))}</td>"
        f'<td class="n">{r["luts"] or ""}</td><td class="n">{r["ffs"]}</td>'
        f'<td class="n">{r.get("cells") or ""}</td><td class="n">{e(r.get("die", ""))}</td>'
        f'<td>{e(r["what"])}</td><td><a href="{e(cat)}">Mimir catalogue</a></td></tr>'
    )


def extend_index(old: str, rows: list[dict[str, Any]], note: str, catalogue: str) -> str:
    """The index of an earlier site with the target columns added to its rows, the new rows appended
    (sorted) and `note` placed before the navigation line; the rest of the page is kept."""
    text = _THEAD.sub(lambda _m: _NEW_HEAD, old, count=1)
    text = _OLD_ROW.sub(
        lambda m: m[1] + "<td>fpga</td>" + m[2] + '<td class="n"></td><td class="n"></td>', text
    )
    text = re.sub(r"<p class=\"dim\"><b>Update \d+</b>.*?</p>\n", "", text, flags=re.S)
    new = "\n".join(
        row_html(r, catalogue)
        for r in sorted(rows, key=lambda r: (r["suite"], r["cells"], r["design"]))
    )
    text = text.replace("</tbody>", new + "\n</tbody>", 1)
    return text.replace('<p class="nav">', note + '\n<p class="nav">', 1)


def build_site(
    out: Path,
    base_url: str,
    specs: list[Spec],
    catalogue: str = DEFAULT_CATALOGUE,
    extend: Path | None = None,
    note: str = "",
    analyse: bool = True,
) -> list[dict[str, Any]]:
    """Build the whole site into `out`; benchmarks are exported one at a time. With `extend` (the
    directory of an earlier site) that site is copied first, the specs are added as new pages and
    the index keeps its rows."""
    if extend is not None:
        if out.exists():
            raise SiteError(f"{out} exists: --extend needs a new directory")
        shutil.copytree(extend, out, symlinks=False)
    out.mkdir(parents=True, exist_ok=True)
    copy_assets(out)
    rows: list[dict[str, Any]] = []
    bridge = analytics.find_bridge() if analyse else None
    with tempfile.TemporaryDirectory(prefix="heimdall-site-") as tmp:
        for spec in specs:
            rows.append(build_one(spec, out, Path(tmp), bridge))
    rows.sort(key=lambda r: (r["suite"], r["luts"], r["design"]))
    if extend is not None:
        old = (extend / "index.html").read_text(encoding="utf-8")
        (out / "index.html").write_text(extend_index(old, rows, note, catalogue), encoding="utf-8")
    else:
        (out / "index.html").write_text(index_html(rows, base_url, catalogue), encoding="utf-8")
    (out / "help.html").write_text(
        _root_page((WEB / "help.html").read_text(encoding="utf-8")), encoding="utf-8"
    )
    (out / "guide.html").write_text(
        guide_page(
            (WEB / "guide.html").read_text(encoding="utf-8"),
            {r["slug"] for r in rows}
            | ({p.name for p in out.iterdir() if (p / "bundle").is_dir()} if extend else set()),
        ),
        encoding="utf-8",
    )
    return rows


def refresh_site(site: Path, note: str = "") -> int:
    """Bring a built site up to this viewer without re-running any flow: the shared assets, the
    viewer page of every benchmark, help.html and guide.html are rewritten; the bundles and the
    index rows stay.
    `note` replaces the "Update N" paragraph of the index. Returns the number of pages refreshed."""
    copy_assets(site)
    viewer = _viewer_page((WEB / "index.html").read_text(encoding="utf-8"))
    pages = sorted(p for p in site.iterdir() if (p / "bundle" / "manifest.json").is_file())
    for p in pages:
        (p / "index.html").write_text(viewer, encoding="utf-8")
    (site / "help.html").write_text(
        _root_page((WEB / "help.html").read_text(encoding="utf-8")), encoding="utf-8"
    )
    (site / "guide.html").write_text(
        guide_page((WEB / "guide.html").read_text(encoding="utf-8"), {p.name for p in pages}),
        encoding="utf-8",
    )
    idx = site / "index.html"
    text = idx.read_text(encoding="utf-8")
    tag = f'<h1>Heimdall III <span style="font-size:.5em;color:#888">{version_label()}</span></h1>'
    text = re.sub(r"<h1>Heimdall III(?: <span[^>]*>v[^<]*</span>)?</h1>", tag, text, count=1)
    idx.write_text(text, encoding="utf-8")
    if note:
        text = idx.read_text(encoding="utf-8")
        text = re.sub(r"<p class=\"dim\"><b>Update \d+</b>.*?</p>\n", "", text, flags=re.S)
        idx.write_text(
            text.replace('<p class="nav">', note + '\n<p class="nav">', 1), encoding="utf-8"
        )
    return len(pages)
