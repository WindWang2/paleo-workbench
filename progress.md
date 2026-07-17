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
## Session: 2026-07-17（系统级 GIS 自动审计与重构）

- [IN PROGRESS] 启动 PWF 状态恢复；已读取 Planning with Files、brainstorming、systematic-debugging 与 `geo-viz-engine/CLAUDE.md`。
- [DONE] 确认 PWF 三文件存在；session-catchup 无未同步报告。
- [DONE] 记录初始 Git 状态：`main@0e86375`，保留现有未跟踪文件，不做清理或覆盖。
- [NEXT] 分块完整读取三份 PWF 文件，建立当前 Issue 基线，然后执行 10 页路由、路径 I/O、数学模型、拓扑和线程生命周期的只读审计。
- [DONE] 读取 `task_plan.md` 全文并确认历史 Phase 22/26 基线；新增 Phase 27 风险优先审计板（ISS-AUDIT/TOPO/THREAD/ASYNC/ALG/ARCH/STATE）。
- [DECISION] 自动采用“风险优先、证据驱动、engine-first 原子迁移”；拒绝一次性大重写与页面层补丁堆积。
- [DONE] 完整恢复 `findings.md` 的历史架构/缺陷上下文；识别出需要复验的历史修复：多环 vertex-id、闭合环插点、路径逃逸、DataPage latest-only worker 生命周期。
- [DONE] 已复读 `progress.md` 1–600 行，确认历史测试基线与线程修复轨迹；继续读取剩余日志后开始源码清单审计。
- [DONE] 完整读取 `progress.md`；开始 ISS-AUDIT-01 静态检索。
- [FOUND] 当前代码测试基线是 10 个 `PAGE_NAMES`，PWF 旧“9 页”描述需要纠正；定位 Project I/O、算法与 QThread 候选入口，下一步逐文件核对。
- [FOUND] 10 页 rail/stack 顺序一致，但数字快捷键只覆盖 1–9，第 10 页无快捷入口（ISS-ROUTE-01）。
- [FOUND] ProjectManager 原子磁盘写入已存在；保存失败时 `meta.updated_at` 可能先行污染内存（ISS-STATE-01 根因候选）。
- [DONE] 核对 `project.paths`：相对 `..` 与 symlink 越界均被 resolve+containment 拦截；绝对外部路径按契约允许。
- [FOUND] 10 页路由仍有 2/3/4 魔法索引与 `_switch_page` 越界未防御，合并到 ISS-ROUTE-01。
- [DONE] 定位指定数学模型及测试文件；公式并非纯 Mock，但 MAD/砂地比/方向趋势仍归属 workbench，engine-first 边界存在缺口（ISS-ARCH-01）。
- [FOUND] MAD=0 且存在偏离中位数时当前全部返回 0，极端值被漏检（ISS-ALG-01）。
- [FOUND] 方向趋势公式正确，但 `(H,W,N)` 全量向量化会在 N=2000+ 造成多数组峰值内存；计划迁入 engine 并做 chunked 计算。
- [FOUND] engine IDW 存在三项 P0 候选：全量三维数组、断层四重级 Python 循环、严格 ccw 漏掉端点/共线屏障；新增 ISS-ALG-04。
- [FOUND] LOO R² 无界 O(N²)；synthetic 误用进程随机 hash 导致跨进程不确定（ISS-REPRO-01）。
- [FOUND] 制备 QThread 对 live ProjectDocument 做后台 mutation；quit+wait(3000) 无法中断长计算且超时后丢引用，存在确定的销毁竞态。
- [FOUND] 等值线初稿仍在 GUI slot 同步提取；ISS-ASYNC-01 根因已确认，现有测试缺 running shutdown/取消覆盖。
- [FOUND] PreviewController 超时后清空 jobs 但线程仍是 controller child；页面销毁仍会删除运行线程。Import timeout `setParent(None)` 也没有全局 keeper，两个生命周期缺口纳入 ISS-THREAD-01。
- [FOUND] 通用 media preload 无界 read_bytes，超大 PDF/GeoTIFF/image 会造成后台内存峰值与 Qt 解码复制。
- [FOUND] lifecycle 测试只覆盖 0.2s（低于 hard-cap），没有命中“超时仍运行”分支；engine SeismicView cleanup 也仅 wait(500) 且不检查结果。
- [FOUND] SeismicView 快速重复 async load 会覆盖旧 worker 引用但不停止旧任务；异常路径不 close loader、固定降采样无体素预算；SeismicHost 仍有 GUI 同步全量 fallback。
- [FOUND] 编图页 `normalize_facies` 静默只取 Polygon 外环、错误处理 MultiPolygon；scene/items/commands 全为单 ring。用户指定多环拖拽/Shape 冲突已确认是现存 P0（ISS-TOPO-01）。
- [FOUND] engine 多环 MovePolygon 实现正确但缺 hole 测试；删除闭合 vertex 会只删首 occurrence 并打开环；MultiPolygon 被 flatten 后错误序列化为 Polygon。
- [DONE] 读取 writing-plans、TDD、executing-plans 与 worktree 隔离规则。用户已授权全自动且当前 PWF/未跟踪资产均在主 checkout，本轮选择原地内联执行，不创建额外 worktree、不派生 sub-agent。
- [NEXT] 将 Phase 27 拆成 route/state、engine math、topology、thread/async 四个 TDD 子项目；每项先 RED 再最小 GREEN。
- [DONE] Phase 27 已写成 7 个内联 TDD 任务，覆盖 route/state、engine math、engine topology、workbench multi-ring、通用 job lifecycle、contour/seismic async 与全量门禁。
- [TEST BASELINE ATTEMPT 1] offscreen full suite 到 51% 后 stall 超过 3 分钟，无断言失败输出；已 TERM 精确 PID 391169。策略切换为 focused suites，最终再用 `-vv --timeout=60`。
- [TDD RED · Task 27.1] 新增 3 个回归用例并确认全部按预期失败：缺少 `0` 快捷键；`_switch_page(999)` IndexError/负索引副作用；atomic replace 失败后内存 `updated_at` 被改为 2099 时间。`3 failed in 4.59s`。
- [TDD GREEN · Task 27.1] 0 映射第 10 页、switch 范围防御、2/3/4 魔法索引收拢、保存成功后才提交 updated_at；focused `37 passed in 7.70s`。
- [PWF ERROR] 首次状态回写 patch verification failed；已用精确定位拆分重试，生产代码未受影响。
- [IN PROGRESS · Task 27.2] 已确认 geoviz lazy facade 扩展点与 geoviz_plots exports；准备写 engine 数学 RED 测试。
- [TDD RED SETUP · Task 27.2] 已写 7 个 engine/root 边界用例；首次混合仓库 pytest 因 rootdir 切换导致 collection error（非行为断言），策略改为 engine/root 分开运行。
- [TDD RED · Task 27.2] engine focused：`6 failed, 3 passed, 1 warning in 1.24s`；失败精准覆盖 4 个缺失门面 API、共线屏障漏判、IDW 缺少分块参数。
- [TDD RED · Task 27.2] root focused：`1 failed in 0.94s`；确认合成样点依赖进程随机化的 Python `hash()`。
- [NEXT] 下沉纯数学实现、改造受限内存 IDW，并将 workbench 包装层切换为 engine facade。
- [MUTATION · Task 27.2] 新建 `geoviz_plots.analytics.well_qc` 与 `interpolation.directional`：零 MAD 保留偏离信息、严格轴参数校验、趋势网格按 cell chunk 计算。
- [MUTATION · Task 27.2] IDW 改为过滤全部非有限控制点、orientation/on-segment 鲁棒屏障判交、可配置 cell chunk；新增数学 API 的 `geoviz_plots`/`geoviz` 门面导出。
- [NEXT] 运行 engine focused GREEN；根据真实反馈修正后再切换 workbench thin-host 包装层。
- [TDD GREEN · Task 27.2 engine] 数学硬化与 IDW focused：`9 passed, 1 warning in 0.72s`。
- [MUTATION · Task 27.2 thin host] `well_qc` 与 `directional_trend` 删除重复数学实现并委托 `geoviz`；factor directional backend 直接走 engine facade；合成样点基值改为 SHA-256 稳定摘要。
- [NEXT] 运行 root 数学/因子 focused 回归，随后补充大样本 LOO 有界性 RED。
- [REGRESSION · Task 27.2 root] well-table/directional/factor/e2e focused：`29 passed in 0.89s`。
- [TDD RED · Task 27.2 LOO] 2000 点测试要求确定性首尾覆盖且调用数固定为 `MAX_LOO_SAMPLES`；当前缺少上限常量并执行全量 LOO，单测按预期失败（`1 failed in 0.96s`）。
- [NEXT] 用均匀确定性索引将验证调用上限设为 64，并仅在抽样观测上计算 R²。
- [MUTATION · Task 27.2 LOO] 新增 `MAX_LOO_SAMPLES=64`；大样本用覆盖首尾的等距确定性索引，训练仍使用其余全部点，R² 只在验证子集计算。
- [TDD GREEN · Task 27.2 LOO/repro] 大样本有界调用与稳定摘要：`2 passed in 0.83s`。
- [NEXT] 执行 facade 与完整 Task 27.2 focused 回归；全绿后更新 Issue Board 并进入拓扑 Task 27.3。
- [REGRESSION · Task 27.2 root] 完整数学/因子链路：`30 passed in 1.01s`。
- [REGRESSION FAIL 1 · engine facade] `34 passed, 1 failed`；失败为既有 optional-import 契约：`geoviz/prepared_codec.py` 顶层导入 `geoviz_cross_well.FormationTop`，在屏蔽可选渲染包时导致 `import geoviz` 失败。新增数学测试与 IDW 均通过。
- [ROOT CAUSE] 核心 codec 的运行时类型构造与可选 renderer 模型耦合，lazy facade 无法隔离其顶层 import；归入 ISS-ARCH-01，不计作数学实现失败。
- [NEXT] 检查 prepared payload 的类型边界并将可选模型导入延迟到实际 decode 路径，保持核心 `import geoviz` 零可选依赖。
- [FIX ATTEMPT 1 · facade] FormationTop 改为仅在 formation encode/decode 分支动态导入；codec 4 个 round-trip 测试通过。
- [REGRESSION FAIL 2 · facade] optional-import 仍失败，堆栈推进到 `prepared_codec -> previews.dat -> geoviz_plots`；说明 codec 同时顶层耦合 XY/Surface payload 定义，而 `previews.dat` 混有渲染 import。
- [STRATEGY] 不触碰 payload 契约；将 `SurfacePreviewPayload`/`XYPreviewPayload` 也延迟到实际 encode/decode 分支。若第三次仍失败，立即触发 3-Strike RCA 并重画 codec/core 边界。
- [FIX ATTEMPT 2 · facade GREEN] DAT payload 类也改为分支内动态导入；optional-import + prepared-codec：`5 passed in 0.87s`。未触发第三次失败，3-Strike 阈值未达到。
- [ARCH] `import geoviz` 现不再因 prepared cache codec 提前加载 cross-well 或 plots 可选包；实际编码/解码对应 kind 时仍保持原类型校验与 round-trip。
- [NEXT] 重跑 Task 27.2 两仓 focused 总门禁并同步 Issue Board。
- [DONE · Task 27.2 engine gate] facade/codec/math/IDW：`39 passed, 1 config warning in 1.10s`。
- [DONE · Task 27.2 root gate] well-table/directional/factor/E2E：`30 passed in 0.88s`。
- [DONE] ISS-ALG-01/02/03/04 与 ISS-REPRO-01 关闭；ISS-ARCH-01 的数学/插值门面部分关闭，SEGY/contour 部分留待 Task 27.6。
- [NEXT · Task 27.3] 进入 engine polygon closure/MultiPolygon invariants，先写 hole move、闭合端点删除与 MultiPolygon round-trip RED。
- [TDD RED · Task 27.3] topology/edit focused：`3 failed, 38 passed in 0.33s`。失败精准命中 open ring 不闭合、MultiPolygon 序列化扁平为 Polygon、删除首闭合 vertex 后首尾 id 不同；hole MovePolygon/undo 新用例已通过。
- [ROOT CAUSE] `FeatureRef` 只存平铺 rings，丢失 polygon part 边界；builder 不规范化闭合；DeleteVertex 以 `list.index(vertex_id)` 忽略逻辑闭合端点与 `remove_index`。
- [NEXT] 为 FeatureRef 增加非破坏性的 `polygon_ring_counts` 元数据，builder 规范闭合；删除命令基于完整 ring snapshot 处理逻辑 vertex 并重建索引。
- [MUTATION · Task 27.3] `FeatureRef` 增加 `geometry_type/polygon_ring_counts`；builder/add_feature 统一闭合 ring；GeoJSON serializer 按 part 元数据恢复 Polygon/MultiPolygon。
- [MUTATION · Task 27.3] DeleteVertex 以逻辑 ring（排除 closing duplicate）和完整 vertex-id snapshot 执行/撤销；变更后重建反向与边索引，首/末闭合点视为同一逻辑顶点。
- [TDD GREEN · Task 27.3 focused] topology/edit commands：`41 passed in 0.35s`。
- [NEXT] 跑 edit engine/paleo canvas/hierarchy 回归，确认新增 FeatureRef 默认字段不破坏调用方。
- [DONE · Task 27.3 regression] topology/edit/edit-engine/hierarchy/map canvases：`89 passed in 0.94s`。
- [DONE] ISS-TOPO-01 engine 侧 closure、hole move、MultiPolygon grouping 已固定；workbench thin host 尚未迁移，Issue 保持 partial。
- [NEXT · Task 27.4] 审计 workbench mapping 的 geometry schema/document I/O/items/commands/scene，先锁定 Polygon holes 与 MultiPolygon round-trip RED。
- [TDD RED · Task 27.4] document I/O + hole scene：`3 failed, 2 passed in 0.45s`。`geometry_type` 被 normalize 丢弃、MultiPolygon/holes 均被截成首 ring、洞内 `contains()` 错误返回 true。
- [ROOT CAUSE] workbench compact record 没有 canonical geometry 元数据；`FaciesPolygonItem` 基于 `QGraphicsPolygonItem` 只能表达单 ring，scene 所有移动/保存操作因此只能看到外环。
- [NEXT] 新增 geometry canonicalization helpers；Facies item 切为 OddEven `QGraphicsPathItem` 并保留 polygons→rings，legacy `coordinates()` 仍映射第一 outer ring。
- [MUTATION · Task 27.4] geometry schema 新增 canonical Polygon/MultiPolygon 解析与闭合规范；document I/O 同时保存 compact coordinates 和标准 geometry。
- [MUTATION · Task 27.4] Facies item 切换为 OddEven QGraphicsPathItem，内部保留全部 part/ring；移动覆盖全部 rings，legacy 顶点 API 映射第一 outer ring。
- [TEST HARNESS ERROR] focused 得到 `4 passed, 1 failed`；唯一失败是新增测试被插入旧测试函数中段，旧 `w_item/w_before` 断言误落入新函数，属于测试排版错误，不计产品 fix strike。
- [NEXT] 修复测试函数边界后复跑同一 focused 集。
- [HARNESS FIX] 恢复 translate 测试尾部至原函数，产品实现未变。
- [TDD GREEN · Task 27.4 I/O/item] holes/MultiPolygon document round-trip、OddEven hole、全 ring move/undo：`6 passed in 0.46s`。
- [NEXT] 增加闭合 outer vertex 编辑、hole hit-test 与逐 ring save validation RED；随后补齐 scene 的 ring-address handle 与 geometry-aware hit/validation。
- [TDD RED · Task 27.4 scene] 三项全部按预期失败：complex coordinates 使 legacy hit-test TypeError；只生成 4 个 outer handles 而非 8；save validation 忽略自交 hole（`3 failed in 0.55s`）。
- [ROOT CAUSE] scene/commands 仍以单 ring callback 和单 `vertex_index` 定址；map_edit_api native/pure hit-test 都只识别 point 或 ring；topology gate 只调用 `validate_ring(item.coordinates())`。
- [NEXT] 扩展 handle/command 为 part+ring 地址；complex polygon hit-test 强制 geometry-aware Python 路径；逐 ring 基础校验并调用 engine facade 的整 Shape 校验。
- [MUTATION · Task 27.4 engine validation] engine 新增 `validate_polygon_geometry`，用完整 Shape 捕获 hole containment/自交/多 part 冲突，并由 `geoviz` facade 懒导出。
- [MUTATION · Task 27.4 ring address] Facies item/handles 新增 part+ring API；新增 RingEditCommand；direct scene vertex edit 可按 ring 地址执行；complex hit-test 绕过旧 C++ 单 ring payload并按 outer-minus-holes 判定。
- [NEXT] 补齐 mouse drag/active handle 地址传播与逐 ring+whole-shape save validation，然后运行 focused GREEN。
- [MUTATION · Task 27.4 scene] direct/drag/delete 路径开始传播 part+ring 地址；逐 ring `validate_ring` 与 engine whole-shape 验证共同构成 save gate；snap 候选覆盖所有 rings。
- [FOCUSED] hole hit-test 与 invalid-hole save validation 已通过；ring-address handle/edit/undo 主断言也通过。
- [TEST HARNESS ERROR] 唯一失败是新测试再次插入原 handle 测试中段，原“单 ring=4 handles”尾部误落进 hole 测试（当前正确为 8）；不计产品 strike。
- [NEXT] 恢复两个测试函数边界并复跑；随后执行 mapping 全域回归。
- [HARNESS FIX] 单 ring handle 断言恢复到原测试；hole 测试只保留 8-handle/ring-address/edit/undo 契约。
- [TDD GREEN · Task 27.4 scene] simple handles、hole handles、complex hit-test、invalid-hole save gate：`4 passed in 0.42s`。
- [NEXT] 执行全部 `test_map*`/mapping document/save/topology 回归，定位 legacy compact record 与 QGraphics base 兼容问题。
- [DONE · Task 27.4 mapping regression] 全部 map/mapping suites：`122 passed in 3.97s`；simple Polygon legacy shape、页面集成、save draft、topology rebuild、merge/split 均无回归。
- [NEXT] 补一条 hole handle 实际 mouse drag 验证与闭合首点 delete 检查；全绿后关闭 Task 27.4 并转线程生命周期。
- [VERIFY · Task 27.4] hole handle 实际 press→move→release 只修改被定址 hole ring，undo 完整恢复：`1 passed in 0.38s`。
- [DONE · Task 27.4] Polygon holes/MultiPolygon I/O、OddEven hit、全 ring move、part/ring/vertex handle、闭合编辑、engine whole-Shape save gate 均落地；ISS-TOPO-01 关闭。
- [NEXT · Task 27.5] 进入 QThread 生命周期：先复现 preview/import/factor worker 超时销毁、stale commit 与 live ProjectDocument 后台 mutation。
- [TDD RED · Task 27.5] 四条线程/内存契约全部失败：Factor worker 无 snapshot result 信号；缺 application keeper；preview/import 超时无 owner 转移；缺媒体预载字节预算（`4 failed in 0.54s`）。
- [ROOT CAUSE] prepare worker持有 live ProjectDocument；preview controller 清空仍运行 child QThread 引用；import 仅 `setParent(None)`；media 使用无界 `Path.read_bytes()`。
- [NEXT] engine CancellationToken + workbench application keeper；FactorPrepareResult DTO 在 GUI commit；preview/import timeout adopt；preload stat budget。
- [MUTATION · Task 27.5 core] engine 新增 thread-safe `CancellationToken/JobCancelled`，无 Qt 依赖并由 geoviz core 直接导出。
- [MUTATION · Task 27.5 keeper] 新增 QApplication-lifetime `DetachedJobKeeper`，按 QThread identity 持有 thread+worker，finished 后自动 deleteLater/release。
- [NEXT] 改 Factor worker snapshot DTO 与 preview/import shutdown adopt；两次 mutation 后再同步。
- [MUTATION · Task 27.5 factor] FactorPrepareWorker 深拷贝 project、返回 `FactorPrepareResult`，页面只在 token 有效且仍绑定同一 project 时于 GUI slot commit；shutdown cancel + timeout adopt。
- [MUTATION · Task 27.5 preview/import/media] preview hard-cap 后 keeper adopt；import 分离 page slots 与 direct thread.quit，timeout adopt；media 预载先 stat 并最多读取 64 MiB+1。
- [NEXT] 运行四条 focused GREEN；若兼容测试失败，区分预期契约更新与真实生命周期回归。
- [FOCUSED ATTEMPT] Factor snapshot与 media budget 通过；preview/import 均已被 keeper 持有并在 finished 自动释放。
- [TEST HARNESS ERROR] 两项失败仅因 release 后继续调用已 deleteLater 的 `thread.isRunning()`，触发 Shiboken deleted wrapper；改为轮询 keeper ownership，不计产品 strike。
- [NEXT] 复跑四契约，然后更新旧 Factor worker 测试为 DTO 语义并补 stale/prepare-timeout RED。
- [TDD GREEN · Task 27.5 base] factor snapshot、preview/import keeper、media budget：`4 passed in 2.22s`。
- [TEST HANG · prep suite attempt 1] 8 个测试均输出通过点，但 pytest 超过 25s 未退出且未打印 summary，疑似 detached QThread/deleteLater teardown 残留；无断言失败。
- [NEXT] 精确定位/终止残留 pytest，单跑 running-prepare shutdown 用例并检查 keeper release 与 thread delete 时序。
- [TEST HANG · prep attempt 2] 单跑 stale/keeper 用例仍在测试 teardown 卡住；主线程 wchan 为 Qt poll，未见断言失败。第一残留 PID 409193 已 TERM，第二 PID 409571 待 TERM。
- [ROOT CAUSE HYPOTHESIS] keeper 使用无 receiver-context 的 Python lambda 连接 `QThread.finished`，可能在发射线程直接调用 `_release/deleteLater`，破坏 QObject GUI-thread affinity 并令 deferred-delete teardown 悬挂。
- [STRATEGY CHANGE] keeper finished 信号改为显式 queued relay/GUI-thread release；再单跑一次。若第三次仍 hang，触发 3-Strike RCA 并更换为非 QObject registry + app timer reaper。
- [STRIKE 3 · STOP] queued relay 后单测仍被 `timeout 15s` 终止，exit 124；已停止产品代码修改。
- [RCA SYNCED] `findings.md` 记录三次证据、排除项与新策略；`task_plan.md` 标记 3-Strike 门禁。
- [NEXT · DIAGNOSTIC ONLY] 用外层 Python faulthandler 5 秒全线程 dump 定位精确阻塞栈；有证据后才恢复 mutation。
- [RCA EVIDENCE] faulthandler 栈定位至 `_on_prepare_failed -> QMessageBox.warning`；shutdown 未断开 failed page slot，stale error 进入 modal event loop。
- [STRATEGY RESUMED] 按证据恢复 mutation：断开 failed page slot + token stale guard + 非模态错误状态；随后单跑原 hang 用例。
- [RCA FIX RESULT] modal hang 已消失，测试在 3.87s 正常报告失败；新根因是 keeper `Signal(int)` 仅 32 位，`id(thread)` 64 位发射 OverflowError，registry 未 release。
- [NEXT] release relay 改为 `Signal(object)/Slot(object)`，复跑同一用例；该修正由明确 warning 与 traceback 驱动。
- [FIX] keeper release relay 改为 Python object payload，消除 64-bit id → Qt int overflow。
- [TDD GREEN · Task 27.5 prepare teardown] 原三次 hang 用例现 `1 passed in 0.91s`，无 modal/Overflow/timeout。
- [NEXT] 运行 prep/preview/data lifecycle 全域回归，确认旧接口兼容与 page close 行为。
- [REGRESSION ATTEMPT 1] 合并线程套件在 60s 上限前出现 `FEE` 后未退出（124）；因 kill 前 pytest 未打印详情，拆分子域定位。
- [REGRESSION GREEN · preparation] prep worker/page/integration：`14 passed in 5.92s`。
- [NEXT] 单独运行 preview lifecycle（-x -vv）定位合并套件的首个 F/E；随后 data import suite。
- [REGRESSION FAIL 1 · preview order] preview 前 10 项通过，`test_cache_miss_after_file_rewrite` 等待 controller idle 超时；无 QThread destroyed 输出。
- [MINIMIZATION] “keeper timeout → cache rewrite”最小顺序 `2 passed in 1.15s`，未复现；说明不是简单 keeper key/id 污染，暂按偶发 finished-cleanup race 继续复跑完整 preview 并采集状态。
- [NEXT] 重跑完整 preview；若同点再失败，增加 controller terminal-state 诊断并修改清理连接上下文，不做无证据修补。
- [REGRESSION FAIL 2 · preview] 完整 preview 再次仅 cache rewrite idle 超时（29 passed / 1 failed）；同点第二次失败。
- [SEQUENCE CHECK] keeper+rescan+stale+cache-hit+cache-rewrite 显式序列 `5 passed in 3.95s`，说明累积调度下的 thread.finished affinity race。
- [ROOT CAUSE] PreviewController 用无 receiver-context lambda 从 `QThread.finished` 直调 `_on_thread_finished/QTimer.singleShot`；回调可在 managed thread 执行，违反 controller GUI-thread affinity。
- [NEXT] 增加 controller-owned queued terminal relay，再跑完整 preview；第三次失败才触发该子缺陷 3-Strike。
- [STRIKE 3 · preview STOP] queued relay 版本全域仅输出 8 dots 后被 45s timeout（124）；停止产品修改。
- [RCA SYNCED · preview] 高概率为 thread.deleteLater 先于携带 wrapper 的 queued terminal cleanup；新策略为 faulthandler定位 + deletion-order重构，不增加 sleep/timeout。
- [NEXT · DIAGNOSTIC ONLY] faulthandler 包装 preview 前 12 项，确认具体 wait 栈与 controller `_active/_jobs` 状态。
- [RCA EVIDENCE · preview] rescan idle wait时 `_jobs` 未清，teardown 对保存的 thread 调用即报 C++ object already deleted；确认 thread.deleteLater 早于 queued cleanup。
- [STRATEGY RESUMED · preview] 移除 finished 上的提前 thread.deleteLater，统一由 GUI `_on_thread_finished` 清状态后删除；shutdown 增加 deleted-wrapper防御。
- [MUTATION · preview deletion order] QThread wrapper 现由 GUI cleanup 在清 `_jobs/_active` 后 deleteLater；worker 仍由 finished 自动删除。
- [MUTATION · preview teardown defense] shutdown 对历史/外部已删除 wrapper 的 interruption/wait RuntimeError 安全跳过，不再令页面 close 二次报错。
- [NEXT] 先复跑 rescan focused，再跑 preview 全域，验证 3-Strike 新策略。
- [TDD GREEN · preview cleanup] rescan focused `1 passed in 3.30s`；preview/lifecycle 全域 `30 passed in 7.85s`。
- [DONE RCA] deletion-order 新策略验证成功，preview 3-Strike 状态解除；无 idle timeout、deleted QThread 或 teardown error。
- [NEXT] 跑 DataPage import 全套；随后合并 prep+preview+data 线程门禁。
- [REGRESSION FAIL 1 · import] DataPage：`6 failed, 44 passed`，所有失败均为 async import_finished 未发射。
- [ROOT CAUSE] 新增 direct `worker.finished/failed -> thread.quit` 使 worker/thread 在 queued GUI report handler 前销毁，丢失 import commit signal。
- [MUTATION · import terminal order] 移除 normal-path direct quit；恢复 GUI handler apply/emit 后 `_finish_import_job` quit。shutdown 已主动 quit，不影响 keeper adopt。
- [NEXT] focused file/folder/import-status 三用例，再跑 DataPage 全套。
- [REGRESSION GREEN · DataPage] focused `3 passed in 3.34s`；全套 `50 passed in 7.76s`。
- [THREAD WARNING] 全套捕获 `QThread::wait: Thread tried to wait on itself`；queued Python lambda 无 QObject receiver context，import handler仍可能在 worker thread运行。
- [NEXT · TDD] 新增 import commit thread-affinity RED；改 DataPage bound @Slot + sender() job lookup，消除 lambda/context 与 self-wait。
- [AFFINITY CHECK] 新 commit-thread 用例已显示 `import_finished` 在 page GUI thread（`1 passed`），因此 warning 并非稳定复现于普通 import。
- [DECISION] 仍移除无 context lambdas：bound @Slot 能显式保证 receiver affinity，并让 shutdown 精确断开页面槽；随后全套检查 warning 是否消失。
- [MUTATION · import affinity] import finished/failed 改为 DataPage bound queued slots，通过 `sender()` 映射 thread/worker job；消除无 context lambda。
- [REGRESSION FAIL 2 · import cleanup] commit 发生在 GUI thread，但 `_finish` wait后重复 delete 已由 `thread.finished` 删除的 worker，造成 7 个 Shiboken teardown error（44 passed）。
- [FIX] wrapper deletion 单一归属 `thread.finished`；GUI `_finish` 不再二次 deleteLater。
- [NEXT] 重跑 DataPage 全套并确认无 self-wait/deleted wrapper Qt message。
- [REGRESSION GREEN · DataPage] `51 passed in 8.11s`，无 self-wait/deleted wrapper warning。
- [REGRESSION GREEN · Task 27.5 combined] prep+preview+data lifecycle：`95 passed in 15.14s`。
- [NEXT] 将 CancellationToken 下传 engine IDW/directional chunk loop 与 factor pipeline；补取消延迟 RED/GREEN 后关闭 Task 27.5。
- [TDD RED · cancellation checkpoint] directional/IDW 均拒绝 `cancellation_token` 参数，2 个用例按预期失败（2 failed in 1.55s）。
- [NEXT] engine 两个 chunk loop 每块前 checkpoint；root factor `_run_grid/LOO/interpolate/batch` 透传同一 token；worker 使用已有 token。
- [MUTATION · cooperative cancel] IDW/directional 每 chunk 前 checkpoint；factor grid/LOO/task/batch 全链透传 token，SciPy backend前后检查，JobCancelled 不再被 LOO吞掉。
- [TDD GREEN · engine cancellation] math/IDW hardened：`11 passed in 1.38s`。
- [NEXT] root factor+prep回归，随后 Task 27.5 合并门禁并关闭 Issue。
- [REGRESSION GREEN · cancel pipeline] factor/directional/prep：`31 passed in 6.03s`。
- [DONE · Task 27.5 gate] prep+preview+data：`95 passed in 15.26s`；ISS-THREAD-01 关闭，ISS-ASYNC-01 插值部分关闭。
- [NEXT · Task 27.6] contour extraction worker化；SEGY rapid-load generation/cancel、loader finally-close、voxel budget与 host sync fallback 清除。
- [TDD RED · Task 27.6 contour] 将 3 个既有 UI 用例改为等待异步结果，并新增 GUI/worker 线程身份回归；当前同步实现按预期失败：`1 failed, 5 passed in 2.48s`，记录到 `ran_off_gui == [False]`。
- [NEXT] 实现共享 ContourDraft snapshot worker、engine 每 level 取消检查，以及 Preparation/Mapping 两个 thin-host 的 generation/工程身份提交门禁。
- [GREEN · Task 27.6 contour] 新增共享 `ContourDraftWorker`：深拷贝工程只读计算、返回 draft DTO，GUI 线程再对 live map 做短提交；制备页和编图页均具备 token、工程身份门禁、shutdown 超时托管，AppShell rebuild 同时关闭两页作业。
- [GREEN · engine contour] `extract_contour_lines` 在 generator 前、每个 level 前和完成后轮询 CancellationToken；workflow 全链透传取消状态。
- [TEST] contour domain/UI focused：`13 passed in 5.28s`；新线程身份用例确认提取运行于非 GUI QThread。
- [NEXT] 开始 SEGY RED：连续加载 latest-only、异常 finally-close、budget-derived downsample、host 禁止同步 fallback。
- [TDD RED · Task 27.6 SEGY] engine 新用例按预期为 `3 failed`：缺 budget factor API、worker generation/max_voxels DTO、异常 finally-close；root host 用例先暴露 fixture 构造漏传必填 `label`（测试夹具错误，不计产品 strike）。
- [NEXT] 修正 host 测试夹具后实现 engine prepared result 与 cooperative loader；再加 SeismicView latest-generation 回归。
- [GREEN · Task 27.6 SEGY core] engine worker 现返回 generation/factor DTO，预算函数保证输出体素上限；loader 按 inline 轮询取消且按 factor 缓存；所有成功/异常/取消路径均在 worker thread 的 `finally` 关闭句柄。
- [GREEN · thin host] `SeismicHost` 只调用 `load_segy_async`；adapter 不再在 GUI resolve 路径同步读取 SEGY。host contract `1 passed`。
- [TEST] engine worker+loader `7 passed, 1 failed`；唯一失败是测试仍把新 `SeismicLoadError` DTO 当字符串做 `in`（夹具断言迁移错误，不计产品 strike），finally-close 本身已执行。
- [NEXT] 修正 DTO 断言，补 SeismicView stale-generation/快速连续加载测试，并运行 view/adapter 回归。
- [TEST] root adapter/host/panel/alignment 回归 `20 passed in 4.37s`，确认 adapter 不解析且 host 异步调度。
- [TEST · latest-generation] engine `13 passed`，新增 rapid-load 用例的旧 generation 已被正确忽略；当前唯一失败/teardown error 是 fake meta 漏 `dt_ms/t0_ms`，导致 current generation 在测试渲染阶段抛 AttributeError（夹具错误，不计产品 strike）。
- [NEXT] 补齐真实 `SeismicVolumeMeta` 夹具并把体积扩到 3³，随后核对 worker registry/cleanup 与 facade 回归。
- [GREEN · latest-only] rapid-load 回归使用真实 `SeismicVolumeMeta`：第一次 worker 收到 interruption，旧 DTO 不触发 `segy_loaded`，仅第二代 `new.sgy` 被渲染/提交。
- [TEST] engine SEGY worker/loader/view focused：`14 passed in 3.01s`。
- [NEXT] 审计 engine facade/package independence、SeismicViewPanel 的 path-only 状态承接，以及 Task 27.6 更宽回归；之后更新 issue 状态。
- [TDD RED · prediction thin host] 新增 path-only payload 回归；当前面板未调度 `load_segy_async`，按预期 `1 failed, 5 passed`，确认 adapter 异步化后预测页存在承接缺口。
- [NEXT] 面板显示非阻塞 loading 状态，监听 engine `segy_loaded` 更新 shape/ready，并保持旧 volume payload 兼容。
- [GREEN · prediction thin host] `SeismicViewPanel` 对 path-only payload 立即切入 engine view/loading，监听 `segy_loaded` 后更新体积 shape 与 controls ready；旧 ndarray payload 仍走 `load_demo`。
- [TEST] seismic prediction panel/page/integration/workflow：`15 passed in 7.61s`。
- [NEXT] 执行 Task 27.6 contour+seismic 广域回归、package independence 与静态检索；若全绿则关闭 ISS-ASYNC/ARCH 并进入 Task 27.7 全量门禁。
- [AUDIT] 静态检索确认 `paleo_workbench` 已无 `.load_segy(...)` GUI 调用，唯一同步 helper `viz/seismic_load.py` 已成为无调用者兼容 API；`git diff --check` 无 whitespace 错误。
- [TEST COVERAGE] 为 engine contour 增加 cancellation-before-work 直接回归，锁定 facade/workflow 之外的底层取消契约。
- [NEXT] 运行 Task 27.6 广域门禁并检查失败是否为产品回归。
- [REGRESSION · Task 27.6] engine contour+SEGY broad gate：`57 passed in 10.33s`；root contour/prep/seismic/viz：`62 passed, 1 failed in 12.76s`。
- [INVESTIGATE] root 唯一失败是 package-independence 扫描一次性报告多个既有/本轮 `from geoviz import ...` facade 文件为 violation，与测试名“only geoviz facade”表面矛盾；先审计扫描器的 AST 规则和 import 环境，不计具体功能 strike。
- [NEXT] 定位 facade gate 的真实判定（疑似禁止顶层重依赖或模块缓存污染），用最小独立命令复现后修正架构旁路。
- [DIAG · facade gate attempt 2] 扫描器只维护显式公开符号 allowlist；补入 Task 27.2 的 analytics/directional/jobs 后，violations 从多文件收敛为 `map_edit_scene.py` 单项，即 Task 27.4 新 facade `validate_polygon_geometry` 尚未登记。focused：`1 failed, 10 passed`。
- [NEXT] 补齐最后一个公开 facade 符号后执行第三次 gate；若仍失败则严格触发 3-Strike RCA/策略切换。
- [GREEN · facade gate] 登记 `validate_polygon_geometry` 后第三次 package-independence gate 成功：`11 passed in 4.01s`；未触发 3-Strike。
- [NEXT] 重跑 Task 27.6 root 广域集合并同步 `task_plan.md` / `findings.md`，随后进入 Task 27.7 全量验证。
- [DONE · Task 27.6] engine application registry 统一保活 SEGY/synthetic worker，view cleanup 非阻塞取消，aboutToQuit 共享 deadline 收口。
- [REGRESSION · final] engine contour+SEGY `57 passed in 9.93s`；root contour/prep/seismic/viz/facade `63 passed in 11.50s`。
- [PWF SYNC] ISS-ASYNC-01 与 ISS-ARCH-01 关闭；Task 27.6 全项勾选，关键异步/预算/句柄不变量沉淀至 findings。
- [NEXT · Task 27.7] 执行 root/engine 全量 non-slow、compileall、diff-check；同时复核 ISS-AUDIT-01/ISS-STATE-01 是否还有未关闭路径。
- [FULL GATE · engine attempt 1] `1026 passed, 2 skipped, 134 deselected, 1 failed in 104.36s`；唯一失败为未触碰的 cross-well DTW 1k 性能阈值，实测 `1.061s < required 1.0s` 不成立。
- [FOCUSED · DTW attempt 2] 独立重跑仍为 `1 failed`，耗时 `1.045s`；确认不是全套资源争用。已连续 2 次，第三次失败将触发 3-Strike，当前先做实现/基准根因审计，禁止盲目重跑。
- [NEXT] 只读检查 DTW 实现与测试基准，判断是工作树路径错配、纯 Python O(NW) 热点或阈值噪声；形成最小性能修复后再进行第三次验证。
- [ROOT CAUSE · DTW] venv 确认加载当前 submodule；独立 benchmark 3 次约 1.00–1.07s。热点为 band 内逐 cell Python scalar DP，而非测试环境路径或一次性抖动。
- [GREEN · DTW] 将同一递推等价改写为 `cumsum + minimum.accumulate` 的 min-plus prefix scan，保留 compact matrix、回溯与 progress 语义。
- [TEST · attempt 3] 完整 DTW suite `10 passed in 1.56s`，性能门槛恢复；第三次验证成功，未触发 3-Strike。
- [NEXT] 重新执行 engine full gate，然后 root full gate。
- [FULL GATE · engine attempt 2] `1027 passed, 2 skipped, 134 deselected in 100.79s`；DTW 性能修复通过全量。
- [FULL GATE · root attempt 1] `991 passed, 4 skipped, 8 deselected, 2 failed in 95.87s`，无 QThread 销毁/teardown hang。失败为：(1) 150ms opacity 动画等待 250ms 后停在 0.999666；(2) review integration 仍硬编码警告 1，当前 QC 实际警告 3。
- [NEXT] 分别 focused 复现并审计：动画 finished 是否强制写 1.0；QC 规则/测试期望谁已陈旧。两项独立，不共用 strike 计数。
- [FIX · root failures] fade 增加 150ms identity-checked exact finalize；QC integration 期望更新为当前 6-rule 契约下缺 facies/wells/contours 共 3 warnings；SeismicHost 空体改 3³，消除 gradient warning。
- [FOCUSED · fade attempt 2] QC 已通过；fade 数值断言本身通过，但前一用例销毁 AppShell 后其无 context singleShot 仍调用已删除 DataPage，pytest-qt 记为 event-loop failure（`1 failed, 5 passed`）。这是 lifecycle 衍生问题，opacity bug 连续第 2 次未过。
- [NEXT] finalize slot 容忍 wrapper 已删除或改用带 QObject context 的 timer；第三次 focused 若失败立即触发 3-Strike RCA。
- [GREEN · fade attempt 3] deadline timer 改为 page-owned `QTimer`，新动画会停止旧 timer，页面删除自动销毁 timer；slot 另容忍 deleted wrapper。focused fade+review：`6 passed in 6.67s`，未触发 3-Strike。
- [NEXT] 重跑 root full gate，随后 compileall/diff-check。
- [FULL GATE · root attempt 2] 第二轮越过 50% 后停在 57%，超过节点 60s 且 pytest-timeout 无输出；精确 TERM PID 461413（exit 143），未见断言/QThread warning。禁止重复 quiet 全套。
- [LOCATE] collect 顺序显示 57% 边界落在 `test_prep_well_table_worker.py` 561–569，结合输出停在该组第 7 个点附近，首要嫌疑为 async generate/shutdown lifecycle 的顺序依赖，而不是后续 preview。
- [NEXT] 用前置 pipeline/prediction 子集 + prep 文件的 `-vv` 复现顺序，并启用 faulthandler；这是本次 root-gate hang 的第 1 次，未触发新 3-Strike。
- [DIAG] prep lifecycle 单文件 `9 passed in 2.20s`；按 collect 顺序加入紧邻的 pipeline/prediction 前置后 `25 passed in 2.34s`，无法复现 full-run 57% hang。
- [INFERENCE] 挂起依赖更早的全套累积状态，而非 prep 文件局部顺序；quiet 百分比只能定位区间，不能证明具体节点。下一策略改为全套 `-vv`（节点名可见）并用外层 deadline/必要时 faulthandler，而非第三次 quiet 猜测。
- [NEXT] 执行 root `-vv` 全量诊断门禁；若同一 lifecycle 节点再次挂起则计第 2 次并抓精确节点/栈。
- [FULL GATE · root final] 同一 non-slow collection 以 `-vv + faulthandler` 正常完成：`993 passed, 4 skipped, 8 deselected in 40.09s`；prep/preview/lifecycle 均逐节点通过，无 hang 或 Qt thread warning。
- [STATIC GATE] `python -m compileall -q paleo_workbench geo-viz-engine/packages`、root `git diff --check`、engine `git diff --check` 全部 exit 0。
- [AUDIT CLOSE] Project path containment/round-trip 已有底层与页面测试；atomic save timestamp、snapshot worker GUI commit 覆盖 ISS-STATE。ISS-AUDIT-01 / ISS-STATE-01 关闭。
- [COMPLETED · Phase 27] 所有 issue 关闭，Task 27.7 全项完成；用户未跟踪 `SCRATCH/` 与 5 个历史 plan 文件保持未触碰。
- [START · Phase 28] 用户要求修复全部 6 条 review。已读取 receiving-code-review / planning-with-files / brainstorming / TDD 规则并完成 session catchup。
- [VERIFY REVIEW] packaging 两条属实：父仓 3 个本轮文件 untracked，engine gitlink仍停在 `dc321a5d` 且 submodule dirty。
- [DESIGN] complex merge/split fail-closed；preview geometry-first；SEGY 统一 invalidation；preload guard-first；engine→parent 两级提交；clean-checkout 复验。
- [NEXT] 逐文件验证 4 条产品缺陷的实际调用链，先写 RED 测试。

