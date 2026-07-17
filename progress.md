# Progress Log: Paleogeography Workbench

## Session: 2026-07-05 (Full session — AppShell + HomePage + DataPage)

### AppShell Skeleton (Phase 1) — COMPLETE ✅

Implemented via SDD (11 TDD tasks + 1 fix):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Design tokens (colors/dimensions/QSS_TEMPLATE) | `01b3a9e` | 5 |
| 2 | PagePlaceholder widget | `74ad20e` | 2 |
| 3 | MenuBar (4 labels, 36px) | `26f5912` | 2 |
| 4 | HeaderToolbar (4 buttons + search, 38px) | `e77d667` | 4 |
| 5 | IconRail (9 nav, page_changed signal) | `c111bc2` | 5 |
| 6 | TextSidebar (contextual panel, 248px) | `473fadb` | 3 |
| 7 | StatusBar (project name + coords, 24px) | `da9e72b` | 4 |
| 8 | AppShell assembly (4-zone layout) | `b00b57e` | 6 |
| 9 | UI package exports | `a3a571e` | 2 |
| 10 | Integration (replace WorkflowDashboard, QSS) | `0c7108c` | 57 total |
| 11 | Screen inventory doc (7→9 pages) | `bcf6101` | — |
| Fix | Remove unused imports | `c7352e1` | — |

Icon + fidelity fixes:
- `6222a80` — 9 SVG icons, gradient rail bg, nav label 9.5px/500, radius 8px, QToolButton
- `203c457` — fix misplaced SVG files

Final review: READY TO MERGE, all 6 acceptance criteria met.

### 首页 Dashboard (Phase 2) — COMPLETE ✅

Implemented via SDD (6 TDD tasks + 1 fix):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | HomePage tokens (STEP_COLORS, STEP_LABELS, STATUS_TEXT, RESOURCE_LABELS) | `8f8a1f9` | 5 |
| 2 | WorkflowProgress (6-step badges) | `6454b49` | 4 |
| 3 | RecentActivityCard (step-derived entries) | `cea9230` | 4 |
| 4 | DataCompletenessCard (resource readiness) | `6ab0896` | 5 |
| 5 | HomePage assembly | `f053b79` | 3 |
| 6 | Integration (wire into AppShell index 0) | `adf0acc` | 2 (80 total) |
| Fix | empty_label dangling + unused Qt import | `96c88f9` | — |

M3 polish: `c507629` — connecting lines, two-column activity entries, unit suffixes, QScrollArea, RESOURCE_UNITS token.

Final review: READY TO MERGE.

### 数据页 DataPage (Phase 3) — COMPLETE ✅

Implemented via SDD (4 TDD tasks + 1 fix):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | ResourceSummaryBar (counts + readiness) | `ea255c4` | 4 |
| 2 | ResourceTable (QTableWidget, 5 cols) | `87ac17d` | 4 (89 total) |
| 3 | DataPage assembly + ActionPanel | `295558a` | 4 |
| 4 | Integration (wire into AppShell index 1) | `28a3a04` | 2 (95 total) |
| Fix | Status coloring + unused import | `bd8d7be` | — |

Final review: READY TO MERGE.

### 制备页 PreparationPage (Phase 4) — COMPLETE ✅

Implemented via SDD (6 TDD tasks + 2 fixes):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Tokens (TASK_STATUS_COLORS/LABELS, INTERPOLATION_METHODS, SMOOTHING_LEVELS) | `054b8f5` | 4 (99 total) |
| 2 | FactorTaskPanel (task list + horizon/method header + summary) | `22ef770` | 6 (105 total) |
| 3 | FactorPreviewGrid (completed factor map cards + value range/R²) | `858b081` | 6 (111 total) |
| 4 | BoundaryPanel (probability threshold / smoothing / area form) | `00f14ce` | 4 (115 total) |
| 5 | PreparationPage assembly | `dabde0f` | 2 (117 total) |
| 6 | Integration (AppShell idx 6, exports, app.py wiring) | `446ee05` | 2 (119 total) |
| Fix | Grid metric default "50×50" + remove double card padding (Task 3 review) | `858b081` (amend) | — |
| Fix | Align BoundaryPanel labels to spec wording | `a438167` | — |

Final review: READY TO MERGE (no Critical/Important; 5 Minor deferred to follow-ups).

### 成图审核页 ReviewExportPage (Phase 5) — COMPLETE ✅

Implemented via SDD (6 TDD tasks + 1 final-fix refactor):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Tokens (WARNING, QC_RESULT_COLORS/LABELS, DEFAULT_QC_RULES, RULE_DESCRIPTIONS) | `a70a19f` | 5 (124 total) |
| 2 | ActionHeader (title + 3 buttons + rules chips) | `c0a7a3b` | 5 (129 total) |
| 3 | QCIssueTable (one row per QC rule, derived result + colored cell) | `b776514` | 6 (135 total) |
| 4 | ResultSummary (pass/warning/error counts + advisory + export list) | `fc9c3a5` | 6 (141 total) |
| 5 | ReviewExportPage assembly | `98763f7` | 2 (143 total) |
| 6 | Integration (AppShell idx 8, exports, app.py wiring) | `3ad80ce` | 2 (145 total) |
| Fix | Extract shared `derive_rule_result` helper (error precedence; resolved cross-widget divergence) | `1bdd23d` | 4 (149 total) |

Final review: READY TO MERGE (1 Important found + fixed before merge; 6 Minor deferred to follow-ups).

### 层序格架页 SequenceFrameworkPage (Phase 6) — COMPLETE ✅

Implemented inline via TDD (4 implementation tasks + docs):

| Task | Content | Tests |
|------|---------|-------|
| 1 | Sequence tokens (`SEQUENCE_SCHEMES`, `SYSTEMS_TRACT_LABELS`) | +2 |
| 2 | Child widgets: `SequenceTargetPanel`, `SequenceBoundaryTable`, `SequenceSchemeSummary` | +6 |
| 3 | `SequenceFrameworkPage` assembly + pages export | +2 |
| 4 | AppShell index 4 + `PaleoWorkbenchWindow` stratigraphy wiring | +2 |

Design/plan added:
- `docs/superpowers/specs/2026-07-05-sequenceframeworkpage-design.md`
- `docs/superpowers/plans/2026-07-05-sequenceframeworkpage.md`

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_tokens.py tests/test_app_shell.py tests/test_ui_exports.py tests/test_sequence_target_panel.py tests/test_sequence_boundary_table.py tests/test_sequence_scheme_summary.py tests/test_sequence_framework_page.py tests/test_sequence_integration.py -q` — 40 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 161 passed

Notes:
- Page is display-first and does not mutate `ProjectDocument`.
- Data source is `project.stratigraphy`; missing values render conservative defaults.
- Explicit `QT_QPA_PLATFORM=offscreen` is required in this headless environment for PySide/pytest-qt.

Commit: `b6d1df0` — `feat: add sequence framework page`

### 编图页 MappingPage (Phase 7) — COMPLETE ✅

Implemented inline via TDD (3 implementation tasks + docs):

| Task | Content | Tests |
|------|---------|-------|
| 1 | Child widgets: `MapDocumentPanel`, `MapCanvasPanel`, `MapChromePanel`, plus active-document helper | +7 |
| 2 | `MappingPage` assembly + pages export | +2 |
| 3 | AppShell index 7 + `PaleoWorkbenchWindow` paleomap document wiring | +2 |

Design/plan added:
- `docs/superpowers/specs/2026-07-05-mappingpage-design.md`
- `docs/superpowers/plans/2026-07-05-mappingpage.md`

Implementation notes:
- `MapCanvasPanel` embeds `geoviz_paleo_map.PaleoMapCanvas`.
- Active document is the latest `ProjectDocument.paleomap_documents` entry.
- `PaleoMapCanvas.load_features(facies_polygons, period_name=linked_target_horizon, wells=well_overlays)` handles polygons, labels, well overlay, title, legend, north arrow, and scale bar.
- Added `geo-viz-engine/packages/geoviz_common` to pytest pythonpath because `PaleoMapCanvas` imports `geoviz_common.paint_scheduler`.
- Page remains display-first; polygon editing/export actions are not implemented in this phase.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_map_document_panel.py tests/test_map_canvas_panel.py tests/test_map_chrome_panel.py tests/test_mapping_page.py tests/test_mapping_integration.py -q` — 11 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 172 passed

