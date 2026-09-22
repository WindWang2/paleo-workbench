# 00 — Baseline (post-V14-merge final audit)

- **Date**: 2026-09-21
- **DEFAULT_BRANCH**: `origin/main` (confirmed via `git symbolic-ref refs/remotes/origin/HEAD` and GitHub)
- **Base SHA**: `7bfe7585` (Merge PR #1442 `fix/cpp-build-run`)
- **Audit/fix worktree**: `/home/kevin/project/paleo-workbench-cpp-final-audit-fix`, branch `fix/cpp-final-postmerge-audit` (created from `origin/main`; user's primary workspace left untouched — it holds uncommitted in-progress changes from a prior session, out of scope).

## Recent Change Map (merges into main, newest first)

| PR | Merge SHA (line) | Modules | Scope highlights | Known limitations declared |
|----|------------------|---------|------------------|----------------------------|
| #1442 | 6739f52f | platform CMake, qt_session_policy, preview widgets, ui_workers, viz docks | Build/run closure after V14 merge storms: preprocessor damage in `pdf_preview_widget.cpp`; nested-namespace damage `main_window.hpp`; V14 members guarded behind `PWB_WITH_CONV_27/16/STAGE_FLOW`; **CMake wiring: VIZ-B dock gate moved to root post-slices block (apps/ subdir processed before viz slices → gate could never fire)**; self-recursive POSIX shims (`setenv/unsetenv/getpid` calling themselves); preview `task_key` scoped to request generation; `preview_rendered` empty-state suppression; oracle regeneration for `ordinal` field | none declared; ctest 236/236, capabilities 20/20, self-check 13/13 claimed |
| #1441 | 9cb52945 (merge) | mapping_kernel, factor_host, closure_workflow, ui_workers, platform `factor_prepare_production` | Native constraint + single-factor pipeline: real kernels IDW/Kriging/constrained-IDW, constraint-line consumption, fingerprint reuse, contours, provenance, linked well analysis; replaced staging fake worker ("网格计算内核未接入") | see docs/development/v14-constraint-factor/* |
| #1440 | 1a559029 | mapping_document, ui_composite, layout_export, closure_workflow, cartography | Integrated compilation publish: 9 built-in templates, real SVG preview renderer (24 element types), export executor SVG/PNG/PDF, fusion seams production impl (catalog pin load + current 3-level resolve + missing-pin reject), QC provenance registration via workflow rail, export_artifacts | FNV-1a vs Python `hash()` documented divergence |
| #1439 | 958348ca | ui_pages_data, project, catalog, platform `closure_data_workspace` | Data fabric: entity workspace read model, multi-file well workspace, link ordinal, manual-edit provenance, ingest-plan product UI, lineage helpers | see docs/development/v14-data-fabric/* |
| #1438 | e1449c5d | ui_workstation, ui_stageflow, apps main_window | Three-stage workbench UX: stage bar mounted into WorkstationFrame app bar (was constructed-but-never-mounted), per-stage panel visibility matrix, command palette 17 commands (was zero registrations), job center dock provider, mapping page data link | none declared |
| #1437 | 637c2bd2 | workspace, mapping_document, ui_widgets/qgis, native/qgis_render_bridge, qgis_layer_control | QGIS layer control plane: tree reconcile (system/factor/user groups), staged group visibility policies, edit-target reassignment, user tree edits adopted at save, usages_of queries, export in tree order, layer state chips | QGIS QgsLayerTree stays runtime authority; domain workspace JSON persistence authority |
| #1436 | 957e850f | job_runtime, ui_data_core, interchange, closure_workflow/map_compile, workflow_runtime, ui_canvas/qt | Residual conversion: ResourceBudget/MemoryPressureMonitor/ResourceGovernor; resources services (collect_assets/scanner/import/export/facies_groups + OOXML xlsx); map_compile draft+production (byte-level payload parity); run_orchestration; ~1900-line QPainter fallback map render backend | **Declared deltas NOT closed**: catalog write path (`lifecycle.py` 15 `register_*` on `service.py` 4.7k lines); CONV-32 `_drive_parallel` node-pool order frozen; product_qa staleness verdict (C++ catch-degrades); XML … |
| #1435 | 10657f85 | root CMake, cmake/Pwb*, tools/migration, apps | Migration truth matrix 678/678 modules (115 NATIVE_PRODUCT / 79 NATIVE_LIBRARY_NOT_WIRED / 70 PARTIAL_NATIVE / 414 LEGACY_REFERENCE); `final-closure-gate.sh`; native install excludes Python artifacts | binary/runtime-independence evidence pending (no Qt/QGIS build in that env) |
| #1434 | c3621fa2 | workflow_graph, curve_expr, polygonization, ui_widgets/qgis mirror, ui_data_core tables, CI env | Open-issue batch: CONV-25 dict semantics, curve_expr Call(Attribute) rejection, polygonize r[0] closure, doc_id index, QueryPlan parse-once, decorate-sort, strip/lower_ascii convergence, overlay JSON dirty-cache, CI conftest budget cores etc. | issues left open pending verification (this audit's job) |
| #1433 | — | mapping authoring line 08 | data prep / map editing / composition docs productization | — |
| #1413–#1432 | — | 14 cpp-close waves | catalog/project, workflow runtime, science prediction, data preview, well/crosswell, joint3d, seismic display, mapping authoring, review/publish, interchange, agent harness, product integration, correctness audit (#1386-#1391), performance | — |

## Open issues at audit start (19)

- CI family: #1427 (2-core CI budget assumptions), #1428 (i18n/locale + integration regressions 6 items), #1429 (Windows access violation after test_project_lifecycle), #1430 (vendored QGIS moc version mismatch 6.11.1), #1431 (shapefile sidecar invalid geometries)
- Perf/P2: #1385 (QGIS mirror/export per-feature conversions), #1388 (table big-data path ×4)
- Hygiene/P3: #1392 (strip/lower_ascii dup + dead code + PreviewCache move + overlay per-frame JSON)
- CONV bugs: #1357 (curve_expr stod overflow → out_of_range vs Python inf), #1358 (polygonize ring closure parity)
- CONV-25 family: #1339 (attr_str `or ""` falsy collapse), #1340 (rebuild dict overwrite semantics), #1341 (available_evidence selector bypasses parse), #1342 (D3 ring-membership doc claim), #1343 (text/iteration semantics punchlist), #1344 (contracts_test gaps), #1345 (workflow_graph public surface + hygiene)

**All of #1339–#1345/#1357/#1358/#1385/#1388/#1392/#1427–#1431 are claimed fixed by merged PR #1434 but remain open → stale-status verification required (see 01).**

## Environment

- Linux x86_64 (CachyOS), 392G free disk. Qt/QGIS vendored SDK presence to be verified (`/tmp/qgisqt`, `build/` caches in the *user workspace* — this worktree must build its own).
- Resource discipline: CMAKE_BUILD_PARALLEL_LEVEL ≤ 4, CTEST_PARALLEL_LEVEL ≤ 2.
- `gh` authenticated (issues/PR visible). No open PRs at start.
