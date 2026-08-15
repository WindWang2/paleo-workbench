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
  settings plumbing (pure; see *Local modifications* below — `performance.py`
  is the one vendored file that is **not** byte-identical to upstream).

The package `__init__.py` files here are Qt-free stubs (the upstream
`drawing/__init__.py` and `drawing/single_factor/__init__.py` import PyQt6 and
the GUI workflow, which a PySide6 host must not load).

The copied modules are **byte-for-byte identical** to the upstream SHA above
(verified at vendor time), **except for the local modifications listed below**.

## Local modifications

- `drawing/compute/performance.py` was rewritten by the host in the two
  persistence helpers (numerical behavior of the interpolation path is
  unchanged):
  - Upstream's lazy `from PyQt6.QtCore import QSettings` import was **removed**.
  - `_load_from_qsettings` now reads the process-level environment knob
    `PALEO_HAIYOU_CPU_PERCENT` (integer CPU-percent budget) instead of
    QSettings, and additionally pins `hardware_accel = False` /
    `gpu_percent = 0`.
  - `_save_to_qsettings` is a no-op (the host owns any GUI preference storage).
  - The helper docstrings/comments describe the PySide host boundary.

- `drawing/single_factor/constrained_engine.py` has two host-driven behavior
  fixes (see issues #370 / #382 in `paleo-workbench`):
  - Barrier blanking band: the returned display grid keeps the corridor as
    nodata (NaN) instead of filling it with `value_min` (upstream's "green
    band = 0" convention for a normalized [0,1] surface). The host passes
    real factor units, so the old fill fabricated an observed-minimum band
    along every fault.
  - Barrier line-of-sight: when active barriers exist the engine always uses
    the per-cell LOS point path (upstream switched to a vectorized batch +
    narrow near-barrier refine above 4096 domain cells, which leaked values
    past dead-end barriers on larger grids; the host caps grid resolution at
    200, so the point path stays responsive).

  To re-verify the parity of every other vendored file against the upstream
  SHA, diff this directory against the upstream checkout and expect
  `performance.py` and the two `constrained_engine.py` hunks above to differ:
  `grep -rn "PALEO_\|PySide\|PyQt6" .` should hit only `performance.py`.

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