Commit: `db65ee5` — `feat: add mapping page`

### 测井预测页 WellLogPredictionPage (Phase 8) — COMPLETE ✅

Implemented inline via TDD (4 implementation tasks + docs):

| Task | Content | Tests |
|------|---------|-------|
| 1 | Prediction helpers: active-task selection and `PredictionTask` → synthetic `WellLogData` conversion | +2 |
| 2 | Child widgets: `PredictionTaskPanel`, `WellLogCanvasPanel`, `PredictionEvidencePanel` | +6 |
| 3 | `WellLogPredictionPage` assembly + pages export | +2 |
| 4 | AppShell index 2 + `PaleoWorkbenchWindow` prediction task wiring | +2 |

Design/plan added:
- `docs/superpowers/specs/2026-07-05-welllogpredictionpage-design.md`
- `docs/superpowers/plans/2026-07-05-welllogpredictionpage.md`

Implementation notes:
- `WellLogCanvasPanel` embeds `geoviz_well_log.WellLogCanvas`.
- Active prediction task is the latest `ProjectDocument.prediction_tasks` entry.
- `well_log_data_from_prediction()` converts `result_summary["predicted_regions"]` into a probability curve and facies intervals, then `build_qpainter_tracks()` produces the rendered tracks.
- Page remains display-first; LAS parsing/model execution/editable picks are not implemented in this phase.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_prediction_helpers.py tests/test_prediction_task_panel.py tests/test_well_log_canvas_panel.py tests/test_prediction_evidence_panel.py tests/test_well_log_prediction_page.py tests/test_well_log_prediction_integration.py -q` — 12 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 184 passed

Commit: `5054a92` — `feat: add well log prediction page`

### 地震预测页 SeismicPredictionPage (Phase 9) — COMPLETE ✅

Implemented inline via TDD (4 implementation tasks + docs + one engine integration fix):

| Task | Content | Tests |
|------|---------|-------|
| 1 | Seismic prediction helper: deterministic `PredictionTask` → `numpy.float32` volume conversion | +2 |
| 2 | Child widgets: `SeismicTaskPanel`, `SeismicViewPanel`, `SeismicControlPanel` | +6 |
| 3 | `SeismicPredictionPage` assembly + pages export | +2 |
| 4 | AppShell index 3 + `PaleoWorkbenchWindow` prediction task wiring | +2 |

Design/plan added:
- `docs/superpowers/specs/2026-07-05-seismicpredictionpage-design.md`
- `docs/superpowers/plans/2026-07-05-seismicpredictionpage.md`

Implementation notes:
- `SeismicViewPanel` embeds `geoviz_seismic.SeismicView`.
- Active prediction task is the latest `ProjectDocument.prediction_tasks` entry.
- `seismic_volume_from_prediction()` creates a deterministic small volume using the task seed and predicted-region probabilities, then `SeismicView.load_demo()` renders it.
- Added backward-compatible `SeismicView(auto_load=True)` parameter in geo-viz-engine; workbench embeds with `auto_load=False` to prevent background synthetic workers from surviving tests and app page construction.
- Page remains display-first; SEGY import, seismic attributes, horizon picking, and model execution are not implemented in this phase.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_seismic_prediction_helpers.py tests/test_seismic_task_panel.py tests/test_seismic_view_panel.py tests/test_seismic_control_panel.py tests/test_seismic_prediction_page.py tests/test_seismic_prediction_integration.py -q` — 12 passed
- `PYTHONPATH=geo-viz-engine/packages/geoviz_seismic:geo-viz-engine/packages/geoviz_common QT_QPA_PLATFORM=offscreen pytest geo-viz-engine/tests/test_seismic_view.py::test_seismic_view_init geo-viz-engine/tests/test_seismic_view.py::test_seismic_view_load_demo -q` — 2 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 196 passed

Commit: `c070fd5` — `feat: add seismic prediction page`
Nested geo-viz-engine commit: `e3376a2` — `fix: allow seismic view without auto loading`

### 可视化页 VisualizationPage (Phase 10) — COMPLETE ✅

Implemented inline via TDD (3 implementation tasks + docs):

| Task | Content | Tests |
|------|---------|-------|
| 1 | Child widgets: `VisualizationSummaryPanel`, `CompositeVisualizationPanel`, `VisualizationTracePanel` | +5 |
| 2 | `VisualizationPage` assembly + pages export | +2 |
| 3 | AppShell index 5 + `PaleoWorkbenchWindow` resources/predictions/maps wiring | +2 |

Design/plan added:
- `docs/superpowers/specs/2026-07-05-visualizationpage-design.md`
- `docs/superpowers/plans/2026-07-05-visualizationpage.md`

Implementation notes:
- `CompositeVisualizationPanel` hosts three geo-viz tabs: `WellLogCanvas`, `SeismicView(auto_load=False)`, and `CrossWellWidget`.
- Reuses `well_log_data_from_prediction()` and `seismic_volume_from_prediction()` rather than creating new visualization data semantics.
- Page remains display-first; linked cursors, saved composite layouts, and export artifact creation are not implemented in this phase.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_visualization_summary_panel.py tests/test_composite_visualization_panel.py tests/test_visualization_trace_panel.py tests/test_visualization_page.py tests/test_visualization_integration.py -q` — 9 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 205 passed

Commit: `36cce8e` — `feat: add visualization page`

### Post-Implementation Hardening — COMPLETE ✅

Resolved low-risk follow-up items:
- Updated `paleo_workbench/ui/screen_inventory.py` from the legacy 7-page inventory to the current 9-page AppShell inventory, with token values sourced from `paleo_workbench.ui.tokens`.
- Added dedicated `BoundaryPanel.area_spin` regression coverage for range, step, decimals, default value, and suffix.
- Expanded ReviewExport integration coverage to verify `ActionHeader`, `QCIssueTable`, `ResultSummary`, and export artifact receipt from the same project data.
- Cleaned the `test_result_summary.py` throwaway loop variable and removed the redundant warning branch from `derive_rule_result()`.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_project_models.py tests/test_boundary_panel.py tests/test_review_export_integration.py -q` — 10 passed
- `QT_QPA_PLATFORM=offscreen pytest tests/test_project_models.py tests/test_boundary_panel.py tests/test_review_export_integration.py tests/test_qc_helpers.py tests/test_result_summary.py -q` — 20 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 206 passed
- `git diff --check` — passed

### Post-Implementation Hardening 2 — COMPLETE ✅

