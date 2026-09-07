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

## Session 2026-09-08 (qgis-geolayer-cartography-v7)
- Worktree .worktrees/qgis-geolayer-cartography-v7 off main db21f6cf; submodules pinned; venv cp312 + geoviz + build deps OK
- 4 parallel deep audits complete → docs/development/qgis-geolayer-cartography-v7/audit-*.md + 00-baseline (defect register P0 1-4, P1 5-15, P2 16-19)
- VENDOR BUILD (D1): conda env paleo-qgis-deps (qt6-main 6.11.2, qca-qt6, expat dev, gdal/geos/proj/spatialite/etc); qt6keychain v0.14.0 built from source; vendored QGIS CONFIGURE PASSED on Windows after 2 documented patches (version.rc.in restored, CheckFunctionExists include); build -j2 running in background (1.5-4h)
- Baseline pytest rerun in background (first run lost summary to faulthandler dump, exit 0)
- Commits: 9cc04645 (docs), d6f63fba (build patches)

## Session 2026-09-08 (continued, qgis-geolayer-cartography-v7)
- Commits: c1a40d9a P0 fixes, bf3784ae GeologicalLayerSpec V2, 5e4aefce §4 geometry
  facade+dedup, 96a9a05e §5 scalar raster (py+c++), e825dcfe §8 presentation
  (agent), bb40a61c §10-12 stage producers (agent; found+fixed 2 latent bugs:
  contour overlay always failed, stage_save unpack crash), d2a5f0e1 §9 delta
  publish + benchmarks (1000-layer noop 30ms)
- Vendor build in progress: 959 core objs, qgis_native.dll linked; core/gui/analysis pending
- Baseline rerun died at test_ui_adversarial_v5 theme-switch (passes standalone;
  full-suite pollution or build contention) — rerun post-build
- Native exts (grid_render_core etc.) built in worktree venv; grid_array getter added
