"""Take the screenshots of the help page (help.html) from a built site, headless Chromium.

Usage: python tools/help_shots.py SITE_DIR OUT_DIR [NAME ...]   (writes o3viz-*.png, 1500x900)
Serves SITE_DIR on 127.0.0.1:8779 for the duration of the run only. Exit code 1 on a console error.
"""

from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

PORT = 8779
INTR = "vtr-verilog-ch_intrinsics"
SHA = "vtr-verilog-sha"
SCROLL = "document.getElementById('%s').scrollIntoView({block: 'start'})"
KUND = "csrc=hdl-block&anchor=kundarewich-hdl-block&compare=mincut&panels=hdl"
# (file name, benchmark, deep-link query, JavaScript run after load)
SHOTS = [
    ("o3viz-ch_intrinsics", INTR, "", ""),
    ("o3viz-line", INTR, "sel=line:155-157", ""),
    ("o3viz-m5-tiers", INTR, "sel=line:165&plane=cell&panels=left&zoom=0.8", ""),
    ("o3viz-m6-graded-fsm", INTR, "sel=line:165&plane=lut&panels=left&zoom=0.8", ""),
    ("o3viz-m5-bus", INTR, "colour=@bus&sel=bus:return_val", ""),
    ("o3viz-m5-ff", INTR, "ff=highlight&plane=lut", ""),
    ("o3viz-depth", INTR, "colour=logic_level", ""),
    ("o3viz-anchors", SHA, "anchor=hutton_seq&plane=lut&panels=hdl", ""),
    ("o3viz-m6-hutton", SHA, "anchor=hutton&colour=@role&plane=lut&panels=hdl", ""),
    ("o3viz-m6-kundarewich", SHA, KUND, SCROLL % "csrc"),
    ("o3viz-paths", SHA, "sel=path:1&plane=placed", ""),
    ("o3viz-cone", SHA, "sel=obj:luts:sha1/hm6fp24itnu&cone=in:6&plane=lut", ""),
    ("o3viz-m7-scoap", INTR, "scoap=cc0:max", ""),
    ("o3viz-discovery", INTR, "", "document.getElementById('dgo').click(); " + SCROLL % "dmat"),
    ("o3viz-m6-collapsed", INTR, "panels=left,hdl,right", ""),
]


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
            for name, slug, query, js in SHOTS:
                if only and name not in only:
                    continue
                page = browser.new_page(viewport={"width": 1500, "height": 900})
                page.on(
                    "console",
                    lambda m, n=name: (
                        errors.append(f"{n}: {m.text}") if m.type == "error" else None
                    ),
                )
                page.on("pageerror", lambda e, n=name: errors.append(f"{n}: {e}"))
                page.goto(f"http://127.0.0.1:{PORT}/{slug}/?rotate=0&{query}")
                page.wait_for_selector("body[data-ready='1']", timeout=120000)
                page.evaluate("window.__o3viz.stop()")
                if js:
                    page.evaluate(js)
                page.wait_for_timeout(1200)
                page.screenshot(path=str(out / f"{name}.png"))
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