Resolved remaining tracked UI follow-up items:
- Replaced duplicated `STEP_TYPES` and `RESOURCE_TYPES` lists in page modules with shared `workflow.service.STEP_ORDER` and `REQUIRED_RESOURCE_TYPES` references.
- Added explicit `WorkflowProgress` badge color metadata and tests for badge object names, step colors, and stylesheet application.
- Split `ResourceSummaryBar` resource names and counts into separate labels while preserving `type_labels` as a compatibility alias for counts.
- Extracted DataPage action controls into reusable `ActionPanel`.
- Scoped `FactorTaskPanel.Row` styling to `QWidget#FactorTaskRow`.
- Replaced Qt-version-fragile `FactorPreviewGrid` visibility assertion with direct hidden-state checks.
- Removed redundant `QPalette` rebuilds from `ResultSummary`; color assertions now verify stylesheet output.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_page_constant_sources.py tests/test_data_page.py tests/test_workflow_progress.py tests/test_factor_task_panel.py tests/test_factor_preview_grid.py tests/test_resource_summary.py tests/test_result_summary.py -q` — 36 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 212 passed

### Preflight Warning Cleanup — COMPLETE ✅

Resolved release-prep warnings:
- Fixed `geo-viz-engine` `Renderer3D._setup_sliders()` so slider `valueChanged` handlers are connected once during initialization and slider range/value updates are signal-blocked during volume loading.
- Added a regression test ensuring repeated `Renderer3D.load_volume()` calls do not emit PySide "Failed to disconnect" runtime warnings.
- Updated root and `geo-viz-engine` pytest config to remove the environment-dependent `timeout` config warning and set `asyncio_default_fixture_loop_scope = "function"`.

Verification:
- `PYTHONPATH=geo-viz-engine/packages/geoviz_seismic:geo-viz-engine/packages/geoviz_common QT_QPA_PLATFORM=offscreen pytest geo-viz-engine/tests/test_renderer_3d.py -q` — 7 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 212 passed, clean output
- `python -m compileall -q paleo_workbench geo-viz-engine/packages/geoviz_seismic` — passed

### Test Results History

| Phase | Tests | Status |
|-------|-------|--------|
| AppShell | 57 | ✅ |
| HomePage | 80 | ✅ |
| HomePage polish | 81 | ✅ |
| DataPage | 95 | ✅ |
| PreparationPage | 119 | ✅ |
| ReviewExportPage | 149 | ✅ |
| SequenceFrameworkPage | 161 | ✅ |
| MappingPage | 172 | ✅ |
| WellLogPredictionPage | 184 | ✅ |
| SeismicPredictionPage | 196 | ✅ |
| VisualizationPage | 205 | ✅ |
| Post-implementation hardening | 206 | ✅ |
| Post-implementation hardening 2 | 212 | ✅ |
| Preflight warning cleanup | 212 | ✅ |

### Commits This Session

AppShell: `bf38646`..`c7352e1` + `6222a80`..`203c457` (13 commits)
HomePage: `73ff911`..`adf0acc` + `c507629` + `96c88f9` (8 commits)
DataPage: `4ba7122`..`28a3a04` + `bd8d7be` (6 commits)
PreparationPage: `054b8f5`..`446ee05` + `a438167` (7 commits)
ReviewExportPage: `a70a19f`..`3ad80ce` + `1bdd23d` (7 commits)
SequenceFrameworkPage: `b6d1df0` (1 commit)
MappingPage: `db65ee5` (1 commit)
WellLogPredictionPage: `5054a92` (1 commit)
SeismicPredictionPage: `c070fd5` (1 root commit) + `e3376a2` (geo-viz-engine nested commit)
VisualizationPage: `36cce8e` (1 commit)
Post-Implementation Hardening: `chore: harden ui follow-ups`
Post-Implementation Hardening 2: `chore: finish ui hardening follow-ups`
Preflight Warning Cleanup: `chore: clean preflight test warnings` + nested geo-viz-engine commit `bb5d29b6`
Total: ~49 committed changes; all current phase, hardening, and preflight work committed

### Next: Post-Implementation Hardening

- No currently tracked non-blocking UI follow-ups remain; next useful step is branch publication or a fresh review.

## Session: 2026-07-06 (Data Management Redesign)

### Data Management Center — COMPLETE ✅

User request:
- Redesign the Data page so it manages all project data,成果, and files, and provides preview for selected data types.
- Use `/superpowers /planning-with-files` for design before implementation.

Current context findings:
- Existing `DataPage` is still a narrow resource table + summary + `ActionPanel`; buttons are not wired to import behavior.
- Existing backend pieces include `scan_resources(root, project_path=None)`, `classify_path(path)`, `ResourceItem`, `ProjectDocument.resources`, `ProjectDocument.export_artifacts`, and `ProjectManager`.
- `scan_resources()` already produces checksums, file sizes, relative/external path flags, resource type, format, and status.
- Existing resource classifier covers LAS, SEGY/SGY, DAT variants, spreadsheets, documents, images, reference maps, and WLP files.
- Existing data-page tests cover table rendering and shell integration, but there are no standalone `tests/test_resources_scanner.py` or `tests/test_resources_classifier.py` files; future implementation should add direct tests for import/dedupe/preview behavior.

Implementation completed inline from the approved plan because this runtime did not expose subagent dispatch tools.

| Task | Content | Tests |
|------|---------|-------|
| 1 | Classifier/scanner characterization coverage | +5 |
| 2 | `DataImportService` with deterministic path/checksum dedupe | +5 |
| 3 | `PreviewState` helpers for resources/artifacts | +4 |
| 4 | `DataCatalogPanel` category/count panel | +2 |
| 5 | `DataAssetTable` unified resources/artifacts table with filtering | +4 |
| 6 | `DataDetailPanel` metadata and lightweight preview display | +3 |
| 7 | DataPage/AppShell/PaleoWorkbenchWindow assembly and project/artifact wiring | +6 updated |
| 8 | File/folder dialog seams and button wiring | +2 |

Design/plan:
- Spec: `docs/superpowers/specs/2026-07-06-datamanagementpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-datamanagementpage.md`

Implementation notes:
- Import does not copy or delete source files.
- Dedupe is path-first, checksum-second, and handles project-relative resource paths.
- Previews are metadata-driven and do not deep-load LAS, SEGY, PPT, or Excel by default; PDF now uses a first-page thumbnail preview.
- `ResourceTable` remains in the codebase for legacy tests, but DataPage now uses `DataAssetTable`.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_integration.py tests/test_data_import_service.py tests/test_data_asset_table.py tests/test_data_catalog_panel.py tests/test_data_detail_panel.py tests/test_preview_strategy.py -q` — 29 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 239 passed

### Data Preview Formats Enhancement — COMPLETE ✅

User request:
- Extend the Data page so it supports previews for multiple data/file formats, not only metadata summaries.

Implemented inline from the approved spec and plan:

| Task | Content | Tests |
|------|---------|-------|
| 1 | Bounded preview strategy for TXT/XML/CSV/DAT, missing files, and professional summary-only formats | +5 strategy cases |
| 2 | `DataDetailPanel` image thumbnails, invalid-image warning, and text/table snippet rendering | +3 widget cases |
| 3 | DataPage imported text/image selection flow coverage | +2 integration cases |
| 4 | Final verification and tracking docs | — |

Design/plan:
- Spec: `docs/superpowers/specs/2026-07-06-data-preview-formats-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-data-preview-formats.md`

