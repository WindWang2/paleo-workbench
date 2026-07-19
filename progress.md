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
- [MERGED] 用户选择 option 1；`main` fast-forward 到 `cf2676e`，无 pull/push。
- [MERGED FOCUSED] preview widgets + reader + async → `83 passed in 6.89s`。
- [MERGED ACTUAL PDF] 44,610,769 bytes / 248 pages → `Ready, Error.None_, 1 / 248`，exit 0。
- [NEXT] 移除自建 worktree、删除已合并分支，提交最终 PWF 收尾。
- [CLEANUP] worktree submodule deinit；确认无未提交内容后移除 `.worktrees/pdf-preview-fix`；已合并分支 `fix/pdf-preview-status` 以 `branch -d` 删除。
- [WORKTREE FINAL] `git worktree list` 仅剩 `/home/kevin/projects/paleo_project cf2676e [main]`。
- [COMPLETED · Phase 29] PDF QIODevice 预览误判已修复、合并、复验并清理隔离分支。

### Phase 30 — 重复实现审计与收敛

- [START] 用户要求重构当前项目、减少重复功能开发；启用 brainstorming + planning-with-files 设计门禁。
- [CONTEXT] session catchup、三份 PWF、git 状态与近期提交已恢复；无待提交产品改动，用户既存未跟踪资产保持不动。
- [AUDIT 1] 完成 Python 文件规模、核心符号和 QThread 生命周期入口扫描；建立 thread / algorithm / preview / geometry 四类候选地图。
- [PWF GATE] 两次只读检索后立即同步 task_plan/findings/progress；尚未修改业务代码、尚未执行测试。
- [ERROR] 首次 PWF patch 使用了错误的 findings 尾部锚点，apply_patch 原子失败且无文件改变；读取精确尾部后拆分上下文重试成功。
- [NEXT] 每次只问一个设计问题：先确认第一批重构优先范围，再对选定范围给出 2–3 个方案与兼容策略。
- [DECISION] 用户选择选项 1：第一批聚焦线程生命周期统一。
- [AUDIT 2] 细读 ThreadKeeper、Data/Preparation/Mapping/Preview 线程实现、engine 独立包约束及现有测试入口。
- [BOUNDARY] 通用层负责 owned job 的启动/取消/安全回收；页面保留业务结果提交；Preview 保留 latest-only 调度；engine 不得反向依赖 workbench。
- [PWF GATE] 两次源码/测试检索后同步三份 PWF；仍未修改业务代码、未执行测试。
- [NEXT] 确认第一批是否仅收敛 workbench，或同时设计 engine 的同构生命周期 API。
- [DECISION] 用户选择 Workbench 优先（选项 1）；engine 本批只作为独立契约边界，不进入产品改动范围。
- [NEXT] 提交 workbench 内三种收敛方案、推荐架构与分批迁移顺序，等待设计批准。
- [APPROVED] 用户批准方案 A：Workbench 内引入 `OwnedWorkerJob`，保留页面业务与 Preview latest-only 语义。
- [SKILLS] 已读取 writing-plans、TDD、using-git-worktrees 完整规则；用户三文件 PWF 约束覆盖默认 docs plan 路径。
- [PLAN] Task 30.1–30.6 已写入 task_plan：基础句柄→contour→factor→Data→Preview transport→全量门禁。
- [SELF REVIEW] 范围、API 一致性、TDD 节点、YAGNI 与 placeholder 检查通过。
- [NEXT] 按 worktree 技能先取得用户对隔离工作树的许可，再创建分支并执行基线测试。
- [CONSENT] 用户允许提交 PWF 计划并创建隔离工作树。
- [COMMIT] main `13288e4 docs(pwf): plan worker lifecycle deduplication`，仅包含三份 PWF；既存未跟踪资产未纳入。
- [WORKTREE] 创建 `.worktrees/refactor-owned-worker-job` / `refactor/owned-worker-job`。
- [ENV ERROR] 远端 submodule 不含锁定的 `957cb3f5`，首次 init 失败；从主工作区本地 engine 仓库精确 fetch 后 checkout 成功，worktree 状态恢复干净。
- [NEXT] 执行 Preparation/Mapping/Data/Preview 受影响测试基线；若失败先报告，不进入实现。
- [BASELINE COMMAND ERROR] 计划中的新增文件 `tests/test_mapping_contour_async.py` 被误当作现有基线节点，pytest exit 4 / no tests ran；已把计划标为 Create，并从 baseline 命令移除，不计产品 strike。
- [PWF GATE] 一次测试命令 + 一次测试入口检索后同步 task_plan/progress。
- [NEXT] 使用现有 contour/mapping 页面测试文件重跑基线。
- [BASELINE attempt 1] 真实 8 文件组合测试通过 60% 并继续约 12 项后长期无输出；精确 TERM PID 741864，exit 143，无失败节点。
- [STRIKE] Phase 30 产品失败计数 0；quiet-run stall 作为既有 harness 生命周期问题，不计实现 strike。
- [NEXT] 将 baseline 分成四个独立 pytest 进程，分别取得可采信的 pass 结果。
- [BASELINE A] Preparation/Mapping → `23 passed in 5.71s`。
- [BASELINE B] DataPage → `51 passed, 1 warning in 7.19s`；warning 为既有 lasio/pkg_resources deprecation。
- [PWF GATE] 连续两次测试执行后立即同步 progress。
- [NEXT] 独立运行 Preview async/cache 与 DataPage stress 基线。
- [BASELINE C] Preview async/cache → `40 passed, 1 warning in 6.59s`。
- [BASELINE D] DataPage stress → `5 passed in 2.96s`。
- [BASELINE COMPLETE] 四个独立进程合计 `119 passed`；Phase 30 产品失败计数 0，可以进入 TDD。
- [PWF GATE] 连续两次测试执行后立即同步 progress。
- [NEXT] Task 30.1 cycle 1：新增 OwnedWorkerJob off-GUI + normal-release RED 测试。
- [T30.1 RED 1] 新增真实 QObject worker 契约；focused run → `1 failed`，精确原因为 `ModuleNotFoundError: paleo_workbench.ui.owned_worker_job`。
- [STRIKE] 预期 RED，不计产品实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试代码 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 实现最小 OwnedWorkerJob：创建线程、off-GUI run、terminal direct quit、identity relay 与正常释放。
- [T30.1 GREEN 1] 最小 OwnedWorkerJob 实现完成；focused → `1 passed in 0.29s`。
- [PWF GATE] 一次产品代码 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] Task 30.1 cycle 2：先写 blocked shutdown/cancel/disconnect/keeper RED，再扩展 API。
- [T30.1 RED 2] blocked worker 契约 focused → `1 failed`；精确原因为 start 不支持 `result_connections`，尚未实现 cancel/target/shutdown。
- [STRIKE] 预期 RED，不计实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 最小实现 result connection registry、cancel/target、有限 wait 与超时 keeper adopt。
- [T30.1 GREEN 2] result registry、cancel/target、有限 wait、超时 keeper adopt 完成；foundation suite → `2 passed in 0.31s`。
- [PWF GATE] 一次产品 mutation + 一次 pytest 后立即同步 task_plan/progress。
- [NEXT] Task 30.2：写 Preparation/Mapping contour 使用统一 handle 的 RED 页面契约。
- [T30.2 RED 1] 新增共享 contour lifecycle 架构契约；focused → `1 failed`，PreparationPage 缺少 `_contour_job` 且仍有旧 token 字段。
- [STRIKE] 预期 RED，不计实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 同步迁移 Preparation/Mapping contour 到 OwnedWorkerJob，保留页面专属业务槽。
- [AUDIT] 确认 Mapping 的 QThread/Qt/keeper 仅用于 contour，可全部移除；Preparation 仍因 factor job 暂时保留这些导入。
- [PWF VIEW GATE] 两次源码检索后同步 findings/progress；产品迁移尚未开始。
- [T30.2 GREEN] Preparation/Mapping contour 同构迁移完成；架构 + contour UI → `7 passed in 3.77s`。
- [DEDUP] 两页删除 8 个裸生命周期字段及两套手工 wait/disconnect/adopt；专属 success/failure/commit 槽保持不变。
- [PWF GATE] 一次产品 mutation + 一次 pytest 后立即同步 task_plan/progress。
- [NEXT] Task 30.3：Preparation factor job 结构 RED→handle 迁移。
- [T30.3 RED] factor ownership 契约 → `1 failed`；PreparationPage 尚无 `_prepare_job`，仍暴露旧 token 字段。
- [STRIKE] 预期 RED，不计实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 迁移 factor worker，并保持 snapshot stale/shutdown 既有回归语义。
- [T30.3 GREEN] Preparation factor job 迁移完成；prep/integration/contour contracts → `20 passed in 2.71s`。
- [DEDUP] PreparationPage 不再直接创建 QThread，factor/contour 统一使用两个 OwnedWorkerJob 实例。
- [PWF GATE] 一次产品 mutation + 一次 pytest 后立即同步 task_plan/progress。
- [NEXT] Task 30.4：DataPage import ownership RED→单 handle 迁移。
- [T30.4 RED] Data import ownership 契约 → `1 failed`；DataPage 尚无 `_import_job`，仍使用 `_import_jobs`。
- [STRIKE] 预期 RED，不计实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 以单 OwnedWorkerJob 替代 import tuple list/sender lookup/manual wait，保留 queued GUI commit。
- [T30.4 GREEN] DataPage import handle 迁移完成；完整 data page → `52 passed, 1 warning in 3.57s`。
- [DEDUP] 删除 `_import_jobs`、sender tuple 查找和两套手工 cleanup；import business/status 逻辑不变。
- [PWF GATE] 一次产品 mutation + 一次 pytest 后立即同步 task_plan/progress。
- [NEXT] Task 30.5：PreviewController transport ownership RED→handle 迁移。
- [T30.5 RED] Preview transport ownership 契约 → `1 failed`；controller 尚无 `_active_job`。
- [STRIKE] 预期 RED，不计实现 strike；Phase 30 实现失败计数仍为 0。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] 用 OwnedWorkerJob 替换 `_jobs/_active/_thread_stopped`，保持 pending/generation/cache/pump 顺序。
- [T30.5 IMPLEMENT] PreviewController 已迁移 `_active_job`；shutdown 委托统一 handle，released 后仍 singleShot pump pending。
- [TEST CONTRACT] Preview/Stress/GeoViz lifecycle 测试移除旧 `_jobs/_active` tuple 依赖，统一读取 `_active_job.thread`；no-terminate 契约改为检查 OwnedWorkerJob.shutdown。
- [SELF REVIEW] 删除 `_start_job` 中残留的无用 `QThread(self)`，未保留兼容重复状态。
- [PWF GATE] 连续两次代码/test mutation 后立即同步 progress；尚未运行 GREEN。
- [NEXT] 运行 Preview async/cache/stress/lifecycle GREEN；失败按 Task 30.5 累计 strike。
- [T30.5 GREEN attempt 1] `48 passed, 4 failed`；四项均为 page teardown 捕获 Qt event-loop exception：lambda 对已删除 handle 发 signal。
- [STRIKE 1] Task 30.5 实现失败计数 1/3；根因已定位，非重复机械修改。
- [FIX] thread.finished relay 改为 OwnedWorkerJob bound slot + QueuedConnection；receiver 删除时 Qt 自动断连，slot 以 sender identity 清理。
- [PWF GATE] 一次 pytest + 一次产品修复后立即同步 findings/progress。
- [NEXT] 重跑同一 Preview 五文件 gate，验证 teardown 与 latest-only 全绿。
- [T30.5 GREEN attempt 2] Preview async/cache/stress/lifecycle/visualization → `52 passed, 1 warning in 6.27s`。
- [CROSS MODULE] foundation + Preparation/Mapping/Data → `74 passed, 1 warning in 4.54s`。
- [FOCUSED TOTAL] 两个独立进程合计 `126 passed`；Task 30.5 strike 保持 1/3，无第二次失败。
- [PWF GATE] 连续两次 pytest 后立即同步 task_plan/progress。
- [NEXT] Task 30.6：静态去重审查、identity 回归、compile/diff/full gates。
- [STATIC DEDUP] 四个目标页面的线程原语检索为 0；仅 `owned_worker_job.py` 保留 QThread/interrupt/wait/keeper。
- [DIFF CHECK] `git diff --check` exit 0；tracked diff 268 insertions / 423 deletions，另有 3 个预期新增文件。
- [PWF VIEW GATE] 连续两次源码/diff 检索后同步 findings/progress。
- [NEXT] 补齐 detached-old-vs-new identity 回归并校正 `is_running` ownership 语义。
- [T30.1 RED 3] release-window 契约 → `1 failed`：thread 已停止但 queued release 未处理时 is_running 错误返回 false；old-detached identity 回归 `1 passed`。
- [STRIKE] 预期 RED，不计实现 strike；Task 30.5 strike 仍为 1/3。
- [PWF GATE] 一次测试 mutation + 一次 pytest 后立即同步 progress。
- [NEXT] `is_running` 改为 ownership 状态（thread 引用存在），随后运行完整 foundation suite。
- [T30.1 GREEN 3] `is_running` 改为 handle ownership；foundation 完整 suite → `4 passed in 0.18s`。
- [PWF GATE] 一次产品 mutation + 一次 pytest 后立即同步 task_plan/progress。
- [NEXT] compileall/diff-check + 受影响总回归，再执行 segmented full root gate。
- [VERIFY STATIC] `python -m compileall -q paleo_workbench` + `git diff --check` → exit 0。
- [VERIFY AFFECTED A] Foundation/Preparation/Mapping/Data → `76 passed, 1 warning in 4.56s`。
- [PWF GATE] 连续两次验证执行后立即同步 progress。
- [NEXT] 新鲜 Preview 52 项，再执行 root non-slow full/segmented gate。
- [VERIFY AFFECTED B] Preview async/cache/stress/lifecycle/visualization → `52 passed, 1 warning in 6.25s`。
- [FULL ROOT] standard non-slow → `1010 passed, 4 skipped, 8 deselected, 2 warnings in 34.84s`，exit 0；本次未复现 stall。
- [PWF GATE] 连续两次 pytest 后立即同步 task_plan/progress。
- [NEXT] 计划逐项复核、clean-checkout focused、代码审查、分支提交与集成。
- [COMMIT] `f86defc refactor(ui): centralize worker lifecycle`；17 files，3 个新增必需文件已纳入，分支提交后 clean。
- [REVIEW] 按 requesting-code-review 技能启动只读独立 reviewer，范围 `13288e4..f86defc`。
- [CLEAN CHECKOUT attempt 1] harness 失败：local file transport blocked + Python cwd 错误 + no fail-fast；产品节点未可信执行，不计产品 strike。
- [CLEANUP] 精确移除 `/tmp/tmp.2UCh6uTEuK/checkout`；worktree list 恢复为 main + feature 两项。
- [NEXT] 使用允许本地 file transport、显式 PYTHONPATH 与 fail-fast 重跑 clean-checkout。
- [CLEAN CHECKOUT product PASS] parent `f86defc` + engine `957cb3f5`：import `AppShell OwnedWorkerJob`；focused `8 passed in 1.66s`；status clean。
- [HARNESS CLEANUP] 普通 remove 因 submodule metadata exit 128；EXIT trap exact force-remove 成功。独立 `git worktree list` 与 path absence 检查 exit 0，仅 main + feature worktree。
- [NEXT] 等待独立 code review；处理 Critical/Important 后重验，或在无阻塞问题时提交 PWF 收尾并集成。
- [REVIEW RESULT] 精简独立 reviewer：无 Critical/Important；1 个 RuntimeError defensive-path Minor，评估后接受，未改代码。
- [REVIEW HARNESS] 首个 reviewer 两次超时后中断；第二个只读 reviewer按要求不跑测试并返回有效分级结论。
- [IMPLEMENTED · ISS-DEDUP-THREAD-01] Workbench thread lifecycle batch 完成；算法/preview dispatch/geometry/large-module issues 保留为 Phase 30 后续批次。
- [NEXT] 提交纯 PWF 收尾，按 finishing-development-branch 菜单等待用户选择 merge/PR/keep/discard。
- [INTEGRATE] 用户选择 option 1；main `git pull --ff-only` already up to date，随后 fast-forward 到 `e1aa52a`。
- [MERGED FULL attempt 1] standard non-slow 在 15% pytest-qt widget teardown 原生 segfault，exit 139；记合并态验证 strike 1/3，暂停 cleanup。
- [ISOLATION] `tests/test_data_page.py` 独立进程 → `52 passed, 1 warning in 3.29s`，排除该文件确定性失败。
- [PWF GATE] 一次 full 失败 + 一次 isolated pytest 后立即同步 findings/progress。
- [NEXT] 用四个独立进程跑完整 collection，验证合并提交并闭合 pass/skip/deselect 数量。
- [MERGED SEGMENT A] files `< test_datapage_stress.py` → `211 passed, 1 warning in 9.21s`。
- [MERGED SEGMENT B] `test_datapage_stress.py <= file < test_map*` → `174 passed, 8 deselected, 1 warning in 6.64s`。
- [PWF GATE] 连续两次 pytest 后立即同步 progress。
- [NEXT] 运行 map→preview 与 preview→末尾两个独立进程，汇总 collection 数量。
- [MERGED SEGMENT C] `test_map* <= file < test_preview*` → `194 passed, 4 skipped in 7.56s`。
- [MERGED SEGMENT D] `file >= test_preview*` → `431 passed, 2 warnings in 18.20s`。
- [MERGED SEGMENTED TOTAL] `1010 passed, 4 skipped, 8 deselected`，数量与 feature full 精确一致。
- [PWF GATE] 连续两次 pytest 后立即同步 findings/progress。
- [NEXT] main compileall/diff-check，随后移除自建 worktree并删除已合并分支。
- [MERGED STATIC] main `python -m compileall -q paleo_workbench` + `git diff --check` → exit 0。
- [CLEANUP attempt 1] 普通 worktree remove 因 submodule metadata 被 Git 拒绝；未删除内容。
- [CLEANUP PASS] 已确认 feature worktree clean 后精确 force-remove；`git branch -d refactor/owned-worker-job` 成功。
- [WORKTREE FINAL] `git worktree list` 仅剩 `/home/kevin/projects/paleo_project e1aa52a [main]`。
- [COMPLETED · ISS-DEDUP-THREAD-01] Workbench 线程生命周期去重已实现、审查、合并、复验并清理；Phase 30 后续保留算法/预览分派/几何/大模块批次。
- [MANUAL RUN] 用户要求启动应用体验；`python -m paleo_workbench.main` 已在图形会话启动并保持运行（PTY session 24941）。启动无异常退出；仅见 FFmpeg backend 与 OpenGL ES 3.2 compatibility warning。
- [START · Phase 31] 用户通过 `/brainstorm` 要求设计项目文件、数据页、制备页与编图页之间的数据读入/输出关联；已完整读取 brainstorming 与 planning-with-files 技能说明。
- [PWF SYNC] 已建立 `ISS-DFLOW-01`～`ISS-DFLOW-05` 审计清单与设计门禁；满足连续 2 次查看/检索后的 PWF 同步要求，下一步沿真实模型和调用链审计。
- [AUDIT · Phase 31] 已完成模型、项目 I/O、数据页、制备页、编图页与 AppShell 状态分发的第一轮调用链检索；确认共享 live `ProjectDocument` 与现有 lineage 骨架。
- [PWF SYNC] 已记录端到端数据图和核心缺口：页面信号能刷新内存视图，但稳定资产登记、派生版本失效、统一 dirty/commit 与输出回流尚缺集中契约；本轮未执行测试、未改业务代码。
- [DECISION · Phase 31] 用户确认 `DEC-DFLOW-01`：采用 `ProjectDocument` 单一事实源、页面暂存、确认提交的事务模式。
- [SCOPE · Phase 31] 用户明确制备页需面向多种单因素图分别管理；已新增 `DEC-PREP-01/02`，下一步审计现有因素类型与页面控件后确认因素目录模式。
- [AUDIT · Phase 31] 已核对制备 UI、默认因素、插值批处理及相关测试：当前虽能批量生成多个 `FactorMapTask`，但方法、井表与 QC 仍以全局/首项为中心。
- [PWF SYNC] 已记录制备页四项结构缺口：缺因素级选择与配置、缺因素级数据绑定、缺因素级 QC、缺派生成果向数据页登记；本轮未运行测试、未修改业务代码。
- [DECISION · Phase 31] 用户确认 `DEC-PREP-02`：制备因素采用标准模板与自定义因素并存的混合目录。
- [PWF SYNC] 已记录模板/任务分层要求；下一步确认制备输入与数据页项目资产的绑定边界，本轮未执行测试、未修改业务代码。
- [DECISION · Phase 31] 用户确认 `DEC-PREP-03`：制备页外部文件先自动登记为项目资产，任务只绑定资源 ID 与字段映射。
- [PWF SYNC] 已收敛制备输入路径边界及 Worker 快照要求；下一步确认重算版本策略，本轮未执行测试、未修改业务代码。
- [DECISION · Phase 31] 用户确认 `DEC-PREP-04`：单因素重算保留不可变成果版本，编图引用固定版本并提示可更新。
- [DESIGN · Phase 31] 已形成三种整体架构路线 A/B/C，推荐“项目资产图 + 不可变成果 + 统一提交服务”；等待用户确认后进入分段设计评审。
- [DECISION · Phase 31] 用户确认架构路线 A：项目资产图、不变成果版本、统一提交服务和薄页面宿主。
- [DESIGN · Phase 31] 已形成 `DES-ARCH-01` 总体架构提案并写入 PWF，等待用户逐段确认；本轮未执行测试、未修改业务代码。
- [APPROVAL · Phase 31] 用户确认 `DES-ARCH-01` 总体架构与职责边界。
- [DESIGN · Phase 31] 已形成 `DES-PREP-01` 多因素制备页提案，覆盖因素级导航、输入/QC/参数、异步试算、待采用结果和批量部分成功；等待用户确认。
- [START · Phase 32] 用户通过 `/goal` 要求实现覆盖所有预览格式的统一设置面板，并授权采用推荐默认、无需询问、持续执行至完成。
- [GOAL] 已创建持续目标；已读取 brainstorming 与 planning-with-files 规则，自动批准“强类型统一配置 + 用户级 QSettings + generation 重载”设计基线。
- [PWF SYNC] 已建立 `ISS-PREVSET-01`～`ISS-PREVSET-06` 审计、TDD、实现与验证清单；当前未修改业务代码、未执行测试。
- [METHOD · Phase 32] 已读取 writing-plans 与 test-driven-development；实现计划将按用户约束继续写入根 `task_plan.md`，业务实现严格执行 RED→GREEN→REFACTOR。
- [PWF SYNC] 已记录自动批准设计与 TDD 门禁；下一步盘点预览代码地图和现有测试，本轮仍未修改业务代码、未执行测试。
- [AUDIT · Phase 32] 已盘点 PreviewMode、Provider、ReaderPanel、异步控制器、内存缓存与 DataWorkspace；确认设置必须贯穿内容生成、缓存身份和当前请求重载。
- [PWF SYNC] 已记录第一轮文件边界与缓存风险；下一步审计 PDF/图像/表格/专业 Host 的可调入口，本轮未执行测试、未改业务代码。
- [AUDIT · Phase 32] 已完成普通 widgets、PDF/图片/GeoTIFF/JSON/媒体、LocalVisualizationProvider、GeoViz Host、磁盘缓存与 DataPage 重载入口审计。
- [PLAN · Phase 32] 已锁定推荐默认字段及六个 TDD 原子任务；下一步确认现有 QSettings/PreviewOptions API 后开始 `T-PREVSET-01` RED。
- [AUDIT · Phase 32] 已确认无既有 QSettings namespace，并读取 geo-viz-engine `PreviewOptions` 精确默认/API；未发现需要修改 engine contracts 的缺口。
- [PWF SYNC] 已锁定 PreviewSettings/Store/Provider/Cache/Controller/Panel/Reader 接口及竞态规避方案；下一步补审 fallback 格式后进入第一个 RED。
- [AUDIT · Phase 32] 已完成 fallback preview 与现有测试扩展点审计；确认安全预算保持硬编码，显示条数接入统一设置。
- [PLAN REFINEMENT] 为兼容既有 `preview(asset)` 子类，Provider settings 注入改为 `with_settings()` 快照浅拷贝；下一步进入 `T-PREVSET-01` RED。
- [RED · T-PREVSET-01] 新增推荐默认值契约测试；`QT_QPA_PLATFORM=offscreen pytest -q tests/test_preview_settings.py` 返回 exit 2，唯一原因是目标模块不存在，符合预期。
- [PWF SYNC] 已满足测试文件 Mutation + RED 测试后的 2-Action 门禁；下一步创建最小 `PreviewSettings` 使默认测试转绿。
- [GREEN · T-PREVSET-01] 创建 `preview_settings.py` 最小 frozen `PreviewSettings`；定向测试 `1 passed in 0.11s`。
- [PWF SYNC] 已满足业务模块 Mutation + GREEN 测试后的 2-Action 门禁；下一步为校验/指纹/Store/GeoViz options 编写下一组 RED。
- [RED · T-PREVSET-01] 扩展配置契约测试；定向 pytest exit 2，唯一收集错误为 `PreviewSettingsStore` 尚未实现。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的 2-Action 门禁；下一步实现完整 PreviewSettings 契约与 Store。
- [GREEN · T-PREVSET-01] 完成 `PreviewSettings` 与 `PreviewSettingsStore`；定向测试 `5 passed in 0.13s`。
- [PWF ERROR] 首次同步因 task_plan 清单锚点未匹配失败；已用 `rg` 定位并改用精确锚点，无业务影响。
- [PWF SYNC] 已满足生产模块 Mutation + GREEN 测试后的 2-Action 门禁；下一步为 Provider/fallback 内容设置编写 RED。
- [AUDIT · T-PREVSET-02] 已定位 Provider 所有固定上限消费点，并确认大 JSON 当前存在整文件读取 + 任意字节截断解析缺陷。
- [PWF SYNC] 已将 JSON 超限安全提示纳入 Provider 设置任务；下一步编写文本/表格/JSON/GeoViz Provider RED。
- [RED · T-PREVSET-02] 新增 Provider 内容设置契约；定向结果 `5 failed, 5 passed`，失败根因统一为 `PreviewProvider.with_settings` 尚未实现。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的 2-Action 门禁；下一步一次性实现已覆盖的 Provider/fallback 最小行为。
- [GREEN · T-PREVSET-02] 修改 `preview_provider.py`、`geoviz_preview_provider.py`、`fallback_preview.py`；域测试 `69 passed, 1 warning in 1.23s`。
- [PWF ERROR] 第二次组合同步因 Issue 文本锚点未匹配失败；已更换为“精确任务行 + 追加日志”策略，不再尝试同一锚点。
- [PWF SYNC] 已满足 Provider Mutation + GREEN 测试后的 2-Action 门禁；下一步为 cache fingerprint、disk options 与 controller generation 编写 RED。
- [RED · T-PREVSET-03] 新增内存/磁盘 cache 隔离与运行中设置切换契约；定向 `3 failed, 10 passed`，失败均为目标接口缺失。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的 2-Action 门禁；下一步实现 cache/disk/controller settings snapshot 链路。
- [FAIL-1 · T-PREVSET-03] 实现 cache fingerprint、disk options、Controller generation/settings snapshot 后运行组合域；输出显示 2 failed，随后 Qt teardown segfault，exit 139。
- [PWF SYNC] 已记录第 1 次失败并更换为“无 async 断言 → async 节点隔离”策略；下一步先提取确定功能失败，不重复崩溃命令。
- [SEGMENT GREEN · T-PREVSET-03] settings/cache/disk `36 passed`；新增 Controller settings 切换节点 `1 passed`，均 exit 0。
- [PWF SYNC] 已满足连续 2 次测试后的门禁；下一步仅收集/运行 async 失败节点，定位兼容断言并规避整组 teardown 崩溃。
- [FAIL DETAIL · T-PREVSET-03] async `--maxfail=2` 得到 `2 failed, 17 passed`；均为默认 cache key 兼容问题，无线程断言失败。
- [FIX · T-PREVSET-03] `make_preview_cache_key(asset)` 省略设置参数时改用推荐默认 fingerprint，与默认 Controller 保持一致。
- [PWF SYNC] 已满足 async 失败测试 + cache Mutation 后的 2-Action 门禁；下一步只复测两个失败节点。
- [GREEN · T-PREVSET-03] 两个 async cache 兼容失败节点复测 `2 passed in 0.43s`。
- [TEST MAP] 收集 `tests/test_preview_async.py` 共31项；下一步按前16/后15分段验证，避免既有 offscreen teardown 累积崩溃。
- [PWF SYNC] 已满足复测 + collection 后的 2-Action 门禁。
- [GREEN · T-PREVSET-03] async 分段 A `14 passed, 17 deselected`；分段 B `17 passed, 14 deselected`，两段完整覆盖31项。
- [PWF SYNC] 已满足连续2次测试后的门禁；cache/settings链路阶段完成，下一步 `T-PREVSET-04` 设置面板 RED。
- [RED · T-PREVSET-04] 新增 `tests/test_preview_settings_panel.py`；定向 exit 2，唯一错误为面板模块不存在。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的2-Action门禁；下一步实现类别栈、全部设置控件、应用/默认行为。
- [FAIL-1 · T-PREVSET-04] 创建完整面板后定向 `16 failed`；统一根因为样式 token `BG_PANEL` 不存在，无多重逻辑失败。
- [PWF SYNC] 已满足面板 Mutation + 第1次失败测试后的2-Action门禁；下一步定点替换为既有 `BG_SIDEBAR` 后复测。
- [GREEN · T-PREVSET-04] 修正设计 token 后面板定向 `16 passed in 0.24s`。
- [PWF SYNC] 已满足样式 Mutation + GREEN 测试后的2-Action门禁；下一步 `T-PREVSET-05` Widgets/Reader显示设置 RED。
- [RED · T-PREVSET-05] 新增 Widgets/Reader 显示设置契约；定向 `3 failed`，失败为目标接口缺失。
- [GREEN · T-PREVSET-05] `preview_widgets.py` 与 `data_reader_panel.py` 完成显示设置应用、设置面板嵌入及 Provider 快照更新；定向 `3 passed in 0.81s`。
- [PWF SYNC] 已满足 Widgets/Reader Mutation + 定向测试后的2-Action门禁；下一步进入 `T-PREVSET-06` DataPage信号接线 RED。
- [RED · T-PREVSET-06] 新增 DataPage 设置变更失效旧 generation 并重载当前资产的契约；定向 `1 failed`，Controller仍保持旧设置，符合接线缺失预期。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的2-Action门禁；下一步实现 DataPage 最小信号接线。
- [GREEN · T-PREVSET-06] DataPage 完成初始设置快照和变更信号接线；定向 `1 passed in 1.37s`，确认 generation 失效及当前资产重载。
- [PWF SYNC] 已满足 DataPage Mutation + GREEN 测试后的2-Action门禁；进入预览域回归与自审。
- [FAIL-1 · T-PREVSET-06] 可见预览域 `3 failed, 82 passed`；失败统一来自 FakePdfView 无缩放 API。
- [FIX · T-PREVSET-06] PDF设置应用增加可选后端能力检测，缺少 zoom API 时安全降级且不阻断 PDF 加载。
- [PWF SYNC] 已满足回归测试 + PDF兼容修复后的2-Action门禁；下一步复测可见预览域。
- [GREEN · T-PREVSET-06] 可见设置/Reader/Widgets 回归 `85 passed in 3.98s`。
- [GREEN · T-PREVSET-06] Provider/fallback/GeoViz/cache/disk/strategy 回归 `92 passed, 1 warning in 1.66s`。
- [PWF SYNC] 已满足连续2次回归测试后的门禁；下一步验证异步生命周期与 DataPage 全域。
- [GREEN · T-PREVSET-06] 异步生命周期分段A `17 passed in 3.11s`；分段B `14 passed in 2.60s`，完整覆盖31项。
- [PWF SYNC] 已满足连续2次异步测试后的门禁；下一步执行 DataPage 全文件与静态检查。
- [GREEN · T-PREVSET-06] DataPage/DataWorkspace `57 passed in 3.96s`；项目资产选择、导入、移除、重扫、PDF及设置重载均通过。
- [STATIC · T-PREVSET-06] `compileall` 与 `git diff --check` exit 0；确认未触碰既有无关未跟踪目录/文档。
- [PWF SYNC] 已满足 DataPage测试 + 静态验证后的2-Action门禁；下一步代码自审后运行全量 offscreen pytest。
- [FULL GREEN · Phase 32] `QT_QPA_PLATFORM=offscreen pytest -q`：`1051 passed, 4 skipped, 2 warnings in 49.69s`，exit 0。
- [COMPLETE · Phase 32] 统一预览设置模型、持久化面板、全格式内容参数、异步代次/缓存隔离与当前项目资产重载全部完成；进入最终独立审查与交付核验。
- [REVIEW · Phase 32] 按交付门禁已派发只读独立代码审查；等待 Critical/Important/Minor 结论后再执行最后新鲜验证。
- [REOPEN · Phase 32] reviewer：0 Critical、2 Important；已重开T-PREVSET-06，按TDD修复 Web首次设置与GeoTIFF严格尺寸。
- [RED · REVIEW FIX] 新增Web懒加载与GeoTIFF两项边界共3测试；结果 `3 failed`，分别复现未应用设置、超目标长边、原图被overview降质。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；下一步实现最小修复。
- [GREEN · REVIEW FIX] 完成Web首次设置与GeoTIFF严格长边/小图保真修复；定向 `3 passed in 0.96s`。
- [PWF SYNC] 已满足生产Mutation + GREEN测试后的2-Action门禁；下一步最终新鲜全量验证。
- [FAIL-1 · FINAL VERIFY] reviewer复核指出overview不足边界；全量在既有FakeWeb后端因无apply_settings失败，手动中止时 `1 failed, 583 passed, 4 skipped`。
- [RED PREP] 新增GeoTIFF overview倍率不足测试；Web兼容已由既有失败覆盖。
- [PWF SYNC] 已满足全量执行 + 测试Mutation后的2-Action门禁；下一步确认RED后做第二轮最小修复。
- [RED · REVIEW FIX-2] 旧FakeWeb兼容与overview不足 `2 failed`，均为预期缺失行为。
- [FIX · REVIEW FIX-2] Web使用apply_settings能力检测；GeoTIFF找不到足够倍率overview时保留ceil倍率。
- [PWF SYNC] 已满足RED执行 + 生产Mutation后的2-Action门禁；下一步定向GREEN。
- [GREEN · REVIEW FIX-2] Web新旧后端 + GeoTIFF非整除/小图/overview不足 `5 passed in 2.18s`。
- [FINAL VERIFY · Phase 32] compileall、`git diff --check`、全量 offscreen pytest 全部 exit 0；最终 `1055 passed, 4 skipped, 8 warnings in 49.54s`。
- [DONE · Phase 32] 所有用户目标与独立审查 Important 均已实现/修复；三份PWF文件同步完成，等待关闭目标并交付。
- [RUN · Phase 32] 按用户要求通过 `python -m paleo_workbench.main` 启动GUI；进程持续运行（PTY session 8632），Qt Multimedia/FFmpeg初始化成功，仅报告OpenGL ES兼容性 RuntimeWarning，无启动异常。
- [START · Phase 33] 用户要求把预览设置改为对话框并移入工具菜单；已读取 brainstorming/planning-with-files/TDD，建立自动批准设计与四项TDD清单，尚未修改业务代码。
- [PLAN · Phase 33] 已读取 writing-plans 并将文件边界、接口及四阶段RED/GREEN计划写入根task_plan；按PWF唯一体系未创建额外spec/plan。
- [RED · T-PREVDLG-01] 新增工具菜单内容与语义信号测试；`2 failed`，根因为工具仍是QLabel且无专用signal/action。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；下一步实现真实工具菜单。
- [IMPLEMENT · T-PREVDLG-01] MenuBar增加ToolsMenuButton/QMenu、“预览设置…”action及preview_settings_requested；保留labels顺序兼容既有测试。
- [PWF SYNC] 已满足菜单实现与类型导入两次Mutation后的2-Action门禁；下一步运行GREEN。
- [GREEN · T-PREVDLG-01] `tests/test_menu_bar.py`：`6 passed in 0.15s`。
- [RED · T-PREVDLG-02] 新增Dialog窗口语义测试；因 `preview_settings_dialog` 模块不存在而collection exit 2。
- [PWF SYNC] 已满足Dialog测试Mutation + RED执行后的2-Action门禁；下一步创建最小Dialog容器。
- [GREEN · T-PREVDLG-02] 创建应用级modal PreviewSettingsDialog；定向 `3 passed in 0.20s`。
- [PWF SYNC] 已满足Dialog生产Mutation + GREEN执行后的2-Action门禁；下一步Reader/Window迁移RED。
- [RED · T-PREVDLG-03] 改写Reader契约并新增Window工具菜单集成/重建接线测试；`3 failed`，均为迁移目标尚未实现。
- [PWF SYNC] 已满足集成测试Mutation + RED执行后的2-Action门禁；下一步实施Reader瘦化与Window Dialog接线。
- [IMPLEMENT · T-PREVDLG-03] ReaderPanel已删除设置按钮/Panel和相关布局依赖，提供公共 `set_preview_settings()` 消费接口。
- [IMPLEMENT · T-PREVDLG-03] AppWindow持有单实例Dialog，菜单打开时同步当前mode/settings，应用回调动态路由至当前shell DataPage。
- [PWF SYNC] 已满足Reader + Window两次生产Mutation后的2-Action门禁；下一步定向GREEN与兼容回归。
- [GREEN · T-PREVDLG-03] 三个迁移节点 `3 passed in 2.23s`。
- [GREEN · Phase 33域] menu/dialog/panel/reader/data integration `70 passed in 4.40s`。
- [PWF SYNC] 已满足连续2次测试后的门禁；下一步DataPage/生命周期、静态与全量验证。
- [SELF-REVIEW · Phase 33] 残留引用与diff审查完成，未发现旧内嵌UI依赖或stale shell接线；下一步执行高风险回归。
- [GREEN · T-PREVDLG-04] DataPage/ProjectLifecycle/AppShell `89 passed in 11.56s`。
- [STATIC · T-PREVDLG-04] `compileall paleo_workbench` 与 `git diff --check` exit 0；下一步独立审查和最终全量。
- [REVIEW · Phase 33] reviewer：0 Critical；确认Window/shell生命周期正确。开始按TDD修复测试QSettings污染，并补工具按钮样式。
- [RED · REVIEW FIX] 集成测试改用临时Store并新增Tools样式契约；`2 failed`，准确证明注入API与统一QSS缺失。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；下一步实现Store注入与样式，并撤销测试对生产配置的污染。
- [IMPLEMENT · REVIEW FIX] PaleoWorkbenchWindow增加可选PreviewSettingsStore注入并传给Dialog；生产默认仍使用标准Store。
- [IMPLEMENT · REVIEW FIX] QSS将ProjectMenuButton与ToolsMenuButton统一透明/hover样式。
- [PWF SYNC] 已满足Window + tokens两处生产Mutation后的2-Action门禁；下一步GREEN并恢复被测试污染的生产字号。
- [RECOVERY] 通过QSettings API将本轮测试误写的真实 `preview/settings/font_size` 从21恢复为推荐默认12。
- [GREEN · REVIEW FIX] Store隔离与Tools样式 `2 passed in 2.24s`。
- [FINAL VERIFY · Phase 33] reviewer行为Critical/Important清零；compileall/diff-check/full pytest exit 0，`1063 passed, 4 skipped, 8 warnings in 57.93s`。
- [DONE · Phase 33] 工具菜单Dialog迁移完成，准备以新代码重启GUI。
- [RUN · Phase 33] 新版GUI已通过 `python -m paleo_workbench.main` 启动并持续运行（PTY session 19595）；Qt Multimedia/FFmpeg初始化正常，无启动异常。用户可从“工具 → 预览设置…”打开模态设置对话框。
- [RUN · USER RETRY] 会话19595已正常退出（exit 0），但退出前地震3D产生pyqtgraph shader兼容日志；已按用户要求重新启动GUI，当前PTY session 62159持续运行，启动无异常。
- [START · Phase 34] 用户反馈地震剖面预览卡顿；已读取systematic-debugging/brainstorming/TDD/PWF并完成第一轮根因证据采集。
- [EVIDENCE] pyqtgraph 0.14模块缺compileShader/compileProgram，导致每帧异常且shader program永不缓存；PyOpenGL模块具备目标API。尚未修改生产代码。
- [PATTERN] PyOpenGL program对象确认支持现有context manager；pyqtgraph自身也依赖同一底层编译器。下一步在真实GLES3.2上下文运行最小monkeypatch实验，隔离是否还有GLSL源码错误。
- [DIAGNOSTIC-1] 独立GL实验首次因缺engine PYTHONPATH失败，改用显式包路径。
- [DIAGNOSTIC-2] 真实GLES3.2 context确认：正确编译器可调用，但modern shader因legacy texture3D helper编译失败；根因设计已锁定为编译器来源+GLSL分支隔离。
- [PLAN · Phase 34] 已读取writing-plans并在根task_plan锁定单文件engine修复、Fake context RED、真实GLES验证及分层回归；未创建额外计划文件。
- [RED ENV · T-SEISPERF-01] 新增Fake GLES3 compiler/source/cache回归；首次定向执行exit 1，唯一失败为`ModuleNotFoundError: geoviz_seismic`，目标断言尚未运行。
- [PWF SYNC] 已满足测试Mutation + 首次RED执行后的2-Action门禁；下一步显式设置engine本地包路径重跑功能RED，不把环境失败计作渲染修复strike。
- [RED · T-SEISPERF-01] 显式`PYTHONPATH=packages/geoviz_seismic`后，测试在目标断言失败：renderer未暴露PyOpenGL `gl_shaders`；功能RED成立。
- [PWF SYNC] 已满足PWF环境记录Mutation + 功能RED执行后的2-Action门禁；下一步实施renderer最小根因修复。
- [IMPLEMENT · T-SEISPERF-01] renderer改用PyOpenGL `gl_shaders`，并清除四个GLSL分支中不属于该版本的normal helper；未调整采样、纹理或UI链路。
- [GREEN · T-SEISPERF-01] Fake GLES3 compiler/source/cache定向测试`1 passed in 0.66s`。
- [PWF SYNC] 已满足生产Mutation + GREEN测试后的2-Action门禁；下一步运行renderer全文件和真实GLES3.2上下文验证。
- [GREEN · T-SEISPERF-02] renderer完整测试`8 passed in 0.78s`。
- [REAL GL ENV-1] 真实上下文脚本因`QOpenGLWidget`导入模块错误exit 1；尚未创建GL context，改从`PySide6.QtOpenGLWidgets`导入后重跑。
- [PWF SYNC] 已满足连续2次测试/诊断执行后的2-Action门禁；下一步修正一次性诊断脚本并验证真实driver编译。
- [REAL GL GREEN · T-SEISPERF-03] 真实DISPLAY/GLES3.2成功编译program=3，第二次调用`cache_identity=True`，无AttributeError或ShaderCompilationError。
- [DOMAIN GREEN · T-SEISPERF-02] renderer/seismic/sculpting/hillshading 7个测试文件`24 passed in 3.65s`。
- [PWF SYNC] 已满足真实GL诊断 + engine地震域测试后的2-Action门禁；下一步workbench预览域、静态检查与全量验证。
- [WORKBENCH GREEN · T-SEISPERF-04] GeoViz/Seismic/Preview相关10个测试文件`124 passed in 24.33s`，1条既知lasio warning。
- [STATIC GREEN · T-SEISPERF-04] engine/workbench compileall及父仓/子模块diff-check全部exit 0。
- [PWF SYNC] 已满足workbench预览域 + 静态验证后的2-Action门禁；下一步engine全量与根全量offscreen回归。
- [ENGINE FULL WAIT-1] engine单进程全量前24%断言全绿，随后Qt poll等待超过3分钟且无输出；精确终止本轮pytest，准备按文件分段。
- [ROOT FULL FAIL-1] 根单进程全量约12%在pytest-qt teardown `_process_events` segfault；无断言失败、无shader异常，策略改为分段新进程。
- [PWF SYNC] 已满足engine全量尝试 + 根全量尝试后的2-Action门禁；下一步先收集测试文件并分批执行，隔离Qt生命周期噪声。
- [ROOT SEGMENT A GREEN] 排序文件1–20：`214 passed in 11.13s`，1条既知lasio warning。
- [ROOT SEGMENT B GREEN] 排序文件21–40：`144 passed in 22.03s`，1条既知lasio warning。
- [PWF SYNC] 已满足连续2次分段测试后的2-Action门禁；下一步继续文件41–80。
- [ROOT SEGMENT C GREEN] 排序文件41–60：`100 passed, 4 skipped in 5.13s`。
- [ROOT SEGMENT D GREEN] 排序文件61–80：`99 passed in 4.73s`。
- [PWF SYNC] 已满足连续2次分段测试后的2-Action门禁；下一步继续文件81–120。
- [ROOT SEGMENT E GREEN] 排序文件81–100：`210 passed in 17.19s`，7条既知lasio/rasterio warnings。
- [ROOT SEGMENT F GREEN] 排序文件101–120：`99 passed in 4.07s`，1条既知GDAL future warning。
- [PWF SYNC] 已满足连续2次分段测试后的2-Action门禁；下一步完成文件121–157并核对总数。
- [ROOT SEGMENT G GREEN] 排序文件121–140：`116 passed in 4.92s`。
- [ROOT SEGMENT H GREEN] 排序文件141–157：`81 passed in 5.16s`。
- [ROOT COMPLETE · T-SEISPERF-04] 八段合计`1063 passed, 4 skipped`，与修复前基线总数一致；无断言失败。
- [PWF SYNC] 已满足连续2次分段测试后的2-Action门禁；下一步独立审查、最终新鲜定向验证与GUI重启。
- [REVIEW · Phase 34] 独立审查：0 Critical、1 Important（legacy horizon generic texture）、3项Minor覆盖建议；Ready=No until fix。
- [RED · T-SEISPERF-REVIEW-01] 新增加严编译器identity、二次link检查、GLES2/desktop legacy纹理函数测试；结果`3 failed`，分别准确复现缺少check_linked与两处分支污染。
- [PWF SYNC] 已满足review测试Mutation + RED执行后的2-Action门禁；下一步修复两处legacy采样并检查二次relink状态。
- [IMPLEMENT · REVIEW FIX] legacy两个分支改用`texture2D`，现代两个分支保持generic `texture`；二次relink后增加`program.check_linked()`。
- [SELF-CORRECTION] 首次宽泛替换误命中modern GLES；分支行号自检立即纠正，最终四分支函数矩阵正确，尚未运行GREEN。
- [PWF SYNC] 已满足两次生产Mutation后的2-Action门禁；下一步定向GREEN与真实GLES复验。
- [GREEN · REVIEW FIX] modern compiler/link/cache与两个legacy分支`3 passed in 0.69s`。
- [REAL GL RE-GREEN] 修复后真实GLES3.2 program=3、cache identity=true，exit 0。
- [PWF SYNC] 已满足定向GREEN + 真实driver复验后的2-Action门禁；下一步reviewer复核、最终新鲜门禁和GUI重启。
- [RE-REVIEW · Phase 34] 原Important清零，0 Critical/Important，Ready=Yes；legacy真实context缺失仅为非阻塞测试边界说明。
- [FINAL ENGINE TARGET] renderer全文件`10 passed in 0.65s`；renderer/seismic/sculpting/hillshading相关域`26 passed in 3.30s`。
- [PWF SYNC] 已满足连续2次新鲜engine验证后的2-Action门禁；下一步workbench链路新鲜验证、静态门禁和重启运行观察。
- [FINAL WORKBENCH TARGET] GeoViz/Seismic/Preview链路`124 passed in 24.35s`，1条既知lasio warning。
- [FINAL STATIC] compileall、父仓与engine diff-check均exit 0；源码扫描确认编译器/四分支纹理函数矩阵符合设计。
- [PWF SYNC] 已满足workbench新鲜验证 + 静态门禁后的2-Action规则；下一步停止旧GUI并以修复代码启动，观察实时日志。
- [RESTART · Phase 34] 旧GUI PID 849341已精确TERM并退出；当前代码以PTY session 75620启动，持续运行，启动日志仅FFmpeg初始化。
- [REAL PAINT · Phase 34] 真实GLES3.2 Renderer3D加载16³体数据并绘制30帧，`REAL_PAINT_OK program=6`，exit 0；无shader异常洪泛。
- [DONE · Phase 34] 错误编译器API、modern/legacy GLSL污染与二次relink检查均已修复；独立审查0 Critical/Important，GUI已重启供用户使用。
- [PWF SYNC] 已满足GUI重启 + 真实paint验证后的2-Action门禁；三份PWF文件最终同步完成。
- [START · Phase 35] 用户要求DAT/LAS等专业预览改为“数据列表 + 可视化预览”双选项卡，可视化仅在首次点击时启动后台任务。
- [SKILLS · Phase 35] 已启用using-superpowers、brainstorming、Planning with Files和TDD；按用户唯一PWF体系不创建额外design/spec文档。
- [PWF SYNC] 已满足技能/PWF恢复阶段的2-view门禁；下一步完整读取技能余段并审计现有预览数据流。
- [SKILL READ-1] 已完整读取brainstorming，并读取TDD前220行；确认实现硬门禁为“先审计→候选设计→批准→writing-plans→功能RED→生产代码”。
- [PWF SYNC] 已满足连续2次skill view后的Planning with Files门禁；下一步读完TDD/PWF技能与writing-plans，再审计代码。
- [SKILL READ-2] TDD已完整读取；Planning with Files已读前240行，确认还需遵守view类2-Action、错误全记录与3-Strike更换策略。
- [PWF SYNC] 已满足连续2次skill view门禁；下一步读完PWF余段，并在设计批准后只调用writing-plans进入实现规划。
- [SKILL READ-3] Planning with Files已完整读取；已完成第一轮preview/Reader/Controller/GeoViz代码搜索。
- [AUDIT-1 · Phase 35] 发现当前重工作在Provider一次请求内已执行，Reader仅延迟Host import不足以实现“点击第二页才开线程”；需拆分轻量列表请求和惰性可视化请求。
- [PWF SYNC] 已满足PWF余段 + 代码搜索2-view门禁；下一步读取关键实现和测试，锁定最小接口。
- [AUDIT-2 · Phase 35] 已读LocalVisualizationProvider/PreviewResult/LAS/SEG-Y fallback和Reader完整实现；确认可复用现有summary widgets与Host clear/release，但必须拆Provider请求语义。
- [PWF SYNC] 已满足provider + reader两个view门禁；下一步审计Controller/DataPage和已有异步测试，随后形成候选设计。
- [AUDIT-3 · Phase 35] 已读PreviewRequestController/DataPage选择、设置、shutdown接线和关键async/Reader测试；锁定双controller + Reader语义信号方向。
- [PWF SYNC] 已满足Controller/DataPage + tests两个view门禁；下一步核对GeoViz supports的格式覆盖与DAT引擎语义，完成候选设计。
- [SEARCH ERROR] 首次GeoViz全包rg误包含web_dist大bundle并截断；更换为精确源文件范围后取得有效证据。
- [AUDIT-4 · Phase 35] 确认双页候选格式为engine-supported LAS、SEGY与4类DAT语义；prepare在线程、render在UI线程的现有边界可直接复用。
- [PWF SYNC] 已满足GeoViz广搜 + 定向源码两个view门禁；下一步形成候选方案与自动批准设计，并调用writing-plans。
- [DESIGN · Phase 35] 已向用户呈现A/B/C三方案并采用双Controller推荐；Provider/DTO、Reader tabs、DataPage generation、错误和测试设计已写入task_plan。
- [DESIGN APPROVAL] 当前需求明确指定双页与点击后启动，结合此前“默认推荐、直接执行”授权，推荐设计自动批准；按用户PWF限制不创建/commit额外spec。
- [PLAN · Phase 35] 已完整读取writing-plans，并在task_plan写入5个可独立RED/GREEN的Task、精确文件/接口/测试门禁；选择inline execution以遵守直接执行与非委派约束。
- [PLAN SELF-REVIEW] 覆盖/placeholder/type/scope四项自审通过；未创建docs plan、未commit，符合用户唯一PWF体系。
- [PWF SYNC] 已满足DAT测试搜索 + plan复读后的2-view门禁；下一步读取executing-plans并执行Task35.1 RED。
- [EXECUTION SKILLS] 已完整读取executing-plans与using-git-worktrees；计划采用当前会话inline执行，但先按门禁检测是否已隔离及分支状态。
- [PWF SYNC] 已满足两个execution skill view门禁；下一步只读检测git目录/分支/dirty基线，决定安全执行位置。
- [WORKSPACE · Phase 35] 检测到main普通工作区及既有dirty改动；依据用户授权在原工作区执行，不创建worktree、不commit，保留所有无关文件。
- [BASELINE FAIL-1] Provider/Reader/async/DataPage/lifecycle 6文件组合在`test_cache_miss_after_file_rewrite`的Qt wait发生Bus error，约88项此前已通过且无断言失败。
- [PWF SYNC] 已满足workspace检测 + baseline测试后的2-Action门禁；策略改为独立进程分段，先确认Task35.1 Provider基线再写RED。
- [BASELINE GREEN · Task35.1] Provider两个测试文件`36 passed in 2.20s`，1条既知lasio warning。
- [TEST MAP · Task35.1] 已读RecordingEngine与bounded provider测试，锁定4个最小RED节点。
- [PWF SYNC] 已满足baseline测试 + test map view后的2-Action门禁；下一步写Task35.1测试Mutation并验证RED。
- [DAT FIXTURE AUDIT] 已读取engine真实DAT markers/fixtures及Provider测试imports，确定well-head列表RED与不规则文本fallback RED。
- [PWF SYNC] 已满足DAT fixture + test import两个view门禁；下一步正式写Provider两阶段/DAT列表测试。
- [RED · Task35.1] 新增5项Provider/DAT测试；`4 failed, 1 passed`，失败均为计划功能缺失，fallback现有行为保持通过。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；下一步实现最小Provider/DTO/DAT列表逻辑。
- [IMPLEMENT · Task35.1] 完成PreviewResult capability、Provider两阶段契约、Local summary/visual拆分与DAT有界列表解析。
- [GREEN-1 · Task35.1] 5个新增节点`5 passed in 0.66s`，1条既知lasio warning。
- [PWF SYNC] 已满足生产Mutation + GREEN测试后的2-Action门禁；下一步两个Provider全文件回归并自审边界。
- [DONE · Task35.1] Provider全文件`41 passed in 1.02s`，1条既知lasio warning；两阶段/DAT列表交付完成。
- [TDD REFERENCE] 已完整读取testing-anti-patterns并审计async测试helpers，Task35.2将测试真实controller行为，不测试mock本身。
- [PWF SYNC] 已满足Provider回归 + 两个test-design view后的门禁；下一步Task35.2测试Mutation与RED。
- [RED · Task35.2] 新增request_kind路由、summary disk隔离、invalidate stale丢弃共4项；全部因构造参数缺失失败，功能RED成立。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；下一步实现Controller/Worker最小purpose与invalidate。
- [IMPLEMENT · Task35.2] Controller/Worker增加validated request_kind、统一provider method路由、summary disk短路和合作式invalidate。
- [GREEN-1 · Task35.2] 新增4项`4 passed in 0.29s`，无线程警告。
- [PWF SYNC] 已满足生产Mutation + GREEN测试后的2-Action门禁；下一步分段运行preview_async全文件。
- [ASYNC GREEN-A · Task35.2] `15 passed, 20 deselected in 3.71s`。
- [ASYNC GREEN-B · Task35.2] `20 passed, 15 deselected in 2.27s`；完整35项覆盖。
- [DONE · Task35.2] request purpose、summary disk隔离与invalidate生命周期完成。
- [PWF SYNC] 已满足连续2次async测试后的2-Action门禁；下一步Task35.3 Reader双页RED。
- [RED · Task35.3] 新增4个Reader行为节点；3项按预期缺接口失败，普通text单页回归通过。
- [PWF SYNC] 已满足Reader测试Mutation + RED执行后的2-Action门禁；下一步创建LazyVisualizationTabs并最小接入Reader。
- [IMPLEMENT-1 · Task35.3] 新建LazyVisualizationTabs，完成两页文案、summary、visual局部状态、单次request signal、惰性Host与release接口。
- [IMPLEMENT-2 · Task35.3] Reader组合新组件，新增semantic signal/loading/error/render_visualization，visualizable summary默认Tab0；普通预览保留旧stack。
- [PWF SYNC] 已满足两个生产Mutation后的2-Action门禁；下一步运行Reader新增节点GREEN并修正真实缺陷。
- [PWF SYNC] 已满足测试 Mutation + RED 测试后的2-Action门禁；下一步实现各 Widget apply_settings 与 ReaderPanel 内嵌设置面板。
## 2026-07-19 Phase 35（DAT/LAS 双阶段懒预览）

