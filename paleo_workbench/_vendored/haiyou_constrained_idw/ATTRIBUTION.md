# Vendored haiyou constrained-IDW algorithm — attribution

This directory contains a **selective, verbatim** copy of the pure algorithm
modules from the `haiyou-visualization` project. It exists so that
`paleo-workbench` can use the constrained-IDW single-factor interpolation
algorithm **without depending on the upstream private repository** at build or
runtime (the published artifact must run independently — see goal §14).

## Source of record

| | |
|---|---|
| Upstream repo | `WWX9/haiyou-visualization` (GitHub; **private**) |
| Integrated commit SHA | `5b8f8f9855d541e2f5886f5b321afdcf70c08a51` |
| Upstream path | `Drawing/drawing/` |

## What was vendored (exact import closure of the integration)

Only the pure-NumPy (+ optional SciPy) algorithm modules actually reached by
`generate_constrained_idw(..., extract_contours=False)` — no Qt application
shell, no GUI workflow code, no sample data, no symbol library:

- `drawing/single_factor/constrained_engine.py` — constrained-IDW pipeline
- `drawing/single_factor/fast_grid.py` — batched IDW + masks + upsampling
- `drawing/single_factor/masks.py` — domain / barrier masks
- `drawing/single_factor/direction_corridor.py` — anisotropic direction blend
- `drawing/compute/__init__.py`, `drawing/compute/performance.py` — CPU/GPU
  settings plumbing (pure; `performance.py` retains upstream's *lazy*
  `from PyQt6.QtCore import QSettings` inside two unused persistence helpers —
  unreachable from the interpolation path, and never imported at runtime; the
  host's `test_constrained_idw_integration` gate asserts PyQt6 never loads).

The package `__init__.py` files here are Qt-free stubs (the upstream
`drawing/__init__.py` and `drawing/single_factor/__init__.py` import PyQt6 and
the GUI workflow, which a PySide6 host must not load).

The copied modules are **byte-for-byte identical** to the upstream SHA above
(verified at vendor time).

## What was NOT vendored

The full `haiyou-visualization` application (PyQt6 GUI, `workflow.py`, contour
post-processing `contour_extractor.py`, `engine/contour.py`, sample data,
`Symbol Library/`, releases, etc.) is intentionally **not** included. Only the
interpolation algorithm needed by the workbench's `单因素图制备` flow was copied
(goal §15: no whole-repo copy).

## Updates

This is a stable, SHApinned vendored dependency. To update, re-copy the
required modules from a specific upstream commit, update the SHA above,
re-verify byte parity, and re-run `tests/test_constrained_idw_integration.py`.

## License / attribution

Upstream `haiyou-visualization` © its authors. Integrated into
`paleo-workbench` for the constrained-IDW capability; this attribution and the
commit SHA above preserve source provenance.