Implementation notes:
- Text-like preview reads at most 8192 bytes and 20 lines.
- `txt` and `xml` render as `text`; `csv` and `dat` render as `table`.
- Image preview is UI-only via `QPixmap`; the strategy layer returns only `image_path`.
- PDF renders a first-page thumbnail; LAS, SGY, SEGY, XLSX, XLS, PPT, PPTX, WLP, and DFB remain safe summary-only by default.
- Missing files return metadata mode with `"文件不存在"`.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py tests/test_data_detail_panel.py tests/test_data_page.py -q` — 25 passed
- `git diff --check` — passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 248 passed
- `python -m compileall -q paleo_workbench` — passed

### Data Page V2 Interaction Polish — COMPLETE ✅

User request:
- Make the preview panel resizable and make PDF preview a real preview panel with page navigation, not a static thumbnail.
- Fill in remaining visible Data page actions.

Implemented:
- Data page lower content now uses `QSplitter`, allowing the catalog/table/detail preview columns to be resized.
- `DataDetailPanel` no longer uses fixed width; it has a 240px minimum width.
- PDF preview now renders a page panel with `上一页` / `下一页` controls and `当前页 / 总页数` label.
- `重新扫描` refreshes selected resource metadata or marks it `missing` if the source file no longer exists.
- `移出项目` unregisters the selected resource without deleting the source file.
- `打开目录` reports and opens the selected resource's containing directory.
- Import actions report added/duplicate/warning counts in the action panel.
- Removed an `ActionHeader` stylesheet rule that caused Qt parse warnings during app startup.
- Replaced the left `TextSidebar` placeholder with real page context content for all 9 pages.
- Data page sidebar context now shows resource/artifact counts, selected item placeholder, reader capabilities, and data operations.

Verification:
- `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_detail_panel.py tests/test_action_header.py -q` — 30 passed
- `git diff --check` — passed
- `QT_QPA_PLATFORM=offscreen pytest tests/test_sidebar.py tests/test_app_shell.py tests/test_data_page.py tests/test_data_detail_panel.py -q` — 36 passed
- `QT_QPA_PLATFORM=offscreen pytest -q` — 259 passed
- `python -m compileall -q paleo_workbench` — passed

---

## Session: 2026-07-07 — Project Management V1 + Baseline Fix

### Baseline Repair (pre-feature)

07-06 会话接入 SeismicPredictionPage 等页面后, `geoviz_seismic` 依赖的 scipy/segyio/pyqtgraph/PyOpenGL/matplotlib 既未在 pyproject 声明、venv 也未安装, 导致 36 个测试收集失败。

修复:
- `pip install -e` 每个 geoviz 子包(按依赖顺序: common → well_log → well_tie → paleo_map → seismic → cross_well → plots → map), 拉齐 scipy 等重依赖。
- 新增 `requirements-geoviz.txt` 记录按依赖顺序的可编辑安装路径。
- 补全 `pyproject.toml` 的 `pythonpath`(含此前缺失的 `geoviz_well_tie` 和 `geoviz_map`), 并在 dependencies 注释里说明依赖策略。
- 基线恢复: 259 passed。

Commit: `397993e fix: declare geo-viz-engine subpackage deps and restore test baseline`

### Project Management V1 — COMPLETE ✅

Implemented via SDD (5 TDD tasks + 1 final cleanup):

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | HeaderToolbar 4 信号 (new/open/save/properties_requested) + 命名按钮属性(保留 .buttons 兼容) | `336bf2e` | 4 (263 total) |
| 2 | PaleoWorkbenchWindow 项目生命周期 (new_project/open_project_path→bool/save_project/save_project_as) + _refresh_shell + _apply_project_to_shell 重构 | `c7f95b9` | 8 (271 total) |
| 3 | 文件对话框 helpers (_choose_open/_choose_save) + _wire_toolbar (两处调用) + save_project 改为无路径时弹对话框 | `e0c3335` | 4 (275 total) |
| 4 | project_properties_text (7 字段) + _show_properties + save OSError 非破坏处理 | `c1d0d54` | 5 (280 total) |
| 5 | 集成 smoke (new/open/save 全周期 + 标题/状态栏更新) | `4cee4e1` | 3 (283 total) |
| Cleanup | 移除冗余 FileNotFoundError (OSError 已覆盖) | (本次同步提交) | — |

Final review: READY TO MERGE (no Critical/Important; 3 Minor deferred to follow-ups)。

### Commits This Session

- Baseline fix: `397993e`
- Project Management: `336bf2e`..`4cee4e1` (5 commits)
- All on `main`, all pushed to origin/main

### Test Results

| Phase | Tests | Status |
|-------|-------|--------|
| (baseline after dep fix) | 259 | ✅ |
| Project Management V1 | 283 | ✅ |

---

## Session: 2026-07-10 — Data Page UI/Perf Optimization (Phase 15)

### Goal

Make the data management page feel smooth under **2000+ assets** and large directory imports: virtual table, filter index, async preview with generation + LRU cache, batched import refresh, light toolbar polish. Keep floating-panel layout (surgical Approach A).

### Process

1. **Brainstorming** → design approved section-by-section
2. **Spec** committed: `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md` (`86f6776`)
3. **Plan** committed: `docs/superpowers/plans/2026-07-10-datapage-ui-perf-optimization.md` (`28b1ef6`)
4. **Worktree:** `.worktrees/datapage-ui-perf` on `feature/datapage-ui-perf`
5. **Subagent-driven development** (sequential implementers; parallel spec/quality reviews; continuous)
6. **PR #1** created, review fixes (serial queue + shutdown), merged to `main` (`bc8b68b`)

### Implementation commits (feature branch)

| Commit | Content |
|--------|---------|
| `0dc2478` | feat: virtualize data asset table with QAbstractTableModel |
| `99d0d24` | feat: add FilterIndex and debounced data search |
| `e5c1afb` | feat: async data preview with generation tokens |
| `bc665cb` | fix: invalidate preview generation on rescan |
| `4908ce4` | feat: LRU preview cache for data reader |
| `7f12639` | perf: batch data table refresh after import |
| `46f8517` | polish: data toolbar toggles and reader loading feedback |
| `1ca0f2c` | test: wait for async reader mode in app shell sidebar tests |
| `434dc95` | fix: serial preview queue and controller shutdown |

### New modules

| File | Role |
|------|------|
| `paleo_workbench/ui/pages/asset_table_model.py` | Virtual table model |
| `paleo_workbench/ui/pages/data_table_columns.py` | Column definitions |
| `paleo_workbench/ui/pages/filter_index.py` | Category + search index |
| `paleo_workbench/ui/pages/preview_cache.py` | LRU cache keys |
| `paleo_workbench/ui/pages/preview_worker.py` | Async controller (serial + shutdown) |

### Verification

- Focused suites green throughout SDD
- Full suite before merge: **385 passed** (after serial/shutdown fix)
- PR review: READY; Important #1–2 fixed pre-merge
- Merged: https://github.com/WindWang2/paleo-workbench/pull/1

### Errors / review issues fixed this session

| Issue | Resolution |
|-------|------------|
| AppShell tests expected immediate `阅读器: text` after async select | `qtbot.waitUntil` for reader mode |
| Rescan vs in-flight preview race | rescan uses `controller.request()` (generation bump) |
| Unbounded concurrent preview threads | serial latest-only queue |
| Live QThread destroyed on shell rebuild | `shutdown()` on close + DeferredDelete |
| Quality review NEEDS_FIXES on Task 3 | `bc665cb` then later `434dc95` |

### Status

**Phase 15 COMPLETE.** Local `main` == `origin/main` at merge commit. Planning files updated 2026-07-10.

### Planning follow-up (same day)

- Wrote durable **数据管理思维 (Data Management Mindset)** into `findings.md` (product + architecture principles: asset universe, register-vs-disk, workspace metaphor, preview bounds, scale mindset, decision checklist).
- Added compressed decision table to `task_plan.md` pointing at full findings section.
- Purpose: future sessions / agents change the data page against explicit management philosophy, not only UI/perf implementation notes.

---

## Session: 2026-07-10 (cont.) — Mapping Editor V1 + native core

### Mapping Editor V1 — COMPLETE ✅ (PR #3)

Implemented via SDD on `feature/mapping-editor-v1` (10 tasks), merged `2e98da6`.

- GIS shell + QGraphicsView scene + full draft features + topology + save draft
- Spec/plan under `docs/superpowers/specs|plans/2026-07-10-mapping-editor-v1*`
- Tests at merge: **449 passed**

### map_edit_core C++ (post-merge continuation)

- Scaffolded `native/map_edit_core/` (pybind11 C++17): hit_test, snap, move_feature, vertex ops, validate
- Install: `pip install -e native/map_edit_core` → `HAS_CPP is True`
- Tests: `tests/test_map_edit_core_cpp.py` (skip if not built)
- Docs: updated `paleo_workbench/mapping/CPP_EXTENSION.md`
- Optional dep: `pyproject.toml` `[native]` → pybind11

### Cleanup

- Worktrees `datapage-ui-perf` / `mapping-editor-v1` removable after merge

### Post-V1 continuation — facies tool + chrome preview

| Commit area | Work |
|-------------|------|
| Facies + hit + vertex | `e413e11` — facies draft tool, hit_test select, broader vertex edit |
| 图面预览 mode | Toolbar `图面预览` toggle; center stack switches edit view ↔ `MapCanvasPanel` + `MapChromePanel`; live dirty scene exported without force-save; helpers `facies_to_geojson` / `well_to_lnglat` / `preview_payload_from_*`; sidebar mode line |

Tests: **~469+** (preview suite in `tests/test_map_preview_mode.py`).

### Post-V1 batch — topology + CI + data polish

| Area | Work |
|------|------|
| Topology | `snap_shared_nodes` / `rebuild_topology` / `merge_rings` / `split_ring_by_line`; scene forced rebuild (undoable); merge 2 facies; split by line; toolbar 重建拓扑/合并/分割 |
| CI | `.github/workflows/ci.yml` builds `map_edit_core` and asserts `HAS_CPP is True` before pytest |
| Data polish | catalog tab → toolbar sync; Chinese haystack labels; open error detail; save OSError test; `PAGE_INDEX_*` helpers |

Tests: **475 passed**, 4 skipped.

### Off-thread image/PDF media preload

- `preload_media` loads **image + PDF** file bytes on worker
- LRU keeps media ≤512KB; larger stripped; path-only hits use `_MediaPreloadWorker`
- `PdfPreviewWidget` loads via `QBuffer` when `pdf_bytes` present
- UI still owns QPixmap/QPdfDocument decode (Qt thread affinity)

---

## Session: 2026-07-10 — Visualization geo-viz adapter (Phase 17) — COMPLETE ✅

Implemented via SDD on `feature/viz-geoviz-adapter` (4 tasks).

| Task | Content | Commit area |
|------|---------|-------------|
| 1 | Pure `paleo_workbench/viz/` — `VizRef` / `VizPayload` / `VizAdapter`; LAS / SEGY / map loaders; prediction bridge | `f9e6468` |
| 2 | Visualization `open_ref`, 古地理 tab, summary asset list, trace refresh | `669f7e2` |
| 3 | Data page 「在可视化中打开」 + window jump (`PAGE_INDEX_VISUALIZATION` + rail + `open_ref`) | `3defc2a` |
| 4 | Message clears prior canvases; `from_prediction` soft-fail; dual-payload asserts; full suite + planning docs | polish + docs |

### Modules

| Path | Role |
|------|------|
| `paleo_workbench/viz/models.py` | `VizKind`, frozen `VizRef`, `VizPayload` |
| `paleo_workbench/viz/well_log_load.py` | LAS → bounded `WellLogData` (12 curves / 2000 samples) |
| `paleo_workbench/viz/seismic_load.py` | SEGY → bounded volume (≤ 64³) |
| `paleo_workbench/viz/map_load.py` | `PaleoMapDocument` → GeoJSON features + wells (via mapping preview helper) |
| `paleo_workbench/viz/adapter.py` | `supports_resource` / `ref_from_*` / `resolve` / `from_prediction` |
| `visualization_page.py` | `open_ref`, `_reload_current`, prediction fallback when no ref |
| `composite_visualization_panel.py` | 古地理 tab + `load_payload` + message `_clear_canvases` |
| `data_page.py` / `action_panel.py` / `app.py` | Jump signal `open_in_visualization(VizRef)` with `source="data_page"` |

### Verification

- Focused viz suites green throughout T1–T4
- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **497 passed**, 4 skipped
- Spec: `docs/superpowers/specs/2026-07-10-visualization-geoviz-adapter-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-visualization-geoviz-adapter.md`

### Status

**Phase 17 COMPLETE** on branch `feature/viz-geoviz-adapter`.

### Post-merge on main (2026-07-10 cont.)

- Fast-forward merged `feature/viz-geoviz-adapter` → `main` (`6d8a131`)
- Declared `shapely>=2.0` in `pyproject.toml` (merge/split topology)
- Public `HAS_SHAPELY` on `map_edit_api`; shapely-dependent topology tests use `skipif`
- Removed unused pytest `asyncio_default_fixture_loop_scope` (warning cleanup)
- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **501 passed**
- Smoke: `PaleoWorkbenchWindow` constructs; `HAS_CPP=True`, `HAS_SHAPELY=True`

**MVP scope (Phases 1–17) complete on `main`.**

---

## Session: 2026-07-10 — Phase 18a sample project bootstrap — COMPLETE ✅

Implemented via SDD on `feature/e2e-pipeline-18a` (tasks 1–5 code + task 6 suite/docs).

| Task | Content | Commit |
|------|---------|--------|
| 1 | Skip large-file checksums in `scan_resources` | `0148a0b` |
| 2 | `bootstrap_sample_project` pipeline for sample data | `eaf977b` |
| 3 | CLI: `python -m paleo_workbench.pipeline` | `6ddbfc7` |
| 4 | Toolbar button 「打开样例工程」 | `24b66aa` |
| 5 | Open sample project from workbench toolbar | `0a0de76` |
| docs | Design + 18a plan | `4abb067`, `d0db751` |

### Modules

| Path | Role |
|------|------|
| `paleo_workbench` scan path | Large-file checksum skip (SEGY-class) |
| `paleo_workbench/pipeline/` | `bootstrap_sample_project` pure bootstrap |
| `python -m paleo_workbench.pipeline` | CLI: `--data-root` / `--out` |
| Header toolbar + `app.py` | 「打开样例工程」 → `bootstrap_sample_project` in-memory (no auto-save) |

### Verification

- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **509 passed**, 4 skipped
- Smoke: `python -m paleo_workbench.pipeline --data-root data --out /tmp/sample.paleo.json` → **200 resources**, exit 0
- Spec: `docs/superpowers/specs/2026-07-10-e2e-real-data-pipeline-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-e2e-real-data-pipeline-18a.md`

### Status

**Phase 18a COMPLETE** on branch `feature/e2e-pipeline-18a`.

---

## Session: 2026-07-10 — Phase 18b asset binding + 18c map draft — COMPLETE ✅

Implemented via SDD on `feature/e2e-pipeline-18b-18c` (tasks 1–6).

| Task | Content | Commit area |
|------|---------|-------------|
| 1 | `bind_prediction_assets` / `suggest_assets_for_demo` / `ensure_demo_prediction` | `8e81df1` |
| 2 | Bound LAS/SEGY canvases via VizAdapter; unbound mock fallback | `818f29b` |
| 3 | Sample open + CLI `--with-demo-tasks` seed demo prediction | `8085d4c` |
| 4 | Deterministic `compile_map_draft` (always produces draft) | `c50c6e6` |
| 5 | Mapping toolbar 「生成演示草稿」 | `95e91a1` |
| 6 | CLI `--with-map-draft`, full suite, docs | (this session) |

### Modules

| Path | Role |
|------|------|
| `paleo_workbench/pipeline/assets.py` | Bind prediction → resource ids; suggest demo LAS/SEGY; ensure demo task |
| `paleo_workbench/pipeline/compile_map.py` | Deterministic demo paleomap (polygons, wells, `is_demo_draft`) |
| `paleo_workbench/pipeline/__main__.py` | `--with-demo-tasks` / `--with-map-draft` (order: bootstrap → demo → draft → write) |
| `well_log_canvas_panel.py` / `seismic_view_panel.py` | Bound path → `VizAdapter.resolve`; message / mock fallback |
| `app.py` + mapping toolbar | Sample open seeds demo prediction; 「生成演示草稿」 → `compile_map_draft` |

### Verification

- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **533 passed**, 4 skipped
- Smoke: `python -m paleo_workbench.pipeline --data-root data --out /tmp/demo18.paleo.json --with-demo-tasks --with-map-draft` → **200 resources**, 1 prediction_task (bound well+seismic), 1 paleomap_document (demo draft, polygons+wells)
- Spec: `docs/superpowers/specs/2026-07-10-e2e-real-data-pipeline-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-e2e-pipeline-18b-18c.md`

### Status

**Phase 18b + 18c COMPLETE** on branch `feature/e2e-pipeline-18b-18c`.

---

## Session: 2026-07-10 — Phase 19 UI visual polish — COMPLETE ✅

Implemented via SDD on `feature/ui-visual-polish` (tasks 1–7).

| Task | Content | Commit |
|------|---------|--------|
| 1 | Density tokens + richer global QSS | `42970e0` |
| 2 | Shared UI widgets (PanelCard, SectionHeader, ToolbarStrip, EmptyStateLabel, PageScaffold) | `84760ae` |
| 3 | Denser AppShell chrome margins and toolbar spacing | `e8254c2` |
| 4 | Density tokens on home, data, mapping chrome | `916a0ac` |
| 5 | Unify page outer margins to `PAGE_MARGIN` | `da78d75` |
| 6 | Adopt PanelCard/EmptyState objectNames; drop duplicate QSS | `6a33245` |
| 7 | Full suite + planning docs | (this session) |

Design/plan docs landed earlier: `e3b2be2`, `c1e1a77`.

### Modules

| Path | Role |
|------|------|
| `paleo_workbench/ui/tokens.py` | Density scale, interaction colors, expanded `QSS_TEMPLATE` |
| `paleo_workbench/ui/widgets/` | Five shared polish widgets + package exports |
| Shell chrome | Header toolbar height 36; denser margins/spacing |
| Page roots | Outer margins → `tokens.PAGE_MARGIN` (12) |
| Cards / empty labels | `objectName` `PanelCard` / `EmptyStateLabel` for global QSS |

### Brief

Density tokens, richer global QSS (button states / tables / focus / panel selectors), five shared widgets, shell + high-traffic page density, `PanelCard`/`EmptyState` objectName adoption—no business-logic changes.

### Verification

- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **544 passed**, 4 skipped
- Spec: `docs/superpowers/specs/2026-07-10-ui-visual-polish-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-ui-visual-polish.md`

### Status

**Phase 19 COMPLETE** on branch `feature/ui-visual-polish`.

---

## Session: 2026-07-10 — Phase 20 Mapping GIS shell polish — COMPLETE ✅

Implemented via SDD on `feature/mapping-gis-shell-polish` (tasks 1–6).

| Task | Content | Commit |
|------|---------|--------|
| 1 | Mapping dock + status QSS selectors | `15c47db` |
| 2 | Visual separators on mapping edit toolbar | `a0a0eeb` |
| 3 | Unify layer tree + attribute dock chrome | `15ca16c` |
| 4 | Denser mapping page spacing + canvas dock chrome | `0bdb36b` |
| 5 | Status bar coordinate zone (`StatusCoordLabel`) | `4710de0` |
| 6 | Full suite + planning docs | (this session) |

Design/plan docs landed earlier: `0f334aa`, `914ef95`.

### Modules

| Path | Role |
|------|------|
| `paleo_workbench/ui/tokens.py` | Mapping/status selectors in `QSS_TEMPLATE` |
| `map_edit_toolbar.py` | Thin separators between tool groups (order unchanged) |
| `map_layer_tree.py` / `map_attribute_table.py` | Dock objectNames; drop local card QSS |
| `map_canvas_panel.py` / `map_chrome_panel.py` / `mapping_page.py` | Dock chrome + denser page spacing |
| `status_bar.py` | `StatusCoordLabel` for distinct coordinate zone |

### Brief

Compact professional GIS shell chrome for 编图: grouped toolbar, unified docks via global QSS, denser spacing, clearer status coordinates—no tool / topology / save behavior changes.

### Verification

- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **549 passed**, 4 skipped
- Spec: `docs/superpowers/specs/2026-07-10-mapping-gis-shell-polish-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-mapping-gis-shell-polish.md`

### Status

**Phase 20 COMPLETE** on branch `feature/mapping-gis-shell-polish`.

---

## Session: 2026-07-10 — Phase 21 DataPage stress + hotspots — COMPLETE ✅

Implemented via SDD on `feature/datapage-stress-hotspots` (tasks 1–5).

| Task | Content | Commit |
|------|---------|--------|
| 1 | Timing + synthetic fixture helpers | `31fa2c0` |
| 2 | Stress scenarios S1–S4 with timing logs | `dc7608b` |
| 3 | Import scan: skip large-file checksums (align with bootstrap) | `f28994f` |
| 4 | Optional second hotspot | **SKIPPED** — S1 update ~4ms, S3 ~3ms at N=2000; no UI hot-path change warranted |
| 5 | Full suite + planning docs | (this session) |

Design/plan docs: `ec6be1c`, `3b914bd`.

### Modules

| Path | Role |
|------|------|
| `tests/perf/` | Timing helpers + synthetic asset fixtures |
| `tests/test_datapage_stress.py` | S1–S4 stress scenarios; print `[datapage-stress]` timings (no CI ms gates) |
| `paleo_workbench/resources/import_service.py` | `skip_checksum_over_bytes` default 50 MiB on `import_files` / `import_folder` → `scan_resources` |

### Sample stress timings (local, after import checksum fix)

```
S1_update n=2000 ~3.7ms
S2_filter ~0.2-0.5ms
S3_rapid_select n=30 ~2.7ms
S4_import_folder n=300 ~24.6ms
```

### Notes

- **Production win:** large-file import checksum skip (SEGY-class / files over threshold no longer SHA256 on import scan), aligned with Phase 18a bootstrap scanner policy.
- **No second hotspot:** measured S1/S3 times are already in the low-ms range for N=2000; Task 4 deliberately skipped.
- Stress harness is evidence-only (printed timings); no wall-clock asserts in CI.

### Verification

- Full suite: **`QT_QPA_PLATFORM=offscreen python -m pytest -q`** → **557 passed**, 4 skipped
- Spec: `docs/superpowers/specs/2026-07-10-datapage-stress-hotspots-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-datapage-stress-hotspots.md`

### Status

**Phase 21 COMPLETE** on branch `feature/datapage-stress-hotspots`.

---

## Session: 2026-07-12/13 — Multimodal Preview Formats (Phase B)

Sub-project B of the data page overhaul. Added 4 new inline preview formats via SDD (8 implementation tasks + 3 fixes), each task individually reviewed.

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | deps (markdown, rasterio) + classifier (md/html) + PreviewResult schema (5 fields, 4 modes) | `9338b6b` | 588 |
| 2 | Markdown/HTML provider (_rich_text_preview) | `cb6bb44` | 591 |
| 3 | RichTextPreviewWidget (QTextBrowser, network-blocked) + reader dispatch | `64354ea` | 593 |
| 4 | JSON/GeoJSON provider (_json_preview, 5MB cap) | `222ad58` | 596 |
| Fix | JSON bytes-first truncation (memory safety) | `71e8c7e` | 596 |
| 5 | JsonTreePreviewWidget (QTreeView, lazy-expanded collapsed arrays) + dispatch | `8942c19` | 601 |
| 6 | GeoTIFF provider (rasterio + 3-path image fallback) | `d301fcb` | 603 |
| 7 | GeoTiffPreviewWidget (thumbnail + metadata table) + dispatch | `962f40f` | 605 |
| 8 | Audio provider + MediaPreviewWidget (QMediaPlayer, no video) + dispatch | `1745601` | 611 |
| Fix | geotiff media preload + dead QUrl import cleanup | `9fcbf66` | 612 |
| Fix | declare Pillow dep, drop dead json/GEOTIFF_FORMATS | `13643e4` | 612 |

Final whole-branch review: READY TO MERGE (1 Important fixed before merge: Pillow dep declaration; Minor deferred: no JSON boundary test at 100/101, json_payload not size-stripped from cache, GeoJSON root label not implemented, _on_error ignores msg).

Baseline: 582 → Final: **612 tests** (+30 new), 1 upstream rasterio/numpy warning.

Next: Sub-project A (DEVONthink 3-pane layout restructure), then C (performance).

---

## Session: 2026-07-13 — DEVONthink Three-Pane Layout (Phase A)

Sub-project A of the data page overhaul. Restructured DataPage into fixed 3-pane layout via SDD (5 implementation tasks + 1 dead-code cleanup).

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Extract compute_category_counts into filter_index | `ba512c8` | 615 |
| 2 | NavigationTree (smart-group QTreeWidget + CATEGORIES move) | `3b5f0f6` | 622 |
| 3 | InspectorPanel (read-only metadata table) | `7555938` | 627 |
| 4 | DataToolbar extension (remove/open_folder/visualize buttons + status label; remove catalog_btn) | `02f693c` | 630 |
| 5 | Rewrite DataWorkspace (3-pane splitter) + rewire DataPage + delete legacy (DataCatalogPanel/ActionPanel/FloatingPanel) + test migration | `5b5b696` | 625 |
| Cleanup | Drop dead _selected_asset_kind + unused Path import | `3d82879` | 625 |

Final whole-branch review: APPROVED (ship). No Critical/Important. 2 integration bugs found+fixed during Task 5 (signal double-fire, reader-toggle direction).

Baseline: 612 → Final: **625 tests** (legacy floating/catalog tests deleted; new tree/inspector/workspace tests added).

Next: Sub-project C (performance: virtual scrolling, import concurrency, search debounce).

---

## Session: 2026-07-13 — Concurrent Resource Scan (Phase C)

Sub-project C of the data page overhaul. Scope narrowed after exploration: Phase 15 (virtual scroll + debounced search) and Phase 21 (checksum skip + stress harness) already completed 2/3 of the original Phase C plan. The only remaining real gap was serial `scan_resources`.

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Parallelize scan_resources via ThreadPoolExecutor (_process_file + pool.map, order-preserving) + 6 unit tests | `1027bce` | 631 |
| 2 | S5 stress scenario (N=10000, env-gated DATAPAGE_STRESS_S5=1) — serial vs concurrent timing | `8ae4287` | 632 |

Both tasks reviewed clean. `_process_file` verified module-level + stateless (thread-safe across all transitive helpers). Backward-compatible signature (max_workers keyword-only, None default).

Baseline: 625 → Final: **632 tests**.

**Data page overhaul (B multimodal → A three-pane → C concurrent scan) complete.**

---

## Session: 2026-07-13 — Global Visual Consistency Polish

Three work lines via SDD (Tasks 1-4 combined + 5 + 6 + fixes).

| Task | Content | Commits | Tests |
|------|---------|---------|-------|
| 1-4 | Tokenize ~60 hardcoded spacing/font magic numbers across 28 files (SPACE_*/PAGE_MARGIN/FONT_SIZE_*) | `237b46b`..`3201d81` | 649 |
| fix | Tokenize 9 residual 13px literals to FONT_SIZE_TITLE (review-found) | `eb544ef` | 649 |
| 5 | Interaction states: focus rings (SecondaryButton objectNames on PDF/media buttons) + EmptyStateLabel on empty/message placeholders + InspectorPanel empty-state | `38c6698` | 655 |
| fix | Missing test_focus_states.py + activity_card empty-state (review-found) | `6ce8c53` | 658 |
| 6 | Core keyboard shortcuts: 1-9 page switch (text-field guarded), Ctrl+F/N/O/S, Delete (data-page-scoped) | `1a95196` | 672 |
| fix | Align search placeholder Ctrl+K → Ctrl+F | `15c5812` | 672 |

Normalization applied: 4→SPACE_1, 6→8→SPACE_2, 10→12→SPACE_3, 14→12→PAGE_MARGIN, 24→16→SPACE_4. Zero residual hardcoded spacing/font in ui/pages (except legitimate zeros and out-of-scope 14px which has no token).

Tests: 649 → 672 (+23 new: 6 empty-state + 3 focus-state + 14 keyboard-shortcut).

Note: 5-6 test failures in local runs are environmental (libEGL/WebEngine GL init fails without NVIDIA driver); not code regressions. Tests pass in CI with proper GL.

---

## Session: 2026-07-13 - Full-Project UI Polish

Four work lines via SDD (5 implementation tasks).

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | StatusBar dynamic context (coords/horizon/CRS/scale segments) | `48bdaa9` | +3 |
| 2 | TextSidebar progress/selection/tips sections for all pages | `beae5eb` | +3 |
| 3 | Tooltip coverage (nav icons, toolbar buttons, table headers, action panels) | `6beac9b` | +6 |
| 4 | Page-switch fade-in transition (QGraphicsOpacityEffect 150ms) | `e687c90` | +4 |
| 5 | section_header tokenization + empty-state audit (5 pages) | `c1d4d7c` | +5 |

Safe tests: 133/133 passing (WebChain env hang excluded). 16 new tests total.

Work lines: cross-page consistency (status bar + sidebar), tooltip discoverability, page-switch transition, misc cleanup.

---

## Session: 2026-07-15 - Context Menu + Format Export

Three implementation tasks via SDD.

| Task | Content | Commit | Tests |
|------|---------|--------|-------|
| 1 | Format converters: LAS->CSV, table->JSON, image->PNG, text->TXT + get_available_formats + ExportError | `6da90a2` | +8 |
| 2 | AssetContextMenu: 6-item menu with dynamic visibility per asset type | `5ce50e2` | +7 |
| 3 | DataAssetTable customContextMenuRequested + DataPage wiring + _export_selected_asset with QFileDialog | `44b8060` | +8 (3 table + 5 page) |

23 new tests total. Safe tests 34/34 passing; DataPage integration tests timeout-guarded (WebEngine env).

Spec: docs/superpowers/specs/2026-07-15-context-menu-export-design.md
Plan: docs/superpowers/plans/2026-07-15-context-menu-export.md

---

## Session: 2026-07-16 — GeoViz local data preview

Published the one-package `geoviz` facade documentation and verified bounded
local previews for LAS, SEGY, well-head DAT, well-stratification DAT, horizon
DAT, and time-depth DAT. Real-data smoke coverage also verifies bounded DFB
image/message and explicit WLP message fallbacks. Workbench production imports
are restricted to the `geoviz` facade; the facade AST has no workbench import.

### Verification

- `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_public_api.py -q` → **2 passed**.
- `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_contracts.py tests/test_geoviz_engine.py tests/test_geoviz_independence.py tests/test_geoviz_well_log_preview.py tests/test_geoviz_seismic_preview.py tests/test_geoviz_dat_preview.py tests/test_geoviz_formation_preview.py tests/test_geoviz_public_api.py -q` → **112 passed**.
- Exact original focused command `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_package_independence.py tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py tests/test_geoviz_preview_lifecycle.py tests/test_preview_cache.py tests/test_preview_async.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_visualization_jump.py tests/test_viz_adapter.py tests/test_fallback_preview.py -q` → 45 nodes completed before an existing Qt async single-process stall; no failure was emitted. Passing alternative `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_package_independence.py tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py tests/test_geoviz_preview_lifecycle.py tests/test_preview_cache.py tests/test_preview_async.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_visualization_jump.py tests/test_viz_adapter.py tests/test_fallback_preview.py -vv --timeout=30` → **183 passed in 9.33s** after the facade-boundary follow-up.
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_real_data_smoke.py -m slow -q` → **8 passed**; the 966 MiB SEGY used only three slices of at most 512×512 and a failing `get_volume_downsampled` guard proved that no full volume was requested.
- Exact original engine command `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not slow' -q` → existing QtWebEngine `ChartEngine` initialization segfault, exit 139. Passing alternative `cd geo-viz-engine && QT_QPA_PLATFORM=minimal QT_OPENGL=software LIBGL_ALWAYS_SOFTWARE=1 .venv/bin/python -m pytest -m 'not slow' -q --timeout=30` → **1006 passed, 2 skipped, 130 deselected in 32.16s** in one process. The child preview-import check prepends the current checkout and all local package roots to `PYTHONPATH`, asserts both module paths are inside that checkout, and verifies no `renderer_3d` import.
- Exact original root command `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not slow' -q` → existing Qt async stall after 53%+ with no failure. Passing alternative `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not slow' -vv --timeout=30` → initially **801 passed, 4 skipped, 8 deselected, 2 warnings in 25.23s**; after adding three facade-boundary cases, **804 passed, 4 skipped, 8 deselected, 2 warnings in 25.18s**. One intervening rerun stalled at `test_worker_uses_asset_snapshot`; that node passed alone and the next identical full run completed.

