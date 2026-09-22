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

- `drawing/single_factor/constrained_engine.py` carries host performance
  modifications (numerical results are unchanged; verified by the parity
  tests in `tests/test_constrained_idw_engine_parity.py`, which compare the
  vectorized implementations bit-for-bit against the reference scalar loops):
  - `_barrier_blocked_mask` / `_offset_barrier_blocked_mask`: vectorized
    replacements for the per-(cell, well, segment) `is_blocked_by_barrier`
    LOS loop, with identical `strict_segments_intersect` arithmetic.
  - `_interpolate_grid_point_euclidean`: vectorized well-candidate selection
    for the pure-Euclidean IDW case (identical sort / weighting semantics).
  - `build_barrier_blank_mask`: vectorized stadium-distance buffer instead of
    the sampling + per-cell `_point_within_polyline_stadium_buffer` loop.
  - `smooth_valid_grid` / `refine_domain_boundary_transition`: vectorized
    neighbor-weight accumulation (same per-element float operations and
    accumulation order).
  - `apply_well_residual_anchoring`: per-well patch windows vectorized with
    NumPy (same per-element arithmetic; `np.hypot` vs `math.hypot` may differ
    by one ulp on ~0.6% of distances, so anchoring parity is asserted within
    tight float tolerance).
- `drawing/single_factor/fast_grid.py` reuses a module-level
  `ThreadPoolExecutor` across calls instead of constructing one per
  interpolation (same work distribution, no numerical change).
- `drawing/single_factor/constrained_engine.py` — **gap-fill hull fix
  (2026-08-22, issue #924)**: the host-added "skip the data-hull raster on the
  default limit-to-coverage path" optimization accidentally fed
  `data_hull_active = mask is not None` a `None`, which flipped
  `gap_iterations` from upstream's `min(8, 3)` to `0` and left interior holes
  unfilled. The skip branch now records `data_hull_present =
  data_hull_exists(wells)` and the gap decision reads
  `(mask non-empty) or data_hull_present`. Upstream parity restored: with this
  fix the direction-line fixture that previously diverged (173 NaN cells) is
  bit-identical to upstream again. Known approximation: in the skipped-raster
  path, existence (`data_hull_exists`) stands in for "raster has any cell";
  upstream would report inactive only if the materialised raster were empty,
  which requires a hull containing zero grid-cell centers.

- `drawing/single_factor/constrained_engine.py` — **cell-batched Euclidean
  kernel (2026-08-23, issue #933)**: no-direction barrier runs now execute the
  whole point-path domain through `_interpolate_euclidean_cells_batch`
  (cell-dimension vectorization: distance matrix, label/LOS block accounting,
  radius passes with per-pass relaxation, stable top-k, grouped-by-k exact
  pairwise reductions). Bit-for-bit identical to the per-cell path — verified
  by `tests/test_constrained_idw_algorithm.py` (values and blocked-well
  counters, incl. exact-hit, zero-decluster and label-gating branches) and an
  end-to-end 200²×300-well grid comparison against the pre-change engine
  (bitwise-equal `grid_z`, identical diagnostics). Kernel 1.9 s → 279 ms;
  end-to-end `generate` 2.24 s → 0.94 s. Direction-active runs keep the
  per-cell path (their curve-corridor caches are genuinely per-cell).

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
