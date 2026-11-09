"""Touch check of the built site on a phone-size emulation (Playwright, CDP touch events).

Usage: python tools/touch_check.py SITE_DIR [--port 8779] [--shots DIR] [--page SLUG]
Pinch changes the camera distance, the + / - / fit buttons change it, two fingers pan, a tap
selects; the index and one page are screenshotted. Prints one line per check; exit 1 on a failure.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import math
import sys
import threading
from typing import Any


def _dist(cam: dict[str, list[float]]) -> float:
    return math.dist(cam["pos"], cam["target"])


def _touch(cdp: Any, kind: str, pts: list[tuple[float, float]]) -> None:
    cdp.send(
        "Input.dispatchTouchEvent",
        {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]},
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--port", type=int, default=8779)
    ap.add_argument("--shots", default="")
    ap.add_argument("--page", default="opencores-i2c")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

    handler = functools.partial(Quiet, directory=a.site)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fails: list[str] = []
    errors: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(("ok   " if ok else "FAIL ") + name + (f": {detail}" if detail else ""))
        if not ok:
            fails.append(name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"]
            )
            ctx = browser.new_context(**p.devices["iPhone 13"])
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            base = f"http://127.0.0.1:{a.port}/"
            page.goto(base)
            if a.shots:
                page.screenshot(path=f"{a.shots}/index-phone.png")
            check("index has tier headings", page.locator("tr.tier").count() >= 5)
            page.goto(f"{base}{a.page}/?rotate=0")
            page.wait_for_function(
                "window.__o3viz && window.__o3viz.S && window.__o3viz.S.man", timeout=120000
            )
            page.wait_for_timeout(1500)
            cdp = ctx.new_cdp_session(page)

            def cam() -> dict[str, list[float]]:
                out: dict[str, list[float]] = page.evaluate("window.__o3viz.cam()")
                return out

            box = page.locator("#view").bounding_box()
            assert box is not None
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            check(
                "panels start collapsed on a phone",
                page.evaluate("window.__o3viz.panelState()")
                == {"left": True, "hdl": True, "right": True},
            )
            check("canvas wider than 300 px", box["width"] > 300, f"{box['width']:.0f}")
            d0 = _dist(cam())
            # pinch out (fingers spread): zoom in
            _touch(cdp, "touchStart", [(cx - 30, cy), (cx + 30, cy)])
            for k in range(1, 9):
                _touch(cdp, "touchMove", [(cx - 30 - 12 * k, cy), (cx + 30 + 12 * k, cy)])
            _touch(cdp, "touchEnd", [])
            page.wait_for_timeout(300)
            d1 = _dist(cam())
            check("pinch out zooms in", d1 < d0 * 0.7, f"{d0:.1f} -> {d1:.1f}")
            # pinch in: zoom out
            _touch(cdp, "touchStart", [(cx - 120, cy), (cx + 120, cy)])
            for k in range(1, 9):
                _touch(cdp, "touchMove", [(cx - 120 + 12 * k, cy), (cx + 120 - 12 * k, cy)])
            _touch(cdp, "touchEnd", [])
            page.wait_for_timeout(300)
            d2 = _dist(cam())
            check("pinch in zooms out", d2 > d1 * 1.3, f"{d1:.1f} -> {d2:.1f}")
            # two-finger drag pans (target moves)
            t0 = cam()["target"]
            _touch(cdp, "touchStart", [(cx - 30, cy), (cx + 30, cy)])
            for k in range(1, 9):
                _touch(
                    cdp,
                    "touchMove",
                    [(cx - 30 + 10 * k, cy + 6 * k), (cx + 30 + 10 * k, cy + 6 * k)],
                )
            _touch(cdp, "touchEnd", [])
            page.wait_for_timeout(300)
            t1 = cam()["target"]
            check(
                "two-finger drag pans",
                math.dist(t0, t1) > 0.5,
                f"target moved {math.dist(t0, t1):.2f}",
            )
            # one finger rotates (camera direction changes, distance about the same)
            p0 = cam()["pos"]
            _touch(cdp, "touchStart", [(cx, cy)])
            for k in range(1, 9):
                _touch(cdp, "touchMove", [(cx + 15 * k, cy)])
            _touch(cdp, "touchEnd", [])
            page.wait_for_timeout(500)
            check("one-finger drag rotates", math.dist(p0, cam()["pos"]) > 0.5)
            # buttons
            page.locator("#zfit").tap()
            page.wait_for_timeout(300)
            f0 = _dist(cam())
            page.locator("#zin").tap()
            page.wait_for_timeout(300)
            f1 = _dist(cam())
            page.locator("#zout").tap()
            page.wait_for_timeout(300)
            f2 = _dist(cam())
            check("+ button zooms in", f1 < f0 * 0.9, f"{f0:.1f} -> {f1:.1f}")
            check("- button zooms out", f2 > f1 * 1.1, f"{f1:.1f} -> {f2:.1f}")
            b = page.locator("#zin").bounding_box()
            assert b is not None
            check(
                "buttons finger-sized (>= 44 px)",
                b["width"] >= 44 and b["height"] >= 44,
                f"{b['width']:.0f}x{b['height']:.0f}",
            )
            page.locator("#zfit").tap()
            page.wait_for_timeout(300)
            check("fit restores the start distance", abs(_dist(cam()) - f0) < 1e-3 * max(f0, 1))
            # tap selects: scan a grid for an object
            sel = None
            for gy in range(-6, 7):
                for gx in range(-6, 7):
                    x, y = cx + gx * 20, cy + gy * 20
                    page.touchscreen.tap(x, y)
                    page.wait_for_timeout(40)
                    sel = page.evaluate("window.__o3viz.S.sel")
                    if sel:
                        break
                if sel:
                    break
            check("tap selects an object", bool(sel), str(sel))
            if a.shots:
                page.screenshot(path=f"{a.shots}/page-phone.png")
            check("order nav present", "more complex" in page.locator("#ordnav").inner_html())
            check("0 console errors", not errors, "; ".join(errors[:3]))
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