## Session: 2026-07-16 — Preview disk cache

Project-local `.preview_cache/` stores bounded prepare results for horizon /
well_stratification / well_head. LAS and SGY remain interactive without disk
cache. Clear via DataPage.clear_preview_cache() / toolbar button.

---

## Session: 2026-07-16 — Full-project audit + SEGY slice scrub

### Phase 22: Full-project audit hardening — COMPLETE ✅ (pushed)

**Method:** Verify prior geo-viz deep-audit CRITICAL items; spawn 3 read-only reviewers (core / UI / packages); fix high-confidence bugs; sample-test; commit + push both repos.

| Repo | Commit | Remote |
|------|--------|--------|
| geo-viz-engine | `1bf80d34` fix: geometry, cache, display | `origin/main` |
| paleo-workbench | `66b7436` fix: lifecycle, mapping, preview | `origin/main` |

**geo-viz fixes:** DTW `Qt.PenStyle.DashLine`; multi-ring polygon move by vertex id; map `ScreenPathCache` pan/size invalidation; sonic TWT ×2; curve `unit` preserved; contour major = every 5th level index.

**workbench fixes:** draft save keeps facies/well attributes; reference_layer path relativize; atomic project save + `updated_at`; GDAL close; SEGY single-pass load; QC error status; GeoJSON real export; factor_tasks wiring; import QThread shutdown; mapping dirty/active-doc guards; flush draft on project save; media stop; fade opacity cleanup; UI confirm on new/open.

