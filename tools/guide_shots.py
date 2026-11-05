"""Take the screenshots of the guide (guide.html) from a built site, headless Chromium.

Needs `playwright` (pip install playwright; playwright install chromium); not a runtime dependency.
Usage: python tools/guide_shots.py SITE_DIR OUT_DIR [NAME ...]
Serves SITE_DIR on 127.0.0.1:8779 for the duration of the run only. Exit code 1 on a console error.
The shots are listed in guide_shot_list.py: (file name, benchmark slug, deep-link query, JavaScript
run after load, optional clip). The same URLs are the "try it" links of the guide.
"""

from __future__ import annotations

import functools
import http.server
import importlib
import sys
import threading
from pathlib import Path

PORT = 8779
Shot = tuple[str, str, str, str, dict[str, int] | None]


def load_shots() -> list[Shot]:
    """The shots (name, benchmark slug, deep-link query, JavaScript after load, clip)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    shots: list[Shot] = []

    def shot(
        name: str, slug: str, query: str, js: str = "", clip: dict[str, int] | None = None
    ) -> None:
        shots.append((name, slug, query, js, clip))

    importlib.import_module("guide_shot_list").define(shot)
    return shots


def url(slug: str, query: str) -> str:
    """The same URL is the "try it" link of the guide (relative to the site root)."""
    return f"{slug}/?rotate=0&{query}"


def main() -> int:
    from playwright.sync_api import sync_playwright

    site, out = Path(sys.argv[1]), Path(sys.argv[2])
    only = set(sys.argv[3:])
    out.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(_Quiet, directory=str(site))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"]
            )
            for name, slug, query, js, clip in load_shots():
                if only and name not in only:
                    continue
                page = browser.new_page(viewport={"width": 1600, "height": 900})
                page.on(
                    "console",
                    lambda m, n=name: (
                        errors.append(f"{n}: {m.text}") if m.type == "error" else None
                    ),
                )
                page.on("pageerror", lambda e, n=name: errors.append(f"{n}: {e}"))
                page.goto(f"http://127.0.0.1:{PORT}/{url(slug, query)}")
                page.wait_for_selector("body[data-ready='1']", timeout=120000)
                page.evaluate("window.__o3viz.stop()")
                if js:
                    page.evaluate(js)
                page.wait_for_timeout(900)
                page.screenshot(path=str(out / f"{name}.png"), clip=clip)
                page.close()
                print("shot", name)
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    for e in errors:
        print("console error:", e, file=sys.stderr)
    return 1 if errors else 0


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    sys.exit(main())
