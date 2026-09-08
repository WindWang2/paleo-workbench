# 05 — Verification

Layered per goal §18. Status legend: ✅ run+green on this machine,
⏳ runs when the vendor build + bridge complete (see §6 of 04-notes for the
runtime recipe), ➖ out of scope (100GB seismic — hard exclusion).

## 1. Pure-domain layers (always run, worktree venv)

| Suite | Covers | Result |
|---|---|---|
| tests/test_stage_p0_regressions.py | P0-1 status vocabulary, P0-2 payload staging | 7 ✅ |
| tests/test_geological_layer_spec.py | §3 spec registry, policy consistency, bindings | 15 ✅ |
| tests/test_qgis_layer_schema.py | fields_json wire, geometry names, ValueMap/Range | 6 ✅ |
| tests/test_geometry_operations.py | §4 facade fallback engines, disclosure, units | 21 ✅ |
| tests/test_scalar_data_mirror.py | §5 spec/classification (9) + GDAL mirror (4, ⏳ gdal env) | 9 ✅ + 4 ⏳ |
| tests/test_scalar_publish.py | §5 payload builders, honest unavailability | 7 ✅ |
| tests/test_presentation_state.py | §8 derivation, field-set guard | 15 ✅ |
| tests/test_factor_layer_products.py + test_constraints_sync.py | §10–12 builders, sync-back fingerprints | 22 ✅ |
| tests/test_mirror_delta_publish.py | §9 ledger tokens, delta computation, fallbacks | 9 ✅ |
| tests/test_geological_symbols.py | §6 symbols, role-compat, spec cross-check | 24 ✅ |
| tests/test_cartographic_qa.py | §14 rules + localization + skip honesty | 20 ✅ |
| tests/test_layout_export_mapping.py | §13 element mapping, hybrid itemization | 11 ✅ |
| tests/test_integrated_compilation.py | §12 fusion entry incl. dispatcher | 15 ✅ |

Neighbouring regression suites (stage e2e, factor pipeline, workspace
domain, topology, map product, composer, export parity) — green after each
phase; consolidated numbers in §3.

## 2. Bridge layers (DONE — first Windows run, 2026-09-08)

Vendor QGIS 4.2.0 (core/gui/analysis + srs.db) built with MSVC 14.38 at a
neutral reusable path (see 04-implementation-notes); bridge extension links
Qt6Core/Gui/Widgets/Xml/Svg/PrintSupport + 3 qgis libs.  Runtime recipe
(tests/conftest.py): two DLL dirs + conda-Qt-first preload + geo-C-lib
preloads (bisected minimal set — extra dirs break the loader with
same-named DLLs).

| Suite | Covers | Result |
|---|---|---|
| tests/test_qgis_scalar_raster_v7.py (new) | renderer XML codec, raster mirror lifecycle + project-XML roundtrip, bad-payload rejection; canvas delta; offscreen scalar render; style-reuse diagnostics | 8 PASS |
| tests/ -m qgis (all files) | full existing bridge contract on Windows, first run | 192 PASS, 1 skipped, 1 teardown-only error (shiboken QMenu lifetime in a file untouched by this branch) |

## 3. Full-suite regression

- Baseline (main @ db21f6cf, this machine): first run lost its summary to a
  faulthandler dump at exit; second run hung >900 s in
  test_ui_adversarial_v5::test_theme_switch_with_open_project_shell (passes
  standalone in 26 s — full-suite interaction; documented in 08 §7).
- Current-branch run: `pytest tests -m "not slow"` minus the hang test minus
  perf/e2e/lod_render_path — RESULTS PENDING (in flight; final numbers
  recorded below when complete).

<!-- FINAL_REGRESSION_RESULTS (2026-09-08, worktree venv, offscreen)
- Goal-owned + adjacent: 331 PASS (batch-mine)
- core2 (catalog/well/harness): 306 PASS
- mapping (stage/render/composer/export): 101 PASS
- workflow (fusion/interp/QA): 212 PASS
- UI: composite_gis + composite_editing 53 PASS (after fixing the
  geometry_service dict-contract regression the branch introduced)
- -m qgis: 192 PASS (above)
- Pre-existing/env (verified on pristine main or untouched files):
  catalog manifest human-readable (fails on main too);
  composite_qgis_canvas 5 bridge-missing fails (identical on main);
  theme-switch + seismic-3D suites hang single-process full runs here
  (pass standalone/in batches; offscreen Qt event-loop exhaustion).
-->

## 4. Performance

See 06-performance.md (mirror 50–1000 layers, 100k-feature delta edit,
500×500 fusion, budgets, vendor-build cost).

## 5. Excluded

- 100GB seismic support/benchmark/optimization — goal hard exclusion;
  seismic surfaces only via synthetic/small/medium fixtures already covered
  by the existing suites. ➖
