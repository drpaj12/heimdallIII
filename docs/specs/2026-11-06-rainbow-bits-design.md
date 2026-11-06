# Heimdall III: rainbow selection, bit squares, reverse groups (update 4)

Peter 2026-11-06: "The bus display is not that great". Approved design.
Purpose: provenance at every granularity made readable: which HDL line became which object on every plane, and
which bit of a bus each object carries. RQ: viewer usability (descriptive, no hypothesis). Measure: on the
screenshots each selected line's objects carry its colour on every plane, and bus bits read LSb red to MSb violet.

## 1. Bit order finding (checked first)

Micro `[7:0]`, `[0:7]`, `[11:4]`, `[4:11]` buses through odin3-flow and the exporter dump run:

- Odin III's JSON `netnames[x].bits` always runs from the LSb up, whatever the declared range. `offset` is the lowest
  declared index, `upto: 1` marks an ascending `[lo:hi]`. LSb = the RIGHT declared index, MSb = the LEFT one.
- The BLIF names nets by DECLARED index (`b[7]` is the LSb of `[0:7]`).
- So `bit` in the planes was the offset from the LSb on the cell/ddg paths (correct) but the declared index on the
  LUT/placed path that reads `name[N]` from the BLIF (wrong for any range that is not `[N:0]`; `[11:4]` gave 4..11,
  `[0:7]` gave 7..0). Bus widths from `max(bit)+1` were wrong with it.
- Fix (exporter, `cells.port_bus`): `bit` is ALWAYS the offset from the LSb (0 = LSb, width-1 = MSb). The bus table
  gets `range: [left, right]` (declared). Affected pages are re-exported; pages whose buses are all `[N:0]` are
  byte-identical to before.

## 2. Definitions

- Hue ramp `rainbow(k, n)`: hue = 270 * k / (n - 1) degrees (red 0 to violet 270), n = 1 gives red;
  `hsl(hue, 85%, 55%)`.
- Forward rainbow: select n HDL lines (click or drag). Line k (top to bottom, 0-based) gets `rainbow(k, n)`.
  The existing reach (`hdlCovering` then `reachDown` plus the graph planes above) is run per line. An object reached
  from one line takes its colour; from several lines it gets a pie of those colours (equal slices, line order).
  Flip-flops in the highlight are white. The HDL pane paints each selected line's background in its colour.
  A selection that is a case/if chain keeps the three tier colours (the tier view wins over the rainbow).
- Bit square (toggle `bits`, default off), any selection (lines, object, bus, brush, groups): each highlighted object
  with a bus bit gets a small horizontal square on its top face coloured `rainbow(bit, width)`. An object that holds
  the whole bus (`busk = own`, `bit = null`; word cells, signal objects) gets the square striped MSb..LSb (at most 8
  stripes, sampled evenly). An object with an inferred bus (`busk = cone`) has no known bit: no square.
  Body colour = line or group; square = bit; the two encodings do not clash. Drawn on white flip-flops too.
- Reverse groups: shift-click an object (3D view) starts a group with the next colour of the fixed 8-step sequence
  red, orange, yellow, green, cyan, blue, indigo, violet, then wraps. A group keeps its colour. Shift+Alt-click adds
  the object to the current (last) group. A group's objects and everything linked to them on every plane
  (`closure` up and down, as a plain click) take the group colour; the HDL lines of the group (innermost constructs
  in the reach plus the own span of the clicked objects) are tinted in it. A line shared by several groups shows
  one colour bar per group in the gutter; an object shared by several groups gets a pie. Flip-flops white.
  Clear button or Esc resets.
- Shift + drag keeps the brush box (a shift-click that moves less than 4 px is the group action).

## 3. Interaction table

| Input | Effect |
| --- | --- |
| click or drag lines in the HDL pane | forward rainbow over the lines |
| click an object (3D) | as before (amber selection, all linked) |
| shift-click an object | new reverse group, next colour |
| shift+alt-click an object | add the object to the current group |
| shift + drag in 3D | brush (unchanged) |
| Esc, "clear selection" | clear selection, rainbow and groups |
| "bits" checkbox, `bits=1` in the URL | bit squares on the highlighted objects |

## 4. Data

Needs `bus`, `bit`, `busk` on the planes (already there) and the bus width from the manifest `buses` table. The
exporter change is the offset fix and `range` in the bus table. No new bundle file; no bundle version bump (the new
field is optional).

## 5. Code

- `web/rainbow.js` (pure, node tests): `rainbow`, `GROUP_COLOURS`, `groupColour`, `lineOwners`, `groupOwners`,
  `lineMap`, `Groups` bookkeeping (`addGroup`, `addTo`, `clear`), `bitStripes`, `pieSlices`, `barGradient`.
- `app.js`: `S.paint` (owners per object id, colours, gutter map), colour in `refreshPlane`, one overlay mesh per
  plane with vertex colours for pies and squares (`drawMarks`), `paintLines` backgrounds and gutter bars,
  shift-click handling, `bits` checkbox, Esc.
- `help.html`, `guide.html`: "What's new (update 4)" at the top plus the controls in the reference sections.

## 6. Tests

Node: rainbow ramp (n = 1, 2, 3, 9, endpoints), group colour wrap and keep, per-line union and pie owners,
shared-line gutter bars, group bookkeeping (new, add, clear, wrap), bit stripes (single bit, word, cone none, cap 8),
pie slices. Python: bit offset for the four ranges, `range` in the bus table, guide/help contain the update section.
Screenshots (looked at): ch_intrinsics forward 3 lines; sha bits on; uart2spi reverse 3 groups; vga_lcd bits on with
the load time under 30 s. Load-time and console-error check on all 50 pages.