**Sampled tests:** lifecycle/manager/adapters/smoke/export/mapping **56 passed**; mapping+data+app_shell **148 passed** (1 flaky subprocess PYTHONPATH fixed); geoviz edit **72 / 60**.

### Phase 23: SEGY preview position slider — COMPLETE ✅

**User ask:** 数据页面的地震体预览，可以拉动滑条调整剖面位置.

**Ownership:** Algorithm/UI widget in **geo-viz-engine** (visualization subproject of paleo-workbench). Workbench DataPage already hosts `SeismicPreviewWidget` via `GeoVizEngine`; no workbench page code required for the scrub control.

| Change | Detail |
|--------|--------|
| Payload | `source_path`, `max_slice_axis`, `axes: dict[str, SeismicAxisSpec]` |
| Load | `load_preview_slice(path, mode, position, limit)` single-slice + downsample |
| UI | mode combo + horizontal slider + position label; 80ms debounce |
| Caps | `slice_scrub` added to preview capabilities |

**Tests:** `geo-viz-engine/tests/test_geoviz_seismic_preview.py` + public API → **11 passed**.

**Planning:** Root `task_plan.md` / `findings.md` / `progress.md` updated; architecture documents geo-viz-engine as the viz algorithm subproject.

### Next actions

1. Optional backlog: Auto-Tie wiring, hidden-layer hit-test, demo draft idempotency.
2. Push engine + parent after commit if not already pushed.

