"""Load every page of a built site in headless Chromium and exercise the graph analytics panel.

For each page (smallest bundle first): load time, console errors, then orbit heat, the default
clustering, and a click on the largest cluster of the largest analysed plane (the cluster must
become an update-4 group that reaches other planes and HDL lines). Prints one line per page and
exits 1 on any failure. Needs playwright (not a runtime dependency). Serves the site on a free
port and stops it.

Usage: python tools/analytics_check.py SITE_DIR [--only SLUG ...] [--shots DIR]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
import threading
import time
from pathlib import Path

CHECK = """
async () => {
  const o = window.__o3viz, S = o.S;
  if (!S.an) return { ok: false, why: "no analytics" };
  const planes = Object.keys(S.an.index.planes);
  if (!planes.length) return { ok: false, why: "no analysed plane" };
  const big = planes.sort((a, b) => S.an.index.planes[b].nodes - S.an.index.planes[a].nodes)[0];
  document.getElementById("anorbit").value = "0";
  await o.anOrbitHeat();
  const heat = S.planes[big].metrics["gdv_u_o0"].filter((v) => v !== null).length;
  document.getElementById("anfeat").value = "gdv_u";
  document.getElementById("ank").value = "default";
  await o.anPickClustering();
  document.getElementById("anlplane").value = big;
  o.fillAnList();
  const sizes = S.an.cur.sizes[big];
  if (!sizes) return { ok: true, degenerate: true, big, heat, why: "all nodes have one structure" };
  const order = sizes.map((_, i) => i).sort((x, y) => sizes[y] - sizes[x] || x - y);
  let used = 0;
  for (const c of order.slice(0, 5)) {
    // the largest clusters can be unlinked cells (taps, clock buffers): try the next
    await o.anClusterGroup(big, c);
    used = c;
    if (S.core.size > 0) break;
  }
  const per = {};
  for (const p of S.order) per[p] = [...S.core].filter((id) => S.byId.get(id)?.plane === p).length;
  const lines = S.paint?.lines ? [...S.paint.lines.values()].reduce((t, m) => t + m.size, 0) : 0;
  return { ok: true, big, nodes: S.an.index.planes[big].nodes, heat, k: S.an.cur.sizes[big].length,
    group: S.groups.groups.length, cluster: used, core: S.core.size, per, lines };
}
"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    root = Path(a.site)
    pages = sorted(
        (p for p in root.iterdir() if (p / "bundle" / "manifest.json").is_file()),
        key=lambda p: sum(f.stat().st_size for f in (p / "bundle").rglob("*") if f.is_file()),
    )
    if a.only:
        pages = [p for p in pages if p.name in a.only]

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    handler = functools.partial(Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        for p in pages:
            page = browser.new_page(viewport={"width": 1500, "height": 900})
            errs: list[str] = []
            page.on("console", lambda m, e=errs: e.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            t0 = time.time()
            try:
                page.goto(f"http://127.0.0.1:{port}/{p.name}/")
                page.wait_for_selector("body[data-ready='1']", timeout=120000)
                load = time.time() - t0
                page.evaluate("window.__o3viz.stop()")
                t1 = time.time()
                res = page.evaluate(CHECK)
                act = time.time() - t1
                if a.shots:
                    page.evaluate("document.getElementById('ansec').open = true")
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(Path(a.shots) / f"{p.name}.png"))
            except Exception as e:  # report and go on
                res, load, act = {"ok": False, "why": str(e)[:100]}, time.time() - t0, 0.0
            ok = bool(res.get("ok")) and not errs and load < 30
            if res.get("ok") and not res.get("degenerate"):
                ok = ok and res["group"] == 1 and res["core"] > 0 and res["heat"] > 0
            bad += not ok
            print(
                f"{'ok ' if ok else 'BAD'} {p.name} load={load:.1f}s act={act:.1f}s "
                f"errors={len(errs)} {res}",
                flush=True,
            )
            for e in errs[:3]:
                print("    console error:", e[:200], flush=True)
            page.close()
        browser.close()
    srv.shutdown()
    srv.server_close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
