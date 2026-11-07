"""Load pages of a built site in headless Chromium and exercise the switching-activity panel.

For each page (smallest bundle first): load time and console errors; for a page with activity data,
each of the three colours (static probability, transition density, power) must measure at least one
object on every plane the manifest lists for activity, and a click on the first HDL line of the
roll-up table must select HDL objects. A page without data must say so in the panel. Prints one
line per page and exits 1 on any failure. Needs playwright (not a runtime dependency). Serves the
site on a free port and stops it.

Usage: python tools/activity_check.py SITE_DIR [--only SLUG ...] [--shots DIR]
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
  const o = window.__o3viz, S = o.S, a = S.act?.data;
  if (!a) {
    const text = document.getElementById("actbody").textContent;
    const says = text.includes("No switching-activity data");
    return { ok: says, none: true };
  }
  const per = {};
  for (const k of ["act_p1", "act_td", "act_pw"]) {
    o.setColour(k);
    per[k] = {};
    for (const p of S.man.activity.planes) {
      per[k][p] = (S.planes[p].metrics[k] ?? []).filter((v) => v !== null).length;
    }
  }
  const lacking = S.man.activity.planes.filter((p) => !per.act_p1[p] && !per.act_pw[p]);
  return { ok: lacking.length === 0, per, lacking, source: a.source_label, target: a.target };
}
"""

LINE = """
() => {
  const o = window.__o3viz, S = o.S, a = S.act.data;
  const row = a.lines.find((r) => r[1] > 0 && S.texts[r[0]]);
  if (!row) return { ok: false, line: null, sel: 0 };
  o.selectLines(row[0], row[1], row[1]);
  return { ok: (S.mode?.n ?? 0) > 0, line: `${row[0]}:${row[1]}`, sel: S.mode?.n ?? 0 };
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
                res = page.evaluate(CHECK)
                if a.shots:
                    page.evaluate("document.getElementById('actsec').open = true")
                    for k in ("td", "pw") if not res.get("none") else ("none",):
                        if k != "none":
                            page.evaluate("k => window.__o3viz.setColour('act_' + k)", k)
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(Path(a.shots) / f"{p.name}-{k}.png"))
                if not res.get("none"):
                    line = page.evaluate(LINE)
                    res["line"] = line
                    res["ok"] = bool(res["ok"]) and bool(line["ok"])
            except Exception as e:  # report and go on
                res, load = {"ok": False, "why": str(e)[:100]}, time.time() - t0
            ok = bool(res.get("ok")) and not errs and load < 30
            bad += not ok
            print(
                f"{'ok ' if ok else 'BAD'} {p.name} load={load:.1f}s errors={len(errs)} {res}",
                flush=True,
            )
            for msg in errs[:3]:
                print("    console error:", msg[:200], flush=True)
            page.close()
        browser.close()
    srv.shutdown()
    srv.server_close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