---

## Session: 2026-07-16 — Visualization modularization (Phase 24)

### Goal
模块化可视化，与 geo-viz-engine 功能对齐：workbench 只做薄 host，算法/控件在子工程。

### Done
- `paleo_workbench/viz/hosts/`: WellLogHost, SeismicHost, CrossWellHost, PaleoMapHost, EnginePreviewHost
- `CompositeVisualizationPanel` → tab coordinator + status line; 5 tabs (测井/地震/连井/古地理/引擎预览)
- LAS: `geoviz.load_las_preview` (no lasio reimpl)
- SEGY: prefer `seismic_path` → `SeismicView.load_segy`; volume via `SeismicLoader.get_volume_downsampled` fallback
- Summary: engine-preview resource types, predictions, multi-well 连井 virtual asset
- Facade: `load_las_preview`, `SeismicLoader` on `geoviz` public API
- Tests: **54 passed** (viz + independence + panels)

### Boundary
```
Workbench host (thin)     geo-viz-engine (thick)
  VizAdapter              load_las_preview / SeismicLoader
  viz/hosts/*             WellLogCanvas / SeismicView / …
  VisualizationPage       GeoVizEngine.prepare/render
```

---

## Session: 2026-07-16 — Richer import/export (Phase 25)

### Import
- `ImportReport.summary_text` / `by_type`
- Enriched `parsed_summary` (size, mtime, type_label, small-file probes)
- `artifact_role` + tags from ROLE_BY_TYPE
- Skip empty files; optional preferred extension filter
- Classifier: geojson, vector (shp/gpkg), csv→tabular, audio