- Task 35.3 定向测试：`QT_QPA_PLATFORM=offscreen pytest -q tests/test_data_reader_panel.py -k 'visualizable_summary or visualization_loading or prepared_visualization or ordinary_text'`，结果 `4 passed`。
- 随后执行完整 `tests/test_data_reader_panel.py`；终端输出因会话上下文截断且进程已结束，最终摘要未能可靠回收。按真实反馈记录为“结果待分段复验”，不据此宣称通过；下一步改用小批次回归定位兼容性差异。
- Reader 4个遗留节点复跑为 `4 failed`：1项仅是旧直占面板断言；2项暴露Host在render异常后未被Reader持有，访问property会重复set_engine；1项暴露Web隔离测试的轻量Widget没有`apply_settings`。
- 修复Host在render前即登记所有权，并令惰性summary设置调用保持可选；更新旧direct-geoviz断言为外层双Tab、内层Host的真实层级。
- Task 35.3 精确复验 `4 passed`；完整 `tests/test_data_reader_panel.py` 为 `41 passed in 3.48s`。双选项卡、惰性Host、失败清理及Web隔离兼容均通过，Task35.3 DONE。
- Task 35.4 接线审计：DataPage当前只有default controller，选择、重扫、右键预览、设置、project root、清缓存和shutdown均只路由该实例；需要保留`_preview_controller`名称作为summary兼容面，并为visual controller补齐全部失效与生命周期路径。
- Task 35.4 RED：新增懒触发功能测试并扩展close/deferred-delete/settings生命周期断言；精确4节点均按预期失败，原因是`_visualization_controller`尚不存在或shutdown仅调用一次。
- Task 35.4 实现：summary controller固定`request_kind=summary`，新增visualization controller及Reader信号接线；选择/重扫/右键摘要先invalidate visual，设置/project root/cache/shutdown双实例同步。
- Task 35.4 首轮GREEN：懒触发、重复Tab不重复请求、双shutdown、设置双generation共4节点 `4 passed`。
- Task 35.4 stale/cache门禁：真实阻塞A可视化期间切换B，A完成后未覆盖B；双controller的unknown/valid project root与内存/磁盘cache清理一致。精确4节点 `4 passed`。
- 回归映射复核：App级预览设置重建测试与DataPage关闭异步测试仍只断言summary controller，需扩展visual settings与visual thread shutdown；既有普通文本异步Provider可继续通过`preview_summary -> preview`兼容契约。
- 扩展App重建设置与真实DataPage close断言；精确2节点 `2 passed`，确认新页面visual controller收到设置且关闭后两个controller均无活动线程。
- Task35.4 整文件回归A：`tests/test_data_page.py` 53 passed（1条既知lasio warning）；`tests/test_data_integration.py` 4 passed。
- Task35.4 async完整分段：22 passed + 15 passed（互补deselection共37项）；无QThread销毁警告。Task35.4 DONE。
- Task35.5 静态门禁：`python -m compileall -q paleo_workbench`、父仓`git diff --check`、engine `git diff --check`均返回0且无输出。
- 完成流程：已完整读取requesting-code-review与verification-before-completion；将按要求先取diff范围、发起独立审查，再执行新鲜的完整相关域验证后才声明完成。
- 已完整读取finishing-a-development-branch与reviewer模板；当前是main普通dirty工作区且用户未授权commit/merge/push，本轮仅执行验证与只读审查，不触发任何集成/清理动作。
- 新鲜验证批次：Provider 35、GeoViz Provider 6、Reader 41、DataPage 53、integration 4 均通过；随后单进程完整async在输出19个点后超过90秒无进展，手动TERM精确pytest/shell PID，未删除或改写数据。
- 该现象与既有Qt长序列事件循环不稳定一致；不计为断言失败，继续采用已验证的互补`-k`独立进程（22+15）策略，并单独运行project lifecycle。
- 新鲜分段门禁：async A `22 passed, 15 deselected`，async B `15 passed, 22 deselected`，合计全覆盖37项；project lifecycle `22 passed`。三进程均exit 0。
- 根全量策略复核：当前仍为157个排序测试文件，沿用已证实的每20文件独立进程A–H；包含`test_preview_async.py`的段将排除此文件并用两个互补子进程替代，避免已复现的单文件顺序挂起。
- Phase35根全量 A/B：排序文件1–20为 `218 passed`；21–40为 `147 passed`；均exit 0，各1条既知lasio warning。
- Phase35根全量 C/D：排序文件41–60为 `100 passed, 4 skipped`；61–80为 `99 passed`；均exit 0。
- Phase35根全量 E-part1：排序文件81–100排除async为 `181 passed`（7条既知lasio/rasterio warning）；async互补A为 `22 passed, 15 deselected`。
- [REVIEW · Phase35] 独立审查：0 Critical、5 Important、2 Minor，Assessment=DONE_WITH_CONCERNS；全量验证暂停在E-part1。
- 已按receiving-code-review核对第一轮源码证据：engine确有`geoviz_well_log.inspect_las_file()`有界/非驻留检查API，workbench当前却调用`lasio.read()`；其余失败重试、DAT半行、text空页、cache重写路径也均能由现有代码直接复现，接受5项Important并逐项TDD修复。
- Reviewer修复设计锁定：facade导出`inspect_las_file`供瘦Host摘要使用；PreviewResult增加显式cacheable语义；LazyTabs summary改为table/text子栈；controller增加共享cache epoch锁以原子协调clear与worker store；失败重试与“用户返回列表不抢Tab”在Tabs状态机内解决。
- R35-01 RED：用会抛AssertionError的lasio stub证明summary仍调用完整matrix loader；目标节点返回message而非well_log，`1 failed`。
- R35-01 GREEN：engine facade导出流式`inspect_las_file`，workbench摘要仅消费header/curve metadata/row_count；同一lasio禁用节点 `1 passed`。
- R35-03/04 测试锚点已核对：DAT契约位于Provider文件前段，Reader双Tab契约位于visualizable summary节点；下一步补字节边界和text fallback RED。
- R35-03/04 RED-ENV-1：4项在触达目标前失败，原因是fixture使用非法`text_limit_kib=1`（配置下限16）且Reader测试漏导入PreviewProvider；属于测试环境设计错误，不计实现strike。改用16KiB且每行16 bytes，使边界仍精确且行数低于2000上限。
- R35-03/04 RED：字段间截断降级text、字段中截断保留损坏`('999','8')`、Reader缺summary text子栈，共3项真实失败；恰在换行边界节点1 passed。
- R35-03/04 GREEN：DAT在decode前丢弃byte-truncated末尾半行，换行边界保留；LazyTabs数据页使用summary/text子栈。字段中/字段间/换行/text页共 `4 passed`。
- R35-02/M01 RED：4节点失败，分别证明PreviewResult无cacheable、Reader无retryable参数、完成回调强制切回Tab1；controller节点另发现provider request-local浅拷贝使整数计数留在副本，测试将改用共享list后再触达缓存断言。
- R35-02测试校正：provider计数改为浅拷贝共享list，并新增result/failure交付断言，防止“构造TypeError但调用次数正确”的假阳性。
- R35-02校正后RED：两次请求均触达provider，但均因PreviewResult缺cacheable进入failed，真实目标节点 `1 failed`。
- R35-02/M01实现：PreviewResult增加cacheable；GeoVizError标记noncacheable；worker与LRU跳过失败；Tabs错误状态允许离开/返回重试，异步完成仅更新visual stack且不抢用户当前数据Tab。
- R35-02/M01 GREEN：noncacheable controller二次真实调用、GeoViz失败DTO、Tab重试、完成不抢Tab共 `4 passed`。
- R35-05 RED已写：阻塞专业prepare期间clear cache，要求generation+1、无UI交付、无disk store、LRU空。
- R35-05 RED：目标节点 `1 failed`，首个断言确认clear cache未提升generation；源码定位4处generation变更与worker disk store入口，准备以共享epoch锁原子协调。
- R35-05 GREEN：controller共享CacheEpoch/RLock；clear在同一锁内advance+删除，worker仅在epoch仍当前时store；阻塞任务节点 `1 passed`，无UI交付/磁盘回写/LRU复活。
- Provider整文件回归首轮：37 passed后1 fail，旧兼容契约要求只有`~Version`的空LAS仍显示0曲线/0采样well_log，而engine inspector严格抛no curve headers。
- 兼容修复：仅识别engine稳定的“no curve headers”ValueError并构造空摘要+警告；其他ValueError仍保持失败消息，不回退lasio或复制解析器。
- Reviewer修复回归A：Provider `38 passed`；GeoViz Provider `7 passed`，均exit 0且无新增warning。
- Reader回归首轮：43 passed、1旧测试失败；旧测试直接注入visual result却未模拟用户点击/visual loading，与新“仅点击后请求”状态机不符。测试已补真实Tab激活与loading前置，不修改生产保护逻辑。
- Reader复验 `44 passed`。随后async A仅输出5项后超过35秒无进展，已TERM精确pytest PID；这是CacheEpoch引入后相较此前22项/3秒的新回归信号，暂停其余测试并按`-vv -x`定位具体节点。
- 系统调试Phase1：A段排序显示第5/6项为两个DataPage可视化测试；第6项`selection_discards_obsolete_visualization`单独运行 `1 passed in 1.51s`，说明不是该逻辑单测稳定死锁，而是前5项teardown/下项startup的顺序交互。下一步用前6项`-vv`复现并观察停点。
- 系统调试Phase2/3：前6项同进程`6 passed in 1.65s`；随后A段同一命令加30s外部deadline复验`22 passed, 17 deselected in 3.01s`。挂起不可稳定复现，符合既有Qt teardown时序噪声而非CacheEpoch锁稳定死锁；保留分段+deadline门禁。
- Async B在新增3项排到最前后稳定于5点处触发40s deadline（exit124）；排序显示停点边界是`rescan_invalidates_inflight_preview`完成后/`stale_generation_discarded`开始。下一步以B前6项`-vv -s`确认具体停在test body还是teardown。
- B前6项详细模式全部通过（2.05s），随后完整B复验 `17 passed, 22 deselected in 3.19s`；与A同样未形成稳定代码死锁。当前async全覆盖为22+17=39项全绿，外部deadline保留用于最终验证。
- Reviewer修复回归B：DataPage `53 passed`（1条既知lasio warning）；integration `4 passed`。
- R35-M02 RED：RecordingEngine按真实engine contract在prepare阶段抛UNSUPPORTED；显式visual请求仍先调用supports，精确节点 `1 failed, 1 passed`，证明一次冗余backend/header resolution。
- R35-M02实现：visual请求直接调用engine.prepare，按ErrorCode区分UNSUPPORTED稳定结果与其他noncacheable失败；3节点中2 passed，unsupported旧断言因test double在resolve失败前记录prepare_calls而1 fail，需校正计数语义为“backend prepare实际进入”。
- R35-M02 GREEN：RecordingEngine计数移到unsupported resolution之后；GeoViz Provider全文件 `7 passed`，显式visual不再提前supports，减少一次DAT header resolution。
- CacheEpoch性能RED：真实disk codec的`np.savez_compressed`阻塞0.5s时，UI线程`clear_disk_cache()`同步等待0.501s，目标节点 `1 failed`；根因是epoch锁包住整个store而非仅最终commit，违反不卡GUI目标。
- CacheEpoch性能GREEN：disk store在锁外完成encode/compress，仅最终entry replace受commit_guard保护；clear不等待压缩且旧epoch不提交。保留/非阻塞两节点 `2 passed`。
- Disk cache全文件 `10 passed`。随后async A在前4项通过后于DataPage lazy wait发生Qt Bus error（exit135，pytestqt exec栈，无Python断言/QThread destroyed）；这是既有长Qt进程原生崩溃模式，后续最终门禁将把DataPage两个重型节点与controller节点拆成独立进程，不继续原样重跑A。
- Review复核新增Important：cache clear取消请求导致Reader永久loading；契约改为只advance cache epoch、保持request generation与UI交付。RED首断言确认当前generation由1变2，目标节点 `1 failed`。
- Cache/request解耦实现范围复核：pending与inflight需同时携带request generation和cache generation；clear只advance后者，worker commit与UI-thread LRU分别检查cache epoch，result仍按request generation交付。
- Cache/request解耦GREEN：pending/inflight携带双generation；clear不取消UI请求，仅阻断旧epoch disk/LRU；shutdown同时失效两者。结果交付与非阻塞压缩两节点 `2 passed`。
- LAS WRAP/DLM RED：新增COMMA/TAB参数与WRAP.YES端到端inspection+preview测试；TAB因whitespace split现有通过，COMMA与WRAP各失败，结果 `2 failed, 1 passed`，准确复现兼容缺口。
- LAS WRAP/DLM GREEN：engine header记录wrapped/delimiter；inspection与sample pass共享delimiter tokenization和逻辑行组装。COMMA/TAB/WRAP端到端 `3 passed`。
- Engine LAS全文件首次因手工PYTHONPATH仅含well_log而9项缺`geoviz_seismic`失败（前10项含新功能均通过），属测试环境未触达实现；补齐8个engine package根后全文件 `19 passed`。
- Cache clear UI集成：阻塞summary与阻塞visualization期间分别clear，释放后都正常交付且离开loading；DataPage两节点 `2 passed`。
- Error语义解耦RED：IO_ERROR应retryable且显示真实消息，INVALID_DATA应nonretryable但仍noncacheable；两节点均因DTO无retryable字段失败。
- Error语义解耦GREEN：DTO独立retryable；IO/RENDER可重试，INVALID_DATA/RESOURCE_LIMIT等不自动重试；所有GeoVizError仍不缓存并显示真实错误消息。2 passed。
- 第三轮复核前回归：GeoViz Provider `8 passed`；Reader `44 passed`。
- 第三轮复核前回归：Provider `38 passed`；disk cache `10 passed`。
- 第三轮复核前回归：DataPage `53 passed`（1条既知lasio warning）；integration `4 passed`。
- 第三轮独立只读复核：0 Critical、0 Important，结论READY；仅记录LAS重复流式扫描、空LAS异常文本协议、极大cache root同步删除3项Minor，当前交付不受阻。
- Async最终强隔离门禁：收集42节点，每节点独立offscreen pytest进程并设20秒deadline，`ASYNC_NODES_PASSED=42`、总命令exit 0；无断言失败。
- [PWF SYNC] 已满足最终async执行与审查反馈后的状态同步；Task35.5继续执行新鲜根分段全量回归。
- 根全量新鲜A段（排序文件1–20）`221 passed, 1 warning`，exit 0。
- 根全量新鲜B段（21–40）`148 passed, 1 failed, 1 warning`；唯一失败是package-independence静态门禁将`preview_provider.py`识别为未通过`geoviz` facade的生产导入。记为该缺陷Strike 1，先定位检测到的具体import，禁止盲目重跑。
- [PWF SYNC] 已满足A/B两次测试执行后的2-Action门禁；进入静态import根因分析并补回归RED。
- B段失败根因：生产代码已正确使用`from geoviz import inspect_las_file`公共facade；静态测试的`GEOVIZ_PUBLIC_FACADE`白名单未随新增兼容导出更新，属于测试契约滞后，不是workbench越层导入。
- 将`inspect_las_file`纳入facade白名单；精确静态门禁 `1 passed`，Strike 1闭环。未改生产导入路径。
- [PWF SYNC] 已满足测试契约Mutation + 精确GREEN后的2-Action门禁；下一步重跑B段并继续C–H。
- 根全量新鲜B段修复后重跑 `149 passed, 1 warning`；C段 `100 passed, 4 skipped`；两者exit 0。
- [PWF SYNC] 已满足B重跑/C段两次测试执行后的2-Action门禁；继续D与E（E排除async，async已由42独立节点覆盖）。
- 根全量新鲜D段 `99 passed`、exit 0。
- E-base在57个点后于`test_preview_disk_cache.py::test_second_request_uses_disk_without_prepare`的pytest-qt事件等待中发生原生Abort（exit134），无Python断言、无QThread-destroyed消息；与已记录的大量Qt文件同进程累积析构故障同型，不记为产品缺陷Strike。策略切换为E段逐测试文件独立进程，禁止原样重复。
- [PWF SYNC] 已满足D/E两次测试执行后的2-Action门禁；E将按文件隔离并输出紧凑计数。
- E逐文件脚本首轮在首文件通过后触发zsh只读变量`status`赋值错误，属于测试调度脚本错误、未触达后续产品测试；立即改用`test_exit`，不重复原命令。
- E段排除async后的19个测试文件逐文件新进程全部通过，合计184 passed（其中settings已有6 warnings）；`E_FILES_PASSED=19`、总命令exit 0。async另有42/42节点独立通过。
- [PWF SYNC] 已满足E隔离脚本校正前后两次测试执行后的2-Action门禁；继续F/G。
- 根全量新鲜F段 `99 passed, 1 warning`；G段 `116 passed`；两者exit 0。
- [PWF SYNC] 已满足F/G两次测试执行后的2-Action门禁；继续H与engine LAS全域。
- 根全量新鲜H段 `81 passed`；engine LAS inspection/sample全域 `19 passed`；两者exit 0。
- 根测试新鲜合计：A221 + B149 + C100 + D99 + E184 + async42 + F99 + G116 + H81 = `1091 passed, 4 skipped`；相对1063基线新增28项，全部来自后续预览/性能修复回归覆盖。
- [PWF SYNC] 已满足H/engine两次测试执行后的2-Action门禁；下一步新鲜静态门禁与工作树核对。
- 新鲜静态门禁：workbench + engine facade/well_log `compileall` exit 0；父仓与engine `git diff --check`均exit 0、无输出。
- [PWF SYNC] 已满足compileall/diff-check两次验证后的2-Action门禁；下一步核对最终diff范围、完成PWF并启动GUI。
- 最终工作树核对：Phase35新增`lazy_visualization_tabs.py`仍为未跟踪交付文件；engine facade/LAS parser与所有workbench/test改动均在共享dirty工作树中，未commit/stage，且保留用户既有`SCRATCH/`和旧docs plans不动。
- 图形环境可用（DISPLAY=:1，WAYLAND_DISPLAY=wayland-0），当前无旧`paleo_workbench.main`进程；可安全启动本轮GUI。
- [PWF SYNC] 已满足最终status与运行环境两次只读核对后的2-Action门禁；启动GUI后记录session并关闭Phase35。
- [RUN · Phase35] `python -m paleo_workbench.main`已在图形会话启动并持续运行（PTY session 98063）；Qt Multimedia/FFmpeg初始化成功，仅有既知OpenGL ES兼容RuntimeWarning，无启动异常。
- [COMPLETE · Phase35] DAT/LAS双页渐进预览、点击后异步可视化、stale/cache/lifecycle修复、三轮审查、1091+4根回归与engine验证全部闭环；GUI已交付体验。
- [PWF SYNC] 根三份PWF最终同步完成；Phase35状态COMPLETED。

