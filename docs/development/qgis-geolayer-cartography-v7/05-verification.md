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

## 2. Bridge layers (⏳ vendor build)

| Suite | Covers |
|---|---|
| tests/test_qgis_scalar_raster_v7.py (new) | §5 renderer XML codec round-trip, raster mirror lifecycle + project-XML roundtrip, bad-payload rejection; §9 canvas delta apply + stale-base fallback; offscreen scalar render pixels; style-only mirror reuse diagnostics |
| tests/ -m qgis (46 pre-existing files) | the full existing bridge contract on this machine for the first time |

## 3. Full-suite regression

- Baseline (main @ db21f6cf, this machine): first run lost its summary to a
  faulthandler dump at exit; second run hung >900 s in
  test_ui_adversarial_v5::test_theme_switch_with_open_project_shell (passes
  standalone in 26 s — full-suite interaction; documented in 08 §7).
- Current-branch run: `pytest tests -m "not slow"` minus the hang test minus
  perf/e2e/lod_render_path — RESULTS PENDING (in flight; final numbers
  recorded below when complete).

<!-- FINAL_REGRESSION_RESULTS -->

## 4. Performance

See 06-performance.md (mirror 50–1000 layers, 100k-feature delta edit,
500×500 fusion, budgets, vendor-build cost).

## 5. Excluded

- 100GB seismic support/benchmark/optimization — goal hard exclusion;
  seismic surfaces only via synthetic/small/medium fixtures already covered
  by the existing suites. ➖
