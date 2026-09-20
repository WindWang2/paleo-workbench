# Task 13 — acceptance ledger

## Verdict matrix (as of current candidate)

| Issue | Disposition | Repro evidence | Post-fix evidence |
|---|---|---|---|
| #1380 | fixed-on-main (3ae509d1) | n/a | viz_c.store_concurrency PASS (post) |
| #1381 | fixed-on-main (3ae509d1) | n/a | viz_c.store_concurrency PASS (post) |
| #1382 | fixed-on-main (3644d562) | n/a | ui_data_core.asset_view_guard PASS |
| #1383 | fixed-on-main (3644d562) | n/a | ui_data_core.asset_view_guard PASS |
| #1384/#1385/#1388/#1392 | line-14 scope | classified | — |
| #1386 | FIXED | ingest.parsers FAIL x3 (3 rows → 0; NBSP→0; float NBSP) | PASS x2 + ASan n/a |
| #1387 | FIXED | code-path (fail-closed contract) | pwb-platform compiles; no disk-full rig — noted |
| #1389 | FIXED (items 2+3; item 1 already fixed) | **SIGSEGV exit=139** on stale entry callback | PASS x2 + ASan+UBSan clean |
| #1390 | FIXED | OOB FAIL (garbage QVariant from columns_[6]) | PASS x2 + ASan+UBSan clean |
| #1391 | FIXED (all 4 items) | fold FAIL x2; ragged FAIL x2; saved-filter repro exit=1 | PASS x2 + ASan+UBSan clean |
| #1399 | fixed-on-main | n/a | pwb-platform compiles clean |

## Build/test commands (all under invoke-resource-gate.sh, j<=2)

- Configure: `invoke-resource-gate.sh Configure -s . -b build/cpp-integrated -c Release`
  with the integrated option set (PLATFORM+DATA+SCIENCE+INTEGRATION_TESTS+TOOLS+
  SEISMIC_*+MAPPING_KERNEL; PALEO_QGIS_* pointed at the main checkout's vendored
  SDK, read-only). Toolchain: ~/.local/opt/cmake-3.30.5 + ~/pwb-sdks ninja.
- Build: `invoke-resource-gate.sh Build -b build/cpp-integrated -t '<targets>'`
- Test: `invoke-resource-gate.sh Test -b build/cpp-integrated -r '<regex>'`,
  `QT_QPA_PLATFORM=offscreen` for Qt tests.

## Evidence record

- POST-FIX run 1 (2026-09-19): all 7 targets PASS — ingest.parsers (318
  comparisons), ui_data_core.asset_view_guard (48), ui_pages_data.smoke (73),
  ui_widgets.modelview (10), ui_shell.qt_widgets_smoke, ui_workers.lifecycle
  (3), viz_c.store_concurrency (3).
- POST-FIX run 2 (determinism): identical, all PASS.
- Adjacent ctest (13 tests across ingest/ui_data_core/ui_pages_data/
  ui_widgets/ui_shell/ui_workers/viz_c): 100% PASS, 1.96s.
- PRE-FIX run (production sources stashed to base, tests kept):
  - ingest.parsers: FAIL unicode_space_separators (expected 3 records, got
    0 — rows silently dropped), FAIL nbsp_separator (1→0), FAIL
    py_parse_float NBSP/U+3000 strip. 3 failures.
  - ui_data_core.asset_view_guard: FAIL x2 — "äöl" query vs "ÄÖL-Äquifer"
    asset → 0 rows; Cyrillic "пласт" vs "ПЛАСТ-Верхний" → 0 rows.
  - ui_workers.lifecycle: FAIL x2 — ragged vector<vector<double>> and
    vector<any> grid_z accepted silently (no PyValueError).
  - ui_widgets.modelview: FAIL data_column_out_of_bounds — foreign index
    col=6 on a 3-col model returned a garbage-but-valid QVariant.
  - ui_shell.qt_widgets_smoke: SIGSEGV (exit=139) — invoking the captured
    set_visible on the deleteLater'd FloatingPanel.
  - ui_pages_data saved-filter: micro-repro vs base chips.cpp —
    filter_query_from_dict(Json(42)) returns node_type='all' (silent
    reset), exit=1.
  - viz_c.store_concurrency: PASS on base (regression-only, as expected —
    #1380/#1381 fix predates this branch).
- ASan+UBSan post-fix (test TU + touched TU instrumented via real ninja
  compile/link lines, deps uninstrumented): modelview 10/10 PASS;
  lifecycle 3/3 PASS; asset_view_guard 48/48 PASS; qt_widgets_smoke all
  PASS — zero sanitizer reports on the previously-crashing/OOB paths.
- TSan for #1391.4 (algorithms() lock): not run — a reliable data-race
  repro needs concurrent register+enumerate; the fix is the same mutex_
  scoped_lock pattern used by register_kernel (inspection + symmetry).

## Known limits / honest gaps

- #1387: no disk-full injection rig offscreen — the fail-closed contract is
  verified by construction (write!=size || !flush → warn) and mirrors the
  existing save_style_sidecar pattern; not claimed as a simulated failure.
- #1389/#1390 Qt-view-layer paths verified offscreen; the DataAssetTable
  layoutChanged connect is compile+inspection verified (no dedicated Qt
  widget test home exists for that class).
- Sanitizer pass: done (ASan+UBSan, 4 instrumented pairs — see above).
- #1391.1 strictness: non-array/non-string `tags` and wrong-typed scalar
  fields warn rather than reproduce Python's `list()` corner acceptances —
  documented in findings.md.

## Independent review → fix → re-verify (round 4)

- Reviewer: subagent_explore, full-diff audit vs Python frozen sources.
- Actionable findings fixed: (1) `apply_saved` falsy-payload no-op parity
  (`query:{}` must not emit an all-reset — Python `if not stored: return`);
  (2) whitespace set completed (U+0085 NEL, U+001C-U+001F); (3) non-ASCII
  casefold sort coverage added; doc drift corrected.
- Recorded limitations (not defects of this fix): final-sigma context rule
  for `str.lower()`, raw-pointer floatable registries on pages without a
  replacement seam, domain↔interchange casefold duplication, ASCII-folded
  SQL `name_search` (D6).
- Re-verify: rebuilt ingest.parsers + ui_pages_data.smoke, ctest 2/2 PASS
  (post-review state, gate-held run).