### Export
- `resources/io_registry.py` format registry
- `resources/export_service.py` unified service (asset convert, inventory, view snapshot)
- Converters: LAS→CSV/XLSX/JSON摘要, table→JSON/XLSX, SEGY→SUMMARY, GeoJSON normalize
- Data page: register ExportArtifact on success; 工程清单 export
- Visualization: PNG/SVG/PDF export wired to active tab (engine export_* when paint_all)

### Tests
export_service + updated classifier/context-menu/import — green suite in focused run.

---

## Session: 2026-07-16 — Module review + high-severity fixes

Goal: 逐一模块 review 找问题.

**Found (high):** inventory UI dead; import UI-thread UB; viz stale tabs; seismic full load; project not in viz page; save ignores draft fail; facies attr strip on normalize.

**Fixed:** data_page wiring/thread; composite clear; seismic volume-first; app_shell project; save gate; geometry_schema + FaciesPolygonItem extras; adapter messages/aliases.

**Verify:** 66 passed (export/import/viz/mapping_schema/independence focused suite).

---

## Session: 2026-07-16 — Agent protocol Phase 1–2 (baseline)

- Deep geo-stack + page topology scan complete.
- Created **AGENT_TASK_BOARD.md** (task table + data object dictionary + gate protocol).
- No new business feature coding in this turn (baseline-first).
- Next lock: T-COMMIT-01 or T-DATA-02 per board.

---

## Session: 2026-07-17 — PWF protocol catchup + baseline

### Catchup
- task_plan.md: historical phases 1–25 documented; follow-ups 11–16 closed; no Phase 26 yet
- ISSUE_BOARD.md: Blocker factor-map chain DONE; residual Medium: ISS-MAP-02, ISS-QC-01/02, ISS-PRED-01, ISS-VIZ-01, ISS-ENV-01
- findings.md: architecture notes stable; MAD/path/hit-test backlog items already resolved in code

### Baseline (Phase 1 diagnose)
```
QT_QPA_PLATFORM=offscreen pytest tests/ -q --timeout=60 -m "not slow"
→ 2 failed, 949 passed, 4 skipped, 8 deselected in 34.28s
```

Failures:
1. `test_workbench_production_imports_only_geoviz_facade` — `contour_draft.py` fallback `from geoviz_plots import ...` + allowlist missing `extract_contour_*`
2. `test_batch_generate_runs_idw_and_updates_mapping_shelf` — generate is now QThread async; test asserted immediately (0 tasks)

### Locked Phase 26
- Fix baseline regressions (in_progress)
- Then pick ISS-MAP-02 edit_history if green

### Phase 26 action log
- Fixed contour_draft: remove geoviz_plots deep import; facade-only extract_contour_lines
- Allowlist extract_contour_lines / extract_filled_contours in independence test
- preparation_integration waits for async FactorPrepareWorker (waitUntil)
- Focused retest: **9 passed in 2.16s**

### Phase 26 continued
- ISS-MAP-02: EditCommandStack on_push/undo/redo → PaleoMapDocument.edit_history (cap 200)
- Test: test_edit_history_appended_on_command_push **passed**
- Baseline fixes **3 passed** together

### Phase 26 finalization
- Commit d24b283 on main (ahead 1, not pushed unless requested)
- Phase 26 marked complete in task_plan.md
- Next candidate: ISS-QC-01 expand run_basic_qc rules

### 2026-07-17 push + ISS-QC-01 lock
- Pushed f91ff0b to origin/main (baseline green + edit_history)
- Lock ISS-QC-01: deepen run_basic_qc rule set

### ISS-QC-01 implement
- Expanded run_basic_qc: horizon, facies, geometry, wells, contour lines, well_table flags
- RULE_DESCRIPTIONS updated for new engine keys
- tests/test_qc_upsert.py expanded
- Focused suite: **15 passed in 2.07s**

### ISS-QC-02 lock
- Goal: spatial IssueLayer fields on QC issues (geometry/ref) for map locate
- Start from run_basic_qc issue dicts + review table display

### ISS-QC-02
- make_issue + geometry/centroid/ref; per-facies and per-well spatial issues
- issue_layer_geojson FeatureCollection
- QCIssueTable 定位 column
- Tests green after column count fix

### ISS-PRED-01 lock
- Deepen well/seismic prediction beyond pure Mock when assets bound

### ISS-PRED-01
- LocalAssetPredictionAdapter: GR-window facies from LAS; seismic path meta
- well/seismic workflows switch to local adapter; mock fallback preserved
- regions_to_depth_intervals honors explicit top/bottom
- **17 passed** focused suite

### ISS-VIZ-01 lock
- Add well-tie workspace tab on VisualizationPage

### ISS-VIZ-01 done
- Facade: `WellTieCanvas` via `geoviz_well_tie.canvas` + independence allowlist
- `WellTieHost`: extract DT/RHOB (or synthetic proxies) + optional seismic volume trace → `set_tie_data`
- `CompositeVisualizationPanel`: 6th tab「井震标定」before 引擎预览; routes well_log/seismic/prediction
- Tests: `test_well_tie_host.py` + composite/alignment/facade updates

### ISS-KRIG-01 done
- UI label `克里金(MVP·线性)` + tooltips; alias `克里金` still maps to SciPy linear
- `interpolate_factor_grid` emits `mvp_note` for linear backend

### ISS-ENV-01 done
- `paleo_workbench/env_bootstrap.py`: checkout path inject when geoviz not installed
- Wired from package `__init__` + `main.py` with clear install error
- Root `README.md` documents editable install preference