## 2026-07-19 Phase 36（专业数据首屏纯表格）

- 已读取brainstorming、TDD与Planning with Files技能；因用户禁止额外长期记忆文件，设计与计划继续只写根三份PWF，不创建/commit `docs/superpowers/specs`。
- 已定位当前UI：双页首屏组合了属性摘要表和真实数据表；变更应局限`LazyVisualizationTabs`，避免影响GeoTIFF等确实需要元数据的普通预览。
- [PWF SYNC] 已满足现状/源码两次查看后的2-Action门禁；当前停在brainstorming设计批准门禁，未修改生产代码。
- 用户明确批准方案A；已使用writing-plans把单一组件边界、行为RED、最小GREEN、相关域回归与GUI重启步骤写入`task_plan.md`。
- 计划自审通过：无额外文件、无DTO/engine改动、无普通元数据预览波及；下一步进入inline TDD执行。
- executing-plans复核无阻断：当前main dirty工作树是用户已批准的共享执行环境；本轮不引入worktree/commit，不覆盖其他Phase改动。
- 精确测试定位：现有visualizable测试直接依赖`tabs.summary.detail_table`；RED将把契约改为`tabs.summary`本身是`TablePreviewWidget/QTableWidget`并直接校验表头与数据。
- [PWF SYNC] 已满足执行技能与测试/组件源码两次查看后的2-Action门禁；开始Task36.1测试Mutation。
- Task36.1测试Mutation：visualizable首屏现断言纯`TablePreviewWidget`、真实表头/行，以及不存在属性摘要子表；同步更新同组件的loading/reset保留数据断言为直接表格API。
- Task36.1 RED：精确节点 `1 failed`，失败点为`tabs.summary`实际仍是`SummaryTablePreviewWidget`，准确锁定待替换生产行为，记Strike 0（预期RED）。
- [PWF SYNC] 已满足测试Mutation + RED执行后的2-Action门禁；进入Task36.2最小生产实现。
- Task36.2生产Mutation：`LazyVisualizationTabs.summary`改为`TablePreviewWidget`，非text只加载`table_headers/table_rows`；删除该路径对`summary_rows/message`的渲染消费。
- Task36.2精确GREEN：纯表格首屏节点 `1 passed`；表头“曲线/单位”和行“GR/API”直接位于首屏表格。
- [PWF SYNC] 已满足生产Mutation + GREEN执行后的2-Action门禁；下一步Reader完整回归。
- Task36 Reader完整回归 `44 passed`；DataPage + integration `57 passed, 1条既知lasio warning`；两命令均exit 0。
- [PWF SYNC] 已满足Reader/Data两次测试执行后的2-Action门禁；继续async生命周期与静态门禁。
- Async关键节点独立进程：Tab激活前不启动可视化 `1 passed`；切资产丢弃旧visual result `1 passed`。
- [PWF SYNC] 已满足两个async测试执行后的2-Action门禁；继续clear-during-loading与静态检查。
- Async clear生命周期独立进程：summary loading期间clear `1 passed`；visual loading期间clear `1 passed`；无stranded loading/QThread警告。
- [PWF SYNC] 已满足两个clear async测试执行后的2-Action门禁；Task36.2相关域回归完成，进入compile/diff门禁。
- Task36静态门禁：目标模块compileall exit 0；父仓与engine diff-check exit 0、无输出。
- [PWF SYNC] 已满足compileall/diff-check两次验证后的2-Action门禁；下一步按finishing/verification流程复核并重启GUI。
- 已完整读取finishing-a-development-branch与verification-before-completion；将以新鲜完整回归证据完成，不用先前结果替代。
- 环境检测：普通仓库、branch=main、git_dir==git_common；用户未授权commit/merge/push，按既定“Keep as-is”保留共享dirty工作树，不执行集成或清理动作。
- [PWF SYNC] 已满足finishing技能与git环境两次查看后的2-Action门禁；进入根测试分段验证。
- 旧GUI session 98063对Ctrl-C未退出，已只对精确PID 917429发送TERM并确认session exit 1；未影响其他进程/文件。
- Phase36根回归A段 `221 passed, 1 warning`。B段在第3项`test_datapage_stress.py::test_stress_s3_rapid_select`发生Qt原生Bus error（exit135），无业务断言；记为隔离策略故障而非纯表格缺陷Strike，禁止原样重跑B段。
- [PWF SYNC] 已满足A/B两次测试执行后的2-Action门禁；B段切换为逐文件新进程，避免Qt stress与后续GUI文件共享原生状态。
- B隔离复验：`test_datapage_stress.py`单独 `5 passed`；其余19文件 `144 passed, 1 warning`；合计149 passed、均exit 0，确认原生崩溃来自进程内Qt状态组合而非测试断言。
- [PWF SYNC] 已满足B-stress/B-rest两次测试执行后的2-Action门禁；继续C/D。
- 根回归C段 `100 passed, 4 skipped`；D段 `99 passed`；两者exit 0。
- [PWF SYNC] 已满足C/D两次测试执行后的2-Action门禁；继续E-base与async独立门禁。
- 根回归E-base排除async：19文件逐进程 `184 passed`；async 42节点逐进程 `ASYNC_NODES_PASSED=42`；所有子进程exit 0。
- [PWF SYNC] 已满足E-base/async两次测试执行后的2-Action门禁；继续F/G。
- 根回归F段 `99 passed, 1 warning`；G段 `116 passed`；两者exit 0。
- [PWF SYNC] 已满足F/G两次测试执行后的2-Action门禁；继续H与最终目标门禁。
- 根回归H段 `81 passed`；最终目标模块compileall + 父/engine diff-check组合exit 0。
- Phase36根回归合计：A221 + B149 + C100 + D99 + E184 + async42 + F99 + G116 + H81 = `1091 passed, 4 skipped`，与Phase35完整覆盖总数一致。
- [PWF SYNC] 已满足H/静态两次验证后的2-Action门禁；证据齐全，下一步启动新GUI并最终同步。
- 最终diff复核确认Phase36生产范围仅为`lazy_visualization_tabs.py`内部summary组件/加载调用；测试直接锁定纯表格和既有惰性状态。
- [RUN · Phase36] 新GUI通过`python -m paleo_workbench.main`启动并持续运行（PTY session 1344）；FFmpeg初始化成功，无启动异常。
- [COMPLETE · Phase36] 纯表格首屏RED→GREEN、相关域与1091+4根回归、静态检查、GUI重启全部闭环；PWF最终同步。

