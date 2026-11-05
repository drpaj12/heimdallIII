# heimdallIII

Heimdall III: the 3D provenance viewer of Yggdrasil III (was `o3viz` in Wyrd III). Exports one Odin III flow run
as a bundle of planes (HDL, graphs, cells, LUTs, clusters, placed atoms; later ASIC planes), serves the viewer,
and builds a static site of many benchmarks. Depends on Odin III only as programs (`odin3`, `odin3-flow`, `vpr`);
never imports its Python.

Spec: `docs/specs/2026-11-05-heimdall-design.md` (this repo), earlier `docs/specs/2026-11-03-o3viz-design.md`.

## Setup, test, lint

    python3 -m venv .venv && .venv/bin/pip install -e . ruff mypy
    .venv/bin/python -m unittest discover -s tests -v
    for f in tests/js/*.test.mjs; do node --test "$f"; done
    .venv/bin/ruff check . && .venv/bin/mypy --strict heimdall tests

## Rules

- Never commit to main after the first import. Open a PR (draft while working, ready at the end); squash merge only on green CI.
- Python 3.11+. Runtime is standard library only. No `# noqa` or `# type: ignore` without Peter's approval.
- Plane model is target-agnostic: a plane has `target` fpga | asic | common; anchors and joins never assume LUTs or a VPR grid.
- Never leave a server running: tests and screenshots stop theirs.
- No paper files in the repo. No emojis or em-dashes in docs.
- Commit and push often, after each green step.
