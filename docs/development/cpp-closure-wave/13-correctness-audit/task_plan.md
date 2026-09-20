# Task 13 — C++ 转换缺陷复现与修复 (correctness audit)

- branch: `codex/cpp-close-13-correctness-audit-20260919`
- worktree: `/home/kevin/project/worktrees/cpp-close-13-correctness`
- base SHA: `06211541ae1ccce22b0d5ba9258ce722170ca98b` (origin/main, re-fetched 2026-09-19)
- coordination file: `.git/codex-coordination/cpp-close-wave/13-line.json`
- budget note: this platform (Devin Desktop) has no `/goal` or `/goal-loop` command —
  the file-persisted loop documented in this directory is the goal loop. Token budget
  request 300M is a ceiling, not a target; metering is per-LLM-call on this platform and
  not separately enumerable, so spend is tracked qualitatively via progress.md rounds.

## Scope (exclusive)

Correctness defects in already-converted capability only: reproduction test -> minimal
fix -> adjacent regression. No feature development (01-12), no perf refactors (14).

## Defect inventory and status @ base SHA

| Issue | Sev | Status on 06211541 | Disposition |
|---|---|---|---|
| #1380 store lock / SEG-Y publish on worker | P1 | FIXED by 3ae509d1 (+bf374a79 movability) | regression-confirm via tests/cpp/viz_c/store_concurrency_test.cpp |
| #1381 TaskRuntime publisher concurrent store write | P1 | FIXED by 3ae509d1 | regression-confirm (same test + catalog_publisher lock) |
| #1382 CatalogRowOverview::asset dangling | P2 | FIXED by 3644d562 (shared_ptr owner) | regression-confirm via ui_data_core.asset_view_guard |
| #1383 asset_view_from_object variant miss | P2 | FIXED by 3644d562 (get_if chain + null guards) | regression-confirm (same test) |
| #1384 prediction inference hot path | P2 perf | OPEN | line 14 scope (performance) — classified, not fixed here |
| #1385 QGIS mirror double conversion | P2 perf | OPEN | line 14 scope — classified |
| #1386 well_tops py_split ASCII-only | P2 | REPRODUCIBLE — `cp->cp < 128` gate still present | FIX |
| #1387 QFile::write unchecked (template + diagnostics) | P2 | REPRODUCIBLE — both sites unchecked | FIX |
| #1388 table big-data path | P2 perf | OPEN | line 14 scope — classified |
| #1389 dangling raw pointers (3 sites) | P3 | item1 FIXED (QPointer on shortcuts_); items 2+3 REPRODUCIBLE | FIX items 2+3 |
| #1390 ObjectTableModel 3 items | P3 | REPRODUCIBLE — no col bound, no isfinite, modelReset-only | FIX |
| #1391 parity punchlist (4 items) | P3 | all four REPRODUCIBLE | FIX |
| #1392 hygiene punchlist | P3 perf/hygiene | OPEN | line 14 scope (dedup/perf) — classified |
| #1399 version_id undeclared under CONV_30+VIEWER | build | FIXED on main (version_id hoisted + !CONV_30 guard) | verify compile in platform build |

## Fix plan (minimal, surgical)

1. #1386 — export `detail::cp_is_unicode_space` (py_compat.hpp), reuse in `py_split`;
   extend oracle generator with U+3000/U+00A0-separated case, regenerate frozen fixture
   from real Python (venv: oracle-venvs/conv11), C++ oracle test fails pre-fix.
2. #1387 — check `write()==size && flush()` at both sites; QMessageBox on failure
   (save_style_sidecar fail-closed pattern).
3. #1389 — `floatable_` -> `QPointer<QWidget>`; re-register `data:inspector` on
   `set_inspector_panel`; `floatable_panel_entries` lambdas capture QPointer.
4. #1390 — `data()` column bound; `sort_key_of` non-finite -> tier 2 (absent);
   `DataAssetTable` also connects `layoutChanged` -> `on_model_reset`.
5. #1391 — `filter_query_from_dict` -> `std::optional` (warning box becomes reachable);
   Unicode-aware case fold for asset search; `any_to_grid` ragged-row -> PyValueError;
   `algorithms()` takes `mutex_`.

## Function/file leases (registered in 13-line.json)

- libs/ingest: py_compat.{hpp,cpp} `cp_is_unicode_space`, well_tops.cpp `py_split`; oracle generator + fixture.
- libs/ui_data_core: filter_index.cpp `lower_ascii` (rename to Unicode fold).
- libs/ui_pages_data: chips.cpp `filter_query_from_dict`; qt/filter_chips_bar.cpp `apply_saved`; src/table_model.cpp `normalize_search_text`; qt/data_workspace.cpp `floatable_` + `set_inspector_panel` + `persist_docked_sizes`; qt/data_asset_table.cpp `set_model`/`set_paged_model` connect set.
- libs/ui_widgets: object_table.cpp `data`, `sort_key_of`.
- libs/ui_shell: float_controller.cpp `floatable_panel_entries`.
- libs/ui_workers: contour_draft.cpp `any_to_grid`.
- libs/application: algorithm_runner.cpp `algorithms`.
- apps/paleo_workbench_platform: well_log_track_panel.cpp `on_save_template` (line-05 adjacent file; minimal guarded fix, lease declared); main_window.cpp diagnostics-save lambda inside `showDiagnosticsDialog` body (function-level lease inside line-12 file).

## Verification plan

- developer-fast preset covers ingest (CONV-19 implied via DATA) + ui_workers needs CONV_22.
- Platform preset needed for ui_* Qt libs + apps (Qt6 6.11.2 system + vendored QGIS SDK
  at /home/kevin/project/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output,
  read-only). Configure through invoke-resource-gate.sh, jobs<=2 default.
- ASan/UBSan: attempt a focused sanitizer build of ui_data_core/ui_widgets tests if the
  platform configure is cheap enough; otherwise record as environment-limited.
- Two consecutive runs for the touched test binaries.