### Phase 28 — Review 根因核验

- [DONE] 定位 merge/split 数据丢失路径：旧 ring API 在复合几何上发生降维，且删除命令会随后执行。
- [DONE] 定位预览数据丢失/崩溃路径：编辑器完整 `geometry` 被紧凑 `coordinates` 抢先覆盖。
- [DONE] 定位 SEGY stale-result 路径：非 path-backed 状态切换没有统一推进 load generation。
- [DONE] 定位预览额外 I/O：模式及已有 payload 守卫位于文件读取之后。
- [NEXT] 按 TDD 添加上述四类回归用例，并验证其在修复前失败。
- [DONE] 确认现有回归测试夹具与目标文件：map topology/preview、preview async、engine seismic workers，以及 root seismic host contract。
- [NEXT] 写入 RED 测试；首次 focused run 必须呈现 reviewer 所述失败路径。
- [DONE] 完成 engine SEGY 实现核验：确认可抽取现有 cleanup/load 中断逻辑为公开生命周期 API。
- [DONE] 确认 Thin Host 修复边界：移除 `_loader` 私有访问，空状态显式取消，volume/demo 由 engine 自身取消。
- [NEXT] 一次性加入 4 组 RED 回归测试并执行 focused gate。
- [RED · run 1] Root focused：出现 2 个产品契约失败后，预载测试的全局 `Path.stat` monkeypatch 触发 pytest INTERNALERROR；该 run 不可作为完整断言结果。
- [RED · command correction] Engine focused 因从父仓使用 `tests/test_seismic_workers.py` 路径而 collection error；尚未执行到 engine 用例。
- [STRIKE] Phase 28 修复后失败计数仍为 0；本次是预期 RED/测试夹具校正，不计实现自愈 strike。
- [NEXT] 修正测试隔离与 engine cwd，重新取得可信 RED 证据。
- [RED · root verified] `7 failed, 42 passed in 5.53s`；全部失败均为本轮预期产品契约，测试隔离已正确。
- [RED · engine env] 父仓 cwd collection 报 `ModuleNotFoundError: geoviz_seismic`；下一次改用 `geo-viz-engine/` cwd，不计实现 strike。
- [NEXT] 在 engine cwd 取得 stale SEGY RED，随后进入 GREEN 实现。
- [ENV] engine cwd + 系统 pytest 仍 collection error；已定位 engine 自带 `.venv/bin/pytest` 与 README 测试入口。
- [NEXT] 使用 engine `.venv/bin/pytest` 执行 stale-result RED；产品实现 strike 仍为 0。
- [ENV] `.venv/bin/pytest` 因旧绝对 shebang exit 127；已核对 Phase 27 日志，正确入口为 `.venv/bin/python -m pytest`。
- [NEXT] 用正确解释器入口执行 engine RED；环境探测不计产品 strike。
- [RED · engine verified] `.venv/bin/python -m pytest -q tests/test_seismic_workers.py` → `1 failed, 3 passed`，stale demo 覆盖契约确实失败。
- [GREEN · implementation] 已完成 complex geometry fail-closed、editor geometry-first、preload guard-first、engine SEGY 统一取消 API、panel empty 取消与 host 私有耦合移除。
- [NEXT] 执行 root + engine focused GREEN；若失败按同一缺陷累计 strike。
- [GREEN · root] `QT_QPA_PLATFORM=offscreen pytest -q ...` → `49 passed in 5.28s`。
- [GREEN · engine] `.venv/bin/python -m pytest -q tests/test_seismic_workers.py` → `4 passed in 0.77s`（仅既有 pytest config warning）。
- [STRIKE] Phase 28 产品修复失败计数：0。
- [NEXT] 扩展回归、静态检查、版本控制收口与 clean-checkout 测试。
- [STATIC] root/engine `git diff --check` 均 exit 0；本轮目标 diff 人工复核通过。
- [PACKAGING] 已确认仍需纳入 root 新模块 2 个 + seismic contract test 1 个，以及 engine 新 API/analytics/directional/tests；父仓 gitlink 尚未更新。
- [SCOPE] 无关 `SCRATCH/` 与 5 个既有 docs plan 继续保持未触碰/不纳入提交。
- [NEXT] 跑受影响扩展回归，再执行 engine→parent 两级提交。
- [FULL GATE · root] `1000 passed, 4 skipped, 8 deselected, 2 warnings in 47.81s`。
- [FULL GATE · engine] `1027 passed, 2 skipped, 134 deselected, 1 warning in 47.03s`。
- [STRIKE] Phase 28 产品修复失败计数保持 0；两套全量门禁全绿。
- [NEXT] 提交 engine，更新父仓 gitlink并提交 root；随后从提交态做 clean-checkout 导入/测试验证。
- [COMMIT · engine] `957cb3f5 fix(core): harden GIS jobs and seismic lifecycle`；staged diff-check exit 0，新增核心模块与测试均已纳入提交。
- [NEXT] 更新父仓 gitlink，精确排除 `SCRATCH/` 与 5 个 docs plan 后提交 root。
- [COMMIT · parent] `540decc fix(workbench): harden GIS state and async editors`；47 files，新增两个必需 worker/keeper 模块及 async seismic contract，gitlink 已更新。
- [SCOPE VERIFIED] staged name-status 未包含 `SCRATCH/` 或 5 个历史 docs plan。
- [NEXT] 从提交态创建隔离 worktree，初始化 submodule，验证 clean checkout 导入与 reviewer focused tests。
- [CLEAN CHECKOUT · attempt 1] parent/submodule 检出成功；import 脚本 expected-path 取值错误导致 AssertionError，非产品失败，trap 已清理临时 worktree。
- [STRIKE] Clean-checkout 产品失败计数：0；本次为验证夹具修正。
- [NEXT] 显式传入临时 checkout 路径，重跑 imports + reviewer focused tests。
- [CLEAN CHECKOUT · PASS] parent `540decc` + submodule `957cb3f5`：AppShell 构造/import 来源断言通过；root reviewer contracts `8 passed in 1.19s`；engine workers `4 passed in 0.75s`。
- [CLEANUP] 临时 worktree 已自动移除，`git worktree list` 仅剩主工作树。
- [GITLINK] `git ls-tree HEAD geo-viz-engine` 与 engine HEAD 均为 `957cb3f5f250daff68dfd7eec45a8d0ea05469b0`。
- [NEXT] 最终 compileall + diff-check，关闭 Phase 28 并提交 PWF 收尾记录。
- [STATIC FINAL] `python -m compileall -q paleo_workbench geo-viz-engine/geoviz geo-viz-engine/packages` + root/engine diff-check → exit 0。
- [COMPLETED · Phase 28] REV-PACK/ENGINE/GEOM/PREVIEW/SEGY/IO 全部关闭；全量、focused、clean-checkout、静态门禁均已通过。
- [NEXT] 提交 PWF 收尾记录，然后做提交态最终状态核验。
- [FINAL HARNESS NOTE] 合并 root+engine 单进程 pytest 因双方 `tests` package 同名导致 3 个 collection error；其后命令未启用 fail-fast，故末尾 exit 0 不可采信为测试结果。
- [FINAL ROOT FOCUSED] 恢复标准 root 命令 → reviewer contracts `8 passed in 1.03s`。
- [EVIDENCE] 最终采用隔离证据：root focused 8 pass；clean-checkout engine 4 pass；root full 1000 pass；engine full 1027 pass；compileall/diff-check exit 0。

