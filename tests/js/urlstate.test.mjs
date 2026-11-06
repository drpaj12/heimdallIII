import test from "node:test";
import assert from "node:assert/strict";
import { parseQuery, PARAMS } from "../../heimdall/web/urlstate.js";

test("the example link parses into state", () => {
  const s = parseQuery("?sel=line:12&plane=lut&colour=logic_level&anchor=hutton&enclosing=1");
  assert.deepEqual(s, { sel: { kind: "line", file: "", a: 12, b: 12 }, enclosing: true, plane: "lut",
    colour: "logic_level", anchor: "hutton" });
});

test("line ranges, files, objects, paths", () => {
  assert.deepEqual(parseQuery("sel=line:x.v:3-9").sel, { kind: "line", file: "x.v", a: 3, b: 9 });
  assert.deepEqual(parseQuery("sel=line:5-7").sel, { kind: "line", file: "", a: 5, b: 7 });
  assert.deepEqual(parseQuery("sel=obj:lut:n12").sel, { kind: "obj", id: "lut:n12" });
  assert.deepEqual(parseQuery("sel=bus:return_val").sel, { kind: "bus", id: "return_val" });
  assert.deepEqual(parseQuery("sel=path:1").sel, { kind: "path", n: 1 });
});

test("metrics, scoap, cone, cell, panels, graphs, zoom", () => {
  const s = parseQuery("scoap=cc0:max&cone=in:4&cell=comb:1:2&panels=left,right,bogus&graphs=stg,ddg,x&zoom=2.5&rotate=0&ff=only&view=lut&solo=lut");
  assert.deepEqual(s.scoap, { m: "cc0", op: "max" });
  assert.deepEqual(s.cone, { dir: "in", depth: 4 });
  assert.deepEqual(s.cell, { which: "comb", i: 1, j: 2 });
  assert.deepEqual(s.panels, ["left", "right"]);
  assert.deepEqual(s.graphs, ["stg", "ddg"]);
  assert.equal(s.zoom, 2.5);
  assert.equal(s.rotate, false);
  assert.equal(s.ff, "only");
  assert.equal(s.view, "lut");
  assert.equal(s.solo, "lut");
  assert.equal(parseQuery("scoap=co").scoap.op, "max");
  assert.equal(parseQuery("cone=both").cone.depth, 6);
});

test("garbage is ignored", () => {
  assert.deepEqual(parseQuery(""), {});
  assert.deepEqual(parseQuery("?sel=nonsense&colour=a b<script>&zoom=-1&ff=zzz&cell=comb:x:y&scoap=zz"), {});
  assert.ok(PARAMS.includes("sel"));
});

test("every try-it link of the guide parses and nothing is dropped", async () => {
  const { readFileSync } = await import("node:fs");
  const text = readFileSync(new URL("../../heimdall/web/guide.html", import.meta.url), "utf8");
  const hrefs = [...text.matchAll(/class="tryit" href="@([^"]*)"/g)].map((m) => m[1].replaceAll("&amp;", "&"));
  assert.ok(hrefs.length >= 20);
  for (const h of hrefs) {
    const q = h.slice(h.indexOf("?") + 1);
    const want = [...new URLSearchParams(q).keys()].sort();
    assert.deepEqual(Object.keys(parseQuery(q)).sort(), want, h);
  }
});

test("bits=1 turns the bit squares on; anything else is ignored", () => {
  assert.equal(parseQuery("?bits=1").bits, true);
  assert.equal("bits" in parseQuery("?bits=yes"), false);
  assert.ok(PARAMS.includes("bits"));
});

test("grp= lists reverse groups: ; between groups, , inside one; bad ids dropped", () => {
  assert.deepEqual(parseQuery("?grp=luts:top/a1,luts:top/b2;cell:u_x").grp, [["luts:top/a1", "luts:top/b2"], ["cell:u_x"]]);
  assert.deepEqual(parseQuery("?grp=a<b;;ok").grp, [["ok"]]);
  assert.equal("grp" in parseQuery("?grp=%3Cx%3E"), false);
});
