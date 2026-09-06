# Progress — Scientific Interpretation & Algorithm V6

## Session 2026-09-07
- Worktree .worktrees/scientific-interpretation-v6 (branch feat/scientific-interpretation-v6 off main 295fabc3)
- Submodules initialized (geo-viz-engine 5e03beba → submodule branch feat/scientific-interpretation-v6 created; well-log-engine f845e7ab)
- uv venv cp312 + geoviz editables; fast-gate baseline: PRE-EXISTING main failure
  tests/e2e/test_integrity_guard.py::test_no_tautological_assertions (5 tautology sites);
  test_native_backend.py::test_map_edit_core_version_and_acceleration fails on pristine
  tree too (env: no native build); hard Windows crash in test_lod_render_path.py
  (seismic_transcode fixture) on this machine — environment, pre-existing.
- Milestone commits:
  - 7d24ede7 docs(v6): audit baseline 00-baseline.md (A–Q, P0/P1/P2 register)
  - 4677c0f0 feat(well): scientific contract §2–4 (units/null/gaps) — am. to d00019d8? NO:
    d00019d8 amended (baseline logs removed, gitignored)
  - df4b31d8 feat(well): identity + registry scale §5–6 (10k wells × 3k extracts = 0.21 s)

## Test results
- tests/test_well_science.py 29 passed
- tests/test_depth_unit_consumers.py passed (after impl)
- tests/test_well_identity.py 18 passed
- Regression blocks (curve_interpretation, well_log_load, engine adapter, strat tests,
  round2, well_tie, audit_viz_welllog, workarea/stratigraphy binding) all green
- Pre-existing failures documented above; NOT caused by V6 changes (verified by stash)

## Notes
- geo-viz-engine submodule branch feat/scientific-interpretation-v6 created for
  SEG-Y scalar/geometry + engine gap work (§7/§9)
- Fixture convention: unit envelope mandatory for unit-gated consumers; synthetic
  data declares meters by construction (prediction_helpers wraps)

## Session 2026-09-07 (continued)
- §7 gap-honest engine submission [70e7097e]
- §8–9 hub grid gate + SEG-Y scalar/geometry + TD range [f4854615; engine 83ae13c8]
- §10 capability matrix + honest routing [0e0119b5; engine commit 2]
- Pre-existing main failures (NOT V6): test_integrity_guard tautologies (5 sites),
  test_native_backend map_edit version (env), test_native_factor_map (7, needs native build),
  test_mapping_document_io malformed-coords (verified by stash)
- env: hard crash test_lod_render_path (Windows), skipped suites: qgis/welllog_binding/opengl

## Remaining
§11 kriging V2 (anisotropy+nugget settable+diagnostics; unify numpy fallback fitter)
§12 constrained IDW magic constants documented + diagnostics preserved in from_constrained_idw_dict
§13 evaluation workbench (RMSE/MAE/bias/R²/coverage; K-fold/spatial/LOO-well; recommendation report)
§14 factor contract (unit-vs-magnitude check); §15 contour/polygon QA (CRS-unit areas P0-10, nodata counts, thresholds recorded)
§16 fusion (unit check, CRS compare, variance persistence, sensitivity wired); §17 publish gate
§18 QC model; §19 harness actions (15 missing; ActionResult.provenance)
§20–21 perf+tests; §22 3 reviews; §23 docs 01-13; §24 submodule bumps+PR
