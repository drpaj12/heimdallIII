# Heimdall III

The watchman who sees all nine worlds and guards the Bifrost. Heimdall III is the 3D provenance viewer of
Yggdrasil III: one benchmark as a stack of planes, from the HDL down to the placed chip, with every object linked
to the HDL line it came from. It was `o3viz` inside Wyrd III and is now its own project, with its history kept.

![Heimdall III on VTR ch_intrinsics](docs/user/images/o3viz-ch_intrinsics.png)

Purpose: teaching and research view of what HDL becomes at every stage of a flow (provenance at every
granularity; graph analysis of netlist structure). Two targets by design: the FPGA flow (LUT, cluster, placed
atoms on the VPR grid) today, and the ASIC flow (Odin III, OpenROAD, GDS, `sky130_fd_sc_hd`) later; the ASIC
exporter is a stub (`heimdall/targets/asic.py`). Spec: `docs/specs/2026-11-05-heimdall-design.md`.

## Use

    heimdall export RUN_DIR --out design.o3viz --benchmark suite:design --src HDL_DIR
    heimdall serve design.o3viz                 # http://127.0.0.1:8765/ ; Ctrl-C to stop
    heimdall site --out SITE --base-url https://drpeterjamieson.com/RESEARCH/HEIMDALL/ SPEC...

Details, controls and screenshots: `docs/user/viz.md`; the viewer has its own help page (press `?`).
Python 3.11+, standard library only at runtime. Odin III, VPR and ABC are used only as programs.

## The site

The built site is a plain directory of static files (no server code). Peter uploads it to
`https://drpeterjamieson.com/RESEARCH/HEIMDALL/` (`heimdall_base_url`); the Mimir III catalogue links each
design that has a page there. Nothing is uploaded by the tools.

First site (29 benchmarks, 21 MB, built with `heimdall site` from `heimdall-runs/site-specs.txt`; flows by Odin III
main e5efb64e, binary `rel-main3`, VPR k6 architecture, one at a time under a 4 GB scope, `sha` through
`tools/heavy-run`):

- VerilogEval, size quartiles by Mimir `l6_luts` (rank, median and its neighbours). The picks
  that failed the VTR flow were replaced by the next by rank. VerilogEval is SystemVerilog and the VTR flow reads
  Verilog only (`--vtr-compat` is not supported for SystemVerilog), so the `ref` files were fed as `.v` and any
  using `always_ff`, `logic` or sized casts failed to parse.
  - Q1: Prob010_mt2015_q4a, Prob011_norgate, Prob012_xnorgate
  - Q2: Prob009_popcount3, Prob024_hadd, Prob025_reduction
  - Q3: Prob150_review2015_fsmonehot, Prob016_m2014_q4j, Prob085_shift4 (replacing Prob086_lfsr5, Prob142_lemmings2,
    Prob096_review2015_fsmseq, Prob128_fsm_ps2, Prob148_2013_q2afsm, Prob120_fsm3s, Prob095_review2015_fsmshift)
  - Q4: Prob123_bugs_addsubz, Prob043_vector5, Prob141_count_clock (replacing Prob154_fsm_ps2data,
    Prob066_edgecapture, Prob068_countbcd, Prob082_lfsr32, Prob146_fsm_serialdata, Prob118_history_shift)
  - Two designs failed `read_slang` in Mimir and have no LUT count, so they are not ranked.
- Odin III micros that reach `route` (one construct each): bm_DL_2_1_mux, bm_DL_2_4_encoder, bm_DL_4_bit_comparator,
  bm_DL_4_bit_shift_register, bm_DL_74381_ALU, bm_DL_BCD_adder, bm_DL_D_flipflop, bm_DL_Dff_w_synch_reset,
  bm_DL_behavioural_full_adder, bm_my_D_latch1, bm_if_reset, bm_DL_16_1_mux, bm_dag1_log, bm_dag2_log, bm_lpm_all.
  `bm_base_multiply` ran through VTR but the exporter fails on it (KeyError on an `hdl:sig.a/top_a.out` link, a
  hierarchy case); it is left out until that is fixed.
- VTR benchmarks `ch_intrinsics` and `sha`.

## Citations

- P. D. Kundarewich, "Synthetic Circuit Generation Using Clustering and Iteration", MASc thesis, University of
  Toronto, 2002 (Comb and Latched matrices, sections 2.1, 3.1 to 3.3, 5.1).
- M. Hutton, J. Rose, J. Grossman and D. Corneil, "Characterization and parameterized generation of synthetic
  combinational circuits", IEEE TCAD 17(10):985-996, 1998, and M. Hutton, J. Rose and D. Corneil, "Generation of
  synthetic sequential benchmark circuits", FPGA 1997; used as the thesis describes them.
- J. Rose et al., "The VTR project", 2012, and VTR 9 (TRETS 2025), for the flow the FPGA planes come from.

## Licence

MIT, as Wyrd III. three.js is vendored under `heimdall/web/vendor` (MIT, licence file kept).
