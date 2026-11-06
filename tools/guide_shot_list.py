"""The shots of the guide: (name, benchmark, deep-link query, JavaScript after load, clip).

The queries are also the "try it" links in heimdall/web/guide.html (a test keeps the two in step).
"""

from __future__ import annotations

from collections.abc import Callable

ALU = "odin3-micro-bm_DL_74381_ALU"
SHIFT = "odin3-micro-bm_DL_4_bit_shift_register"
LPM = "odin3-micro-bm_lpm_all"
INTR = "vtr-verilog-ch_intrinsics"
SHA = "vtr-verilog-sha"
CLOCK = "verilogeval-Prob141_count_clock"
UART = "opencores-uart2spi"

VIZ = "window.__o3viz"
SCROLL = "id => document.getElementById(id).scrollIntoView({block: 'start'})"
RIGHT = {"x": 300, "y": 0, "width": 1300, "height": 900}
# worst VPR path of sha: its first and one-before-last LUT objects
SHA_FIRST = "luts:sha1/hr5mitk2qg7"
SHA_LAST = "luts:sha1/hm6fp24itnu"
# three reverse groups on uart2spi: one LUT each, the third with a second LUT added
GROUPS = "luts:top/hffwk3p4m3w;luts:top/hl26au6ed7u;luts:top/ho5yupui42a,luts:top/hovat6k3fqa"


def define(shot: Callable[..., None]) -> None:
    # 1 HDL lines
    shot("lines-1", ALU, "sel=line:13&panels=left")
    shot("lines-3", ALU, "sel=line:9&enclosing=1&panels=left")
    # 2 case tiers
    shot("tiers-1", ALU, "sel=line:12&plane=cell&panels=left&zoom=0.8")
    shot("tiers-3", INTR, "sel=line:165&plane=cell&panels=left&zoom=0.8")
    shot("tiers-4", INTR, "sel=line:165&plane=lut&panels=left&zoom=0.8")
    # 3 flip-flops and buses
    shot("ff-1", SHIFT, "ff=highlight&plane=lut&panels=hdl&zoom=0.8")
    shot("ff-2", SHIFT, "sel=line:19&ff=only&plane=lut&zoom=0.8&panels=left")
    shot("ff-3", CLOCK, "colour=@bus&sel=bus:ss&panels=hdl")
    # 4 logic depth and SCOAP
    shot("depth-1", LPM, "colour=logic_level&panels=hdl")
    shot("scoap-1", LPM, "scoap=co:max&panels=hdl")
    shot("scoap-2", LPM, "scoap=cc0:max&panels=hdl")
    # 5 paths
    shot("path-1", SHA, "sel=path:1&plane=placed&panels=left")
    shot("cone-1", SHA, f"sel=obj:{SHA_LAST}&cone=in:6&plane=lut&panels=left")
    shot("cone-2", SHA, f"sel=obj:{SHA_FIRST}&cone=out:4&plane=lut&panels=left")
    # 6 graph planes
    shot("graph-1", INTR, "graphs=stg&plane=stg&panels=left,hdl")
    shot("graph-2", INTR, "graphs=cfg&plane=cfg&panels=left,hdl")
    shot("graph-3", CLOCK, "graphs=ddg&plane=ddg&sel=line:25&panels=left")
    # 7 Hutton and Kundarewich
    shot("hutton-1", SHA, "anchor=hutton&colour=@role&plane=lut&panels=hdl&zoom=0.8")
    shot("hutton-2", SHA, "anchor=hutton&panels=left,hdl", f"({SCROLL})('cshapes')", RIGHT)
    shot(
        "kund-1",
        SHA,
        "csrc=hdl-block&anchor=kundarewich-hdl-block&cell=comb:11:7&panels=left,hdl",
        f"({SCROLL})('csrc')",
        RIGHT,
    )
    shot(
        "kund-2",
        SHA,
        "csrc=hdl-block&anchor=kundarewich-hdl-block&compare=mincut&panels=left,hdl",
        f"({SCROLL})('csrc')",
        RIGHT,
    )
    # 8 plane control
    shot("planes-1", ALU, "plane=lut&panels=left,hdl&zoom=0.8")
    shot("planes-2", ALU, "solo=lut&plane=lut&panels=left,hdl")
    shot("planes-3", ALU, "view=lut&panels=left,hdl")
    shot(
        "planes-4",
        ALU,
        "plane=lut&zoom=0.8&panels=left,hdl",
        f"[0, 1].forEach(() => {VIZ}.wheelAt(540, 440, -300))",
    )
    shot("panels-1", ALU, "sel=line:13&panels=left,hdl,right")
    # 11 rainbow lines, bit squares, reverse groups
    shot("rainbow-1", INTR, "sel=line:200-202&plane=lut&panels=left&zoom=2.2")
    shot("bits-1", SHA, "sel=bus:A&bits=1&view=lut&zoom=3&panels=left,right")
    shot("groups-1", UART, "grp=" + GROUPS + "&plane=lut&panels=left&zoom=1.6")