### Phase 29 — PDF 预览加载失败

- [START] 用户报告 PDF 预览加载失败；按 systematic-debugging 只做根因调查，尚未修改产品代码。
- [ENV] Qt 6.11.1 的 QtPdf/QtPdfWidgets 均存在。
- [REPRO] 实际 PDF 路径加载成功：`Error.None_ / 248 pages / Ready`。
- [HYPOTHESIS] bytes 预载走 `load(QIODevice)` 返回 `None`，被 widget 当作 Error，导致假失败。
- [NEXT] 最小脚本确认 QBuffer load 后 document 实际 Ready 且 widget `_load_failed=True`。
- [ROOT CAUSE CONFIRMED] QBuffer document：`return=None, Ready, Error.None_, 248 pages`；widget：`_load_failed=True, 0 / 0`。
- [PAUSED] 当前请求按诊断处理，未修改产品代码；若用户要求修复，进入 TDD RED→GREEN。
- [APPROVED] 用户批准方案 A；设计/实施计划因 PWF 唯一记忆约束写入 `task_plan.md`，未新增 docs 文件。
- [PLAN] 单原子 inline TDD：真实 QBuffer RED → status-driven GREEN → focused/full gates。
- [WORKTREE] `.worktrees/pdf-preview-fix` / `fix/pdf-preview-status` 创建成功，submodule 检出 `957cb3f5`。
- [BASELINE attempt 1] quiet preview suite 12 dots 后 >2m 无进展，精确 PID TERM，exit 143。
- [BASELINE verified] `pytest tests/test_preview_async.py -vv --timeout=30 --maxfail=1` → `30 passed in 6.04s`。
- [STRIKE] ISS-PDF-01 产品修复失败计数：0；quiet-run stall 为基线 harness 现象。
- [NEXT] 写真实 QBuffer widget RED 用例并验证预期失败。
- [RED] `test_pdf_widget_loads_preloaded_bytes_without_reopening_path` → expected FAIL：`assert True is False` at `widget._load_failed`；document 已成功加载 1 页。
- [STRIKE] 预期 RED，不计实现 strike；ISS-PDF-01 产品修复失败计数仍为 0。
- [NEXT] 实现 status-driven load completion，并兼容现有 fake-document tests。
- [GREEN] 新增 `_load_pending`、`_finish_document_load()` 与 `statusChanged` 收敛；未回退到 GUI path I/O。
- [GREEN focused] 真实 QBuffer-only 回归 → `1 passed in 0.55s`。
- [STRIKE] 产品修复失败计数保持 0。
- [NEXT] 运行 preview widget + data reader + preview async 回归，修复任何契约兼容问题。
- [FOCUSED attempt 1] quiet 三文件 suite 在大量通过点后 teardown stall，精确 PID TERM，exit 143；未出现失败节点。
- [FOCUSED verified] 同一三文件 suite `-vv --timeout=30` → `82 passed in 11.76s`。
- [STRIKE] 产品修复失败计数保持 0；两次 quiet stall 均由节点级重跑排除产品失败。
- [NEXT] 用实际 44.6 MiB / 248 页 PDF 验证 widget bytes 预览，再跑 root full gate。
- [ACTUAL PDF] 44.6 MiB / 248 pages → widget `failed=False, pending=False, Ready, Error.None_, 1 / 248`，exit 0。
- [FULL attempt 1] quiet non-slow 运行到 57% 后 >2m 无输出，精确 PID TERM，exit 143；无失败节点。
- [STRIKE] full quiet stall 不计产品 strike；实现测试失败计数仍为 0。
- [NEXT] 使用 full `-vv --timeout=60` 获取节点级门禁。
- [FULL attempt 2] `-vv` 定位停顿节点为既有 `test_stress_s3_rapid_select`，精确 PID TERM，exit 143。
- [ISOLATION] 同节点全新进程 → `1 passed in 0.51s`，排除 PDF 回归与节点确定性失败。
- [STRIKE] ISS-PDF-01 产品失败计数仍为 0；full 单进程 stall 作为既有 Qt 全局状态问题单独记录。
- [NEXT] 按文件分段运行 non-slow collection，汇总精确 pass/skip/deselect 证据。
- [SEGMENT A] lexicographic `< test_datapage_stress.py` → `210 passed in 23.14s`。
- [SEGMENT B] `test_datapage_stress.py <= file < test_map*` → `174 passed, 8 deselected in 15.68s`。
- [NEXT] 运行 map→preview 与 preview→末尾两个独立区间，随后汇总 collection 数量。
- [SEGMENT C] `test_map* <= file < test_preview*` → `188 passed, 4 skipped in 18.65s`。
- [SEGMENT D] `file >= test_preview*` → `429 passed in 42.91s`。
- [FULL SEGMENTED TOTAL] `1001 passed, 4 skipped, 8 deselected`；collection 数量闭合，无失败。
- [NEXT] compileall/diff-check、审查 diff，关闭 Phase 29。
- [STATIC] `python -m compileall -q paleo_workbench` 与 `git diff --check` exit 0；diff 仅含 PDF widget/test + 三份 PWF。
- [SELF REVIEW] 增补 `Loading → Ready` fake-document contract test，待执行验证。
- [NEXT] 运行双 PDF contract 与 focused suite；确认后关闭 Phase 29。
- [CONTRACT] immediate Ready + Loading→Ready → `2 passed in 0.27s`。
- [WIDGET REGRESSION] `tests/test_preview_widgets.py` → `16 passed in 1.33s`。
- [VERIFIED] Phase 29 所有代码/测试/静态门禁完成；进入 finishing-development-branch 提交与集成流程。
- [IMPLEMENTED] ISS-PDF-01 fixed；分支 `fix/pdf-preview-status` 准备提交并等待 finishing workflow 集成选择。
