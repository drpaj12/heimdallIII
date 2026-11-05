"""The guide: examples are well formed, pictures exist, "try it" links are the shots' URLs,
and every deep-link parameter is documented in the help page."""

from __future__ import annotations

import html
import importlib.util
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType

from heimdall import serve

WEB = serve.WEB
ROOT = Path(__file__).resolve().parent.parent


def _shots_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guide_shots", ROOT / "tools" / "guide_shots.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["guide_shots"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Guide(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.examples: list[dict[str, int]] = []
        self.imgs: list[str] = []
        self.tryit: list[str] = []
        self.hrefs: list[str] = []
        self._ol = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "section" and "ex" in a.get("class", "").split():
            self.examples.append({"steps": 0, "figs": 0, "try": 0})
        if tag == "ol" and self.examples:
            self._ol = True
        if tag == "li" and self._ol:
            self.examples[-1]["steps"] += 1
        if tag == "figure" and self.examples:
            self.examples[-1]["figs"] += 1
        if tag == "img":
            self.imgs.append(a["src"])
        if tag == "a" and "href" in a:
            self.hrefs.append(a["href"])
            if "tryit" in a.get("class", "").split():
                self.tryit.append(a["href"])
        if tag == "div" and a.get("class") == "try" and self.examples:
            self.examples[-1]["try"] += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "ol":
            self._ol = False


def _guide() -> _Guide:
    g = _Guide()
    g.feed((WEB / "guide.html").read_text())
    return g


class TestGuide(unittest.TestCase):
    def test_examples_are_well_formed(self) -> None:
        g = _guide()
        self.assertGreaterEqual(len(g.examples), 8)
        for i, e in enumerate(g.examples, 1):
            self.assertTrue(3 <= e["steps"] <= 6, f"example {i}: {e['steps']} steps")
            self.assertTrue(1 <= e["figs"] <= 3, f"example {i}: {e['figs']} screenshots")
            self.assertGreaterEqual(e["try"], 1, f"example {i}: no try-it box")

    def test_pictures_exist_and_are_all_used(self) -> None:
        g = _guide()
        shots = _shots_module().load_shots()
        for src in g.imgs:
            self.assertTrue(src.startswith("images/guide/"), src)
            self.assertTrue((WEB / src).is_file(), src)
        self.assertEqual(sorted(g.imgs), sorted(f"images/guide/{s[0]}.png" for s in shots))
        on_disk = {p.name for p in (WEB / "images" / "guide").iterdir()}
        self.assertEqual(on_disk, {f"{s[0]}.png" for s in shots})

    def test_try_links_are_the_shot_urls(self) -> None:
        g = _guide()
        mod = _shots_module()
        want = {"@" + mod.url(s[1], s[2]) for s in mod.load_shots()}
        self.assertEqual(set(g.tryit), want)

    def test_links_to_help_and_index(self) -> None:
        g = _guide()
        self.assertIn("help.html", g.hrefs)
        self.assertIn("index.html", g.hrefs)
        h = (WEB / "help.html").read_text()
        self.assertIn('href="guide.html"', h)


class TestDeepLinkDocs(unittest.TestCase):
    def test_every_parameter_is_in_the_help_page(self) -> None:
        js = (WEB / "urlstate.js").read_text()
        m = re.search(r"export const PARAMS = \[([^\]]*)\]", js)
        assert m
        names = re.findall(r'"(\w+)"', m.group(1))
        self.assertGreaterEqual(len(names), 15)
        text = html.unescape((WEB / "help.html").read_text())
        for n in names:
            self.assertIn(f"<code>{n}</code>", text, n)

    def test_app_applies_the_url(self) -> None:
        app = (WEB / "app.js").read_text()
        self.assertIn("parseQuery(location.search)", app)


if __name__ == "__main__":
    unittest.main()
