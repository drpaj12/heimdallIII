"""Site builder and targets, on the tiny fixture run."""

from __future__ import annotations

import gzip
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from heimdall import export, site, targets
from heimdall.serve import WEB
from heimdall.targets import asic


class _Links(HTMLParser):
    """Every file reference of a page (img, a, script, link) and its element ids."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        key = {"img": "src", "script": "src", "a": "href", "link": "href"}.get(tag)
        if key and a.get(key):
            self.refs.append(a[key])


DATA = Path(__file__).resolve().parent / "data"
FLOW = DATA / "flow"


class TestSpec(unittest.TestCase):
    def test_parse(self) -> None:
        s = site.parse_spec("micro:bm_x=/tmp/f,src=/a,src=/b,what=an adder")
        self.assertEqual((s.suite, s.design, s.slug), ("micro", "bm_x", "micro-bm_x"))
        self.assertEqual(s.flow, Path("/tmp/f"))
        self.assertEqual(s.src, (Path("/a"), Path("/b")))
        self.assertEqual(s.what, "an adder")

    def test_note(self) -> None:
        s = site.parse_spec("s:d=/f,what=w,note=a variant; see x/y")
        self.assertEqual((s.what, s.note), ("w", "a variant; see x/y"))

    def test_bad(self) -> None:
        for bad in ("nosuite=/f", "a:b", "a:b=/f,zzz=1"):
            with self.assertRaises(site.SiteError):
                site.parse_spec(bad)

    def test_duplicates(self) -> None:
        with self.assertRaises(site.SiteError):
            site.parse_specs(["a:b=/x", "a:b=/y"])


class TestTargets(unittest.TestCase):
    def test_plane_targets(self) -> None:
        got = targets.plane_targets(["ddg", "hdl", "cell", "lut", "placed", "die"])
        self.assertEqual(
            got,
            {
                "ddg": "common",
                "hdl": "common",
                "cell": "common",
                "lut": "fpga",
                "placed": "fpga",
                "die": "asic",
            },
        )

    def test_asic_needs_a_finished_run(self) -> None:
        with self.assertRaises(export.ExportError):
            asic.export_asic(FLOW, Path("/nonexistent"))


class TestPack(unittest.TestCase):
    def test_split_and_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            raw, out = Path(d) / "raw", Path(d) / "out"
            (raw / "planes").mkdir(parents=True)
            big = json.dumps({"v": list(range(5000))})
            (raw / "planes" / "lut.json").write_text(big)
            (raw / "manifest.json").write_text('{"a": 1}')
            (raw / "hdl").mkdir()
            (raw / "hdl" / "t.v").write_text("module t; endmodule\n")
            parts = site.pack_bundle(raw, out, part_bytes=500)
            names = parts["planes/lut.json"]
            self.assertGreater(len(names), 1)
            blob = b"".join((out / n).read_bytes() for n in names)
            self.assertEqual(gzip.decompress(blob).decode(), big)
            self.assertEqual(json.loads((out / "manifest.json").read_text())["parts"], parts)
            self.assertTrue((out / "hdl" / "t.v").is_file())
            self.assertFalse((out / "planes" / "lut.json").exists())


class TestCacheBust(unittest.TestCase):
    def test_pages_point_to_existing_versioned_dir(self) -> None:
        spec = site.Spec("micro", "t", FLOW, (DATA / "src",), "x")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "site"
            site.build_site(out, "", [spec])
            aid = site.asset_id()
            self.assertEqual([p.name for p in (out / "_assets").iterdir()], [aid])
            for html_file in [out / "micro-t" / "index.html"]:
                text = html_file.read_text(encoding="utf-8")
                srcs = re.findall(r'src="\.\./_assets/([^/"]+)/app\.js"', text)
                self.assertEqual(srcs, [aid])
                self.assertTrue((out / "_assets" / srcs[0] / "app.js").is_file())
            for name in ("help.html", "guide.html"):
                for ref in re.findall(r'src="_assets/([^/"]+)/', (out / name).read_text()):
                    self.assertEqual(ref, aid)

    def test_id_follows_content(self) -> None:
        a = site.asset_id()
        self.assertEqual(a, site.asset_id())
        self.assertRegex(a, r"^v\d+\.\d+(\.\d+)?-[0-9a-f]{8}$")
        app = WEB / "app.js"
        orig = app.read_bytes()
        try:
            app.write_bytes(orig + b"\n// changed\n")
            self.assertNotEqual(a, site.asset_id())
        finally:
            app.write_bytes(orig)
        self.assertEqual(a, site.asset_id())

    def test_stale_banner_present(self) -> None:
        text = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn("Old cached files: reload the page", text)
        self.assertIn("window.__o3alive = true", (WEB / "app.js").read_text(encoding="utf-8"))


class TestBuild(unittest.TestCase):
    def test_site(self) -> None:
        spec = site.Spec("micro", "t", FLOW, (DATA / "src",), "a tiny test design")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "site"
            rows = site.build_site(out, "https://example.org/h/", [spec])
            self.assertEqual(rows[0]["slug"], "micro-t")
            index = (out / "index.html").read_text()
            self.assertIn('href="micro-t/"', index)
            self.assertIn("a tiny test design", index)
            self.assertIn("catalogue.html#t", index)
            page = (out / "micro-t" / "index.html").read_text()
            aid = site.asset_id()
            self.assertIn(f"../_assets/{aid}/app.js", page)
            self.assertIn(f"../_assets/{aid}/vendor/three.module.min.js", page)
            self.assertIn(f'content="{aid}"', page)
            self.assertNotIn("@@BUILD@@", page)
            self.assertIn(f"../_assets/{aid}/order.json?v=", page)
            self.assertTrue((out / "_assets" / aid / "order.json").is_file())
            self.assertIn('href="../help.html"', page)
            self.assertFalse((out / "micro-t" / "help.html").exists())
            self.assertIn(
                f'src="_assets/{aid}/images/o3viz-line.png"', (out / "help.html").read_text()
            )
            self.assertIn('href="guide.html"', index)
            self.assertIn('href="help.html"', index)
            self.assertTrue((out / "guide.html").is_file())
            self.assertTrue((out / "_assets" / aid / "images" / "guide").is_dir())
            self.assertFalse((out / "_assets" / aid / "guide.html").exists())
            man = json.loads((out / "micro-t" / "bundle" / "manifest.json").read_text())
            self.assertIn("planes/lut.json", man["parts"])
            self.assertEqual(man["plane_targets"]["lut"], "fpga")
            self.assertEqual(man["plane_targets"]["hdl"], "common")
            self.assertTrue((out / "_assets" / aid / "app.js").is_file())
            self.assertFalse((out / "_assets" / aid / "index.html").exists())

    def test_every_link_and_image_resolves(self) -> None:
        specs = [
            site.Spec("micro", "t", FLOW, (DATA / "src",), "a tiny test design"),
            site.Spec("odin3-micro", "bm_DL_74381_ALU", FLOW, (DATA / "src",)),
        ]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "site"
            site.build_site(out, "", specs)
            pages = sorted(out.rglob("*.html"))
            self.assertGreaterEqual(len(pages), 5)
            seen = 0
            for page in pages:
                scan = _Links()
                scan.feed(page.read_text())
                for ref in scan.refs:
                    if ref.startswith(("http://", "https://", "mailto:", "data:")):
                        continue
                    path, _, frag = ref.partition("#")
                    path = path.split("?", 1)[0]
                    target = page if not path else (page.parent / path).resolve()
                    if target.is_dir():
                        target = target / "index.html"
                    self.assertTrue(target.is_file(), f"{page.relative_to(out)}: {ref}")
                    self.assertTrue(
                        target.resolve().is_relative_to(out.resolve()), f"{page}: {ref}"
                    )
                    if frag and target.suffix == ".html":
                        ids = _Links()
                        ids.feed(target.read_text())
                        self.assertIn(frag, ids.ids, f"{page.relative_to(out)}: {ref}")
                    seen += 1
            self.assertGreater(seen, 40)

    def test_guide_links_follow_the_benchmarks_present(self) -> None:
        tpl = (
            '<a class="tryit" href="@a-b/?sel=line:3&amp;rotate=0">x</a> '
            '<a class="tryit" href="@c-d/?z=1">y</a>'
        )
        out = site.guide_page(tpl, {"a-b"}, "v1-abc")
        self.assertIn('href="a-b/?sel=line:3&amp;rotate=0"', out)
        self.assertNotIn("c-d/", out.replace("benchmark c-d is not", ""))
        self.assertIn("benchmark c-d is not in this build", out)

    def test_deterministic(self) -> None:
        spec = site.Spec("micro", "t", FLOW, (DATA / "src",))
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            site.build_site(a, "", [spec])
            site.build_site(b, "", [spec])
            files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
            self.assertEqual(files, sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file()))
            for f in files:
                self.assertEqual((a / f).read_bytes(), (b / f).read_bytes(), str(f))

    def test_export_manifest_has_targets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            man = export.export_bundle(FLOW, Path(d) / "b", "t", [DATA / "src"])
            self.assertEqual(set(man["plane_targets"]), set(man["planes"]))
            self.assertEqual(man["coord"]["placed"]["kind"], "grid")


if __name__ == "__main__":
    unittest.main()


class TestRefresh(unittest.TestCase):
    def test_refresh_rewrites_pages_and_note(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            site_dir = Path(td)
            page = site_dir / "s-d"
            (page / "bundle").mkdir(parents=True)
            (page / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
            (page / "index.html").write_text("old", encoding="utf-8")
            (site_dir / "index.html").write_text(
                '<p class="dim"><b>Update 5</b>: x</p>\n<p class="nav">n</p>', encoding="utf-8"
            )
            n = site.refresh_site(site_dir, '<p class="dim"><b>Update 6</b>: y</p>')
            self.assertEqual(n, 1)
            aid = site.asset_id()
            self.assertIn(
                f"../_assets/{aid}/app.js", (page / "index.html").read_text(encoding="utf-8")
            )
            idx = (site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Update 6", idx)
            self.assertNotIn("Update 5", idx)
            self.assertTrue((site_dir / "_assets" / aid / "analyticsview.js").is_file())
            self.assertTrue((site_dir / "_assets" / aid / "selcompare.js").is_file())
            label = site.version_label()
            self.assertIn(label, site.index_html([], "", "https://x/"))
            self.assertRegex(label, r"^v\d+\.\d+")
            for name in ("help.html", "guide.html"):
                body = (site_dir / name).read_text(encoding="utf-8")
                self.assertIn(label, body)
                self.assertNotIn("@@VERSION@@", body)
            self.assertIn("update6", (site_dir / "help.html").read_text(encoding="utf-8"))
