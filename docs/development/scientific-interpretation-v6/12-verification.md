# 12 — Verification

## New test files (13, ~130 tests)
| file | covers |
|---|---|
| test_well_science.py (29) | unit classification/refusal, gap-preserving resample, ft-axis shift, NULL policy provenance |
| test_depth_unit_consumers.py | overlay/engine/well-tie/cursor unit gates |
| test_well_identity.py (18) | duplicate-name tops/shifts/documents; 10k wells × 3k extracts binding = 0.21 s |
| test_coordinate_hub_honesty.py (6) | unconfigured-grid refusal, typed NO_GRID |
| test_engine_gap_submission.py (6) | NaN gaps reach the native backend; #402 intact |
| test_constraint_capabilities.py (11) + test_constraint_routing_honesty.py (5) | matrix + end-to-end diagnostics |
| test_kriging_v2.py (10) | anisotropy transform/solve, explicit params, fit diagnostics, GRF evidence |
| test_evaluation_workbench.py (12) | LOWO folds, metrics semantics, recommendation report |
| test_constrained_idw_diagnostics.py | adapter facts survive into provenance |
| test_geometry_units_qa.py (12) | CRS-unit areas/lengths, QC records |
| test_factor_fusion_v6_honesty.py (7) | CRS refusal, unit warnings |
| test_harness_scientific_actions.py (7) | honest unavailable/not-found/unknown-unit paths |

Engine submodule: test_segy_scalar_geometry.py (9),
test_time_depth_range_honesty.py (6) — 46 package tests green.

## Regression posture
Every touched suite green (curve interpretation, well-log load/adapter ×3,
stratigraphy, round2, view coordination ×2, domain-coords contract, joint
host ×5, factor interpolation ×3, kriging fallback, interpolation
evaluation, fusion, map product ×3, mapping pipeline, adversarial polygon
suites, harness ×4, workarea/stratigraphy binding).

## Pre-existing failures on main (NOT caused by V6; verified by stash)
- tests/e2e/test_integrity_guard.py::test_no_tautological_assertions
  (5 tautological assertion sites in OTHER test files — engine-adjacent
  test debt on main)
- test_native_backend.py::test_map_edit_core_version_and_acceleration +
  test_native_factor_map.py (7): require built C++ extensions (absent on
  this Windows venv; qgis/welllog_binding/opengl legs skip by design)
- test_mapping_document_io.py::test_malformed_coordinates… (fails on
  pristine main too)
- hard Windows crash in test_lod_render_path.py fixture on this machine
  (environment; segyio/zarr native interaction)

## Full-suite gate
Fast gate `-m "not slow and not opengl and not qgis"` run at milestone
boundaries; final full-suite verification runs before the PR (see PR body).

## Review rounds (§22) — 3 independent deep reviews, all P0/P1 fixed
Round 1 (scientific): fixed — kriging auto-fit double-transform (the fit ran
in a ratio² frame; 20% range / 32% sill error on anisotropic fields, now
single-transform + regression test), engine false "anisotropy ignored" on
every run and its contradiction when kriging applied it, MultiPolygon ring
access, meters-LAS losing its declaration.

Round 2 (architecture): fixed — meters-LAS loader wrap condition (every V6
unit gate failed closed on properly declared meters files), publish-gate CRS
check reading a nonexistent collection (would have refused every product
with a composition ref → now an honest verifiability warning, see 13),
calibration action reading a nonexistent context attr + hub private (now
per-well UNKNOWN when no hub threaded, public accessor only),
kriging_diagnostics persisted to task provenance, geometry CRS predicate
delegated to crs_policy (was a second, disagreeing authority),
factor.evaluate_methods no longer fabricates a method ranking from one
proxy fold engine.

Round 3 (numerical/adversarial): fixed — the double-transform fit (probe:
13.6%-of-std prediction error), azimuth 0° anisotropy loss, anonymous
tops-overlay leakage (no-id no-name target received ALL wells' tops),
projected "WGS 84 / UTM…" strings misread as geographic (≈m² wrong by
10^11), descending-axis interp_gap_preserving now raises, evaluate_request
dedupe, KB lookup keyed with the shift key, wrapper declared-flag
consistency note.

Also fixed (main-branch debt surfaced by the audit): the 5 tautological
assertions behind tests/e2e/test_integrity_guard failures — each un-masked
assertion now checks real behavior (two were masking wrong assertions,
fixed to match actual table/model contracts).