## 2026-07-19 Phase 37（专业可视化交互一致性）

- 已使用brainstorming、systematic-debugging、TDD与Planning with Files；先完成engine/workbench边界诊断，不在无根因时添加页面级交互补丁。
- 初步代码索引确认engine提供可交互`WellLogCanvas`和完整`SeismicView`；workbench通过GeoVizPreviewHost嵌入，下一步逐层核对宿主、backend render与payload。
- [PWF SYNC] 已满足规划文件和引擎/宿主索引两次查看后的2-Action门禁；无生产修改。
- 根因对照完成：Host不截获事件；well preview backend漏掉原`QPainterWidget`交互包装层；seismic preview backend以`SeismicPreviewWidget`替代完整`SeismicView`，导致原engine功能退化。
- [PWF SYNC] 已满足Host/backend、Canvas/PreviewWidget、原始widget三组代码查看后的状态同步；进入brainstorming方案选择，未修改生产代码。
- 用户已确认方案 A：交互与完整功能收敛到geo-viz-engine，workbench保持薄Host；将以安装包`WellLogView`替代裸canvas，并以惰性`SeismicView(auto_load=False)`替代轻量地震preview。
- [PWF SYNC] 已依据批准设计写入Task37.1–37.4的RED/GREEN、惰性加载、取消生命周期和回归门禁；下一步读取执行规范后以测试先行实施。
- Task37.1测试Mutation：well preview改为断言`WellLogView`完整范围/复位交互包装；seismic preview移除轻量单剖面控件断言，改为断言惰性完整`SeismicView(auto_load=False)`、异步路径委托与cleanup。
- [PWF SYNC] 已满足计划/PWF与Task37.1测试两次Mutation的2-Action门禁；下一步运行精确RED。
- Task37.1首次精确测试在父仓与engine根各执行一次，均于collection报`ModuleNotFoundError: geoviz_well_log/geoviz_seismic`；未进入测试函数或生产代码，根因是当前shell未带engine多包源码路径，属于调度环境错误，不计Strike。
- [PWF SYNC] 已满足两次测试执行的2-Action门禁；下一步先复用仓内既有PYTHONPATH测试入口，再取得真实RED。
- Task37.1真实RED：带engine多包`PYTHONPATH`后，收集在`from geoviz_well_log import WellLogView`准确失败；旧安装包没有交互视图导出，验证目标缺口。
- Task37.2/37.3生产Mutation：新增包内`WellLogView`并把旧`QPainterWidget`改为兼容别名；well backend创建包装器。seismic backend保留有界prepare，但在`create_widget/render/release`局部导入完整`SeismicView(auto_load=False)`，分别委托`load_segy_async`和`cleanup`。
- [PWF SYNC] 已满足真实RED执行与两项生产实现的2-Action门禁；下一步运行精确GREEN并处理实际接口错误。
- Task37.2/37.3精确GREEN：交互well与完整seismic backend节点`2 passed`。
- 相关engine回归：LAS preview、原`QPainterWidget`兼容入口、深度滚动条、SEGY有界prepare/惰性导入和SeismicView最新generation契约共`37 passed`；无异步销毁告警。
- [PWF SYNC] 已满足两次测试执行的2-Action门禁；下一步补强真实滚轮事件断言，再跑最终相关域与静态检查。
- Task37.1鼠标交互GREEN：包装器收到真实`QWheelEvent`后，第一track的depth span缩小且垂直深度滚动条启用，精确节点`1 passed`。
- [PWF SYNC] 已满足滚轮测试Mutation与GREEN执行的2-Action门禁；Task37.1–37.3实现项已勾选，下一步进行engine全相关域与workbench薄Host链路验证。
- Task37 engine相关域：well preview/兼容页面/scrollbar、seismic preview/worker/view/UI共`58 passed`。输出含一条既有`QThread: Destroyed while thread '' is still running`，发生于包含`SeismicView()`自动合成数据的旧UI测试组合；本次backend测试使用`auto_load=False`且无该警告，仍将在最终门禁前增加preview release的明确取消回归，不能仅以此视为无关。
- Task37 workbench薄Host链路：PreviewHost、生命周期、Provider、Reader及async惰性相关筛选`46 passed, 63 deselected`；无QThread-destroyed输出，只有pytest-asyncio配置弃用警告。
- [PWF SYNC] 已满足engine/workbench两次测试执行的2-Action门禁；下一步锁定完整SeismicView的preview release取消语义并定位组合测试中的既有线程告警。
- 线程告警定位：`tests/test_seismic_ui.py`单独`1 passed`仍复现`QThread: Destroyed while thread '' is still running`。该测试直接构造默认`SeismicView()`（会启动`SyntheticWorker`）却未调用`cleanup()`或等待finished；这不是preview backend的`auto_load=False`路径，但暴露完整视图默认合成任务的测试/销毁生命周期缺口。
- [PWF SYNC] 已满足隔离engine相关域与单测定位两次测试执行的2-Action门禁；下一步审计`SyntheticWorker`取消/完成和SeismicView销毁路径，优先以可验证的生命周期修复或测试夹具清理闭环。
- 生命周期测试Mutation：仅验证图标的`test_seismic_ui`改为`SeismicView(auto_load=False)`，不再无关地启动合成QThread；这与preview backend的惰性构造策略一致，不改变默认产品`SeismicView()`行为。
- 修复验证：UI图标、完整seismic preview backend及latest-generation取消测试`10 passed`，此前`QThread: Destroyed`输出消失。
- [PWF SYNC] 已满足测试Mutation与验证执行的2-Action门禁；下一步重跑完整engine相关域，确认没有其他默认构造测试留下线程。
- 完整engine相关域重跑仍为`58 passed`但保留QThread-destroyed输出；继续隔离后`tests/test_seismic_view.py`单独`5 passed`仍复现，根因缩小到该文件的默认`SeismicView()`构造测试。
- [PWF SYNC] 已满足完整域与隔离文件两次测试执行的2-Action门禁；下一步逐个审查这些测试是否真的需要合成加载，并以`auto_load=False`消除无关线程。
- 测试清理Mutation：`test_seismic_view`中仅UI/overlay场景应改惰性构造；初次机械替换同时命中`test_seismic_view_init`的默认加载契约。已通过逐行检查在运行前发现，未把该中间态用于测试或交付；下一步以测试名锚点恢复init默认构造，并将overlay测试改为惰性构造。
- [PWF SYNC] 已满足两次测试Mutation的2-Action门禁；继续精确校正测试设置后再验证，避免将测试夹具错误误判为产品回归。
- 校正后：保留`test_seismic_view_init`对默认异步合成加载的真实契约；其余仅验证demo替换、模式、工具栏和overlay的四项测试改为`auto_load=False`。`tests/test_seismic_view.py`为`5 passed`且QThread-destroyed输出消失。
- [PWF SYNC] 已满足测试设置Mutation与精确验证的2-Action门禁；下一步最后重跑engine相关域和workbench Host链路，再执行静态门禁。
- 最终engine相关域：`58 passed`，包含真实滚轮、旧页面shim、well/seismic preview、完整SeismicView与worker generation；无QThread-destroyed输出。
- 工作台组合回归在43项后发生原生`Bus error`（trace停在既有`test_preview_async.py::test_data_page_selection_discards_obsolete_visualization`的Qt等待）；没有pytest业务断言。此模式与Phase35/36已记录的跨大量Qt测试对象累积故障一致，且本轮未改workbench线程代码；不作为本Bug Strike，策略切换为按文件/节点新进程隔离，禁止原样重复。
- [PWF SYNC] 已满足engine/workbench两次测试执行的2-Action门禁；下一步以独立进程完成Host/Provider/Reader文件和async相关节点验证，再做静态门禁。
- 隔离工作台验证首批：`test_geoviz_preview_host` 11、`test_geoviz_preview_lifecycle` 4、`test_geoviz_preview_provider` 8、`test_data_reader_panel` 44，均独立进程全绿；未再出现QThread-destroyed或Bus error。
- async节点调度的首个历史函数名已不存在，pytest只报告`not found`、未运行任何测试；这是调度清单过期而非产品失败。后续以源码中真实函数定义续跑，且不重复已通过的四个文件。
- [PWF SYNC] 已满足隔离多次测试执行的2-Action门禁；下一步核对真实async测试名并完成剩余惰性/陈旧结果节点。
- async惰性/生命周期节点按独立进程全绿：purpose路由2项，以及invalidate、retryable、clear-during-visualization、Tab激活后请求、切资产丢弃陈旧结果、slow GeoViz latest-only、payload不提前加载共7项，合计`9 passed`；无QThread-destroyed或Bus error。
- Task37.4功能回归项完成：engine 58项、workbench四个预览文件67项、async关键9项均通过。组合Bus error仅是已知Qt跨文件进程累积，已由全覆盖独立进程验证替代。
- [PWF SYNC] 已满足隔离async多次测试执行的2-Action门禁；下一步执行目标compile/diff静态门禁并请求只读最终审查。
- 静态门禁：engine preview/well-log/page兼容层`compileall`通过；父仓和engine `git diff --check`均exit 0、无输出。
- 范围审计：父仓仍含用户既有Phase32–36及未跟踪设置/文档文件；本轮新增/变更限定engine的`WellLogView`、well/seismic preview backend、兼容页面入口及其测试。未stage/commit/push，也未触碰`SCRATCH/`或历史docs。
- [PWF SYNC] 已满足compileall/diff-check两次验证的2-Action门禁；下一步请求Task37只读最终审查，然后重启GUI交付。
- Task37只读终审：运行时Critical/Important为0；确认Seismic backend无顶层`SeismicView`导入、create时才`auto_load=False`、render/release委托完整视图的异步/cleanup，WellLogView保持wheel/zoom/pan/crosshair/ruler且旧`QPainterWidget`为同类兼容别名。
- 审查发现发布限制：新增`well_log_view.py`在当前engine dirty submodule中仍未跟踪。用户未授权stage/commit，故不修改Git索引；当前工作区运行无缺失，未来clean checkout/合并必须将该文件提交并更新父仓gitlink。
- [PWF SYNC] 最终审查已写入；下一步启动GUI。工作流按用户既有“Keep as-is、无commit/stage/push”授权结束，不执行finishing技能的merge/PR/discard选项。
- [RUN · Phase37] `QT_QPA_PLATFORM=xcb python -m paleo_workbench.main`已在图形会话启动（PTY session 51797）；5秒健康轮询仅输出Qt FFmpeg初始化信息，进程持续运行，无Python异常或QThread-destroyed输出。
- [COMPLETE · Phase37] 测井交互包装器与完整惰性地震视图已在共享工作区交付；engine 58项、workbench独立文件67项和async关键9项回归、compile/diff-check、只读终审及GUI启动均完成。PWF三文件同步；未stage/commit/push。
- [RUN · Phase37-fix] 用户反馈“地震三维体不显示”；本地复现确认 `SeismicView.load_demo()` / `load_segy_async()` 后 `Renderer3D._mode` 仍停在 `"planes"`，导致 volume item 被默认隐藏。
- [PWF SYNC] 已记录新的回归点并按2-Action门禁同步进度；下一步修正默认3D模式并补回归测试。
- [RUN · Phase37-fix] 已完成默认 3D 模式修正回归：`tests/test_seismic_view.py` 5 passed，`tests/test_geoviz_seismic_preview.py` 2 passed。
- [PWF SYNC] 当前修复链路已验证，下一步做静态检查并更新计划状态。
- [RUN · Phase37-fix2] 预览链路回归通过：`tests/test_geoviz_seismic_preview.py` 2 passed，`tests/test_seismic_view.py` 5 passed。
- [PWF SYNC] 已满足两次测试执行后的进度同步门禁；下一步执行静态检查并收尾。

## 2026-07-19 Phase 38（app.py God-class 重构）

- 已启动 Phase 38，针对 `app.py` 中的 `PaleoWorkbenchWindow` God-class 进行拆分，解决大文件职责堆叠和强耦合接线问题。
- [PWF SYNC] 已将设计与计划更新至 `task_plan.md`，准备实施。
