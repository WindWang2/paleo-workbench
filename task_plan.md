# Task Plan: Paleogeography Workbench — UI Page Implementation

> **Updated:** 2026-07-10
> **Goal:** Implement real content for all 9 AppShell pages, then upgrade DataPage into a project-wide data/result/file management center, then wire up project file lifecycle, then harden DataPage for 2000+ assets (UI + performance).

## Project Status: 9/9 pages + Data Management Center + Project Management V1 complete; **Data Page UI/Perf Optimization merged to main** (PR #1). ~385 tests passing.

## Current Architecture

- **AppShell** (4-zone): menu bar (36px) + header toolbar (38px) + icon rail (60px, 9 nav, gradient bg, SVG icons) + text sidebar (248px) + QStackedWidget (9 pages) + status bar (24px)
- **Design tokens** in `paleo_workbench/ui/tokens.py` — colors, fonts, dimensions, QSS_TEMPLATE, step colors/labels, status text, resource labels/units
- **Global QSS** applied in `main.py` via `app.setStyleSheet(tokens.QSS_TEMPLATE)`
- **Pages package** at `paleo_workbench/ui/pages/`
- **DataPage (post Phase 15):** `DataWorkspace` (virtual `QTableView` + multi-format reader) + floating catalog/actions; `FilterIndex`; serial async `PreviewRequestController` + LRU `PreviewCache`; async import via `QThread`

## 数据管理思维（改数据页时先读）

> 完整版见 `findings.md` → **「数据管理思维 (Data Management Mindset)」**。下面是压缩决策版。

| 原则 | 含义 |
|------|------|
| **工程级中枢** | 管全部输入 / 参考 / 成果文件面，不是单类型资源摘要 |
| **登记 ≠ 磁盘** | 工程登记路径与元数据；移出不删盘；缺失标 `missing` |
| **工作台隐喻** | 表 + 阅读器第一视口；目录/操作为浮动 overlay，禁止三列固定卡片回潮 |
| **选中即读** | 支持格式有界预览；不支持则 message；深度可视化去专用页 |
| **非破坏默认** | 不默认拷贝入库、不删源文件、不在数据页做全文件编辑 |
| **规模体感** | 2000+：虚拟表、内存筛选、串行异步预览 + 缓存、导入一次刷新 |
| **下游一致** | 测井/地震/制备/编图消费同一 `ProjectDocument` 资产 |

**决策检查（任一否 → 重想方案）：** 只管理登记？不碰磁盘删除？表/阅读器仍是主角？大列表不堵 UI？导入一次刷新？缺失/不支持可解释？

## Phases

### Phase 1: AppShell Skeleton — ✅ COMPLETE
- 4-zone layout, 9-page navigation, SVG icons, gradient rail, design tokens, global QSS
- Commits: `01b3a9e`..`c7352e1`, then icon fixes `6222a80`..`203c457`
- Tests: 57 (all passing)
- Spec: `docs/superpowers/specs/2026-07-05-appshell-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-appshell.md`

### Phase 2: 首页 Dashboard — ✅ COMPLETE
- WorkflowProgress (6-step colored badges + status), RecentActivityCard (two-column entries + scroll), DataCompletenessCard (resource readiness + unit suffixes)
- M3 polish: connecting lines, two-column activity, unit suffixes, QScrollArea
- Commits: `8f8a1f9`..`adf0acc`, polish `c507629`, fix `96c88f9`
- Tests: +23 new (80 total at completion, now 95 with DataPage)
- Spec: `docs/superpowers/specs/2026-07-05-homepage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-homepage.md`

### Phase 3: 数据页 DataPage — ✅ COMPLETE
- ResourceSummaryBar (counts + readiness), ResourceTable (QTableWidget, 5 cols, type mapping, status coloring), ActionPanel (import/convert buttons)
- Commits: `ea255c4`..`28a3a04`, fix `bd8d7be`
- Tests: +14 new (95 total)
- Spec: `docs/superpowers/specs/2026-07-05-datapage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-datapage.md`

### Phase 4: 制备页 PreparationPage — ✅ COMPLETE
- FactorTaskPanel (task list + horizon/method header + summary footer), FactorPreviewGrid (completed factor map cards with value range + R²), BoundaryPanel (probability threshold / smoothing / min area form)
- Commits: `054b8f5`..`446ee05`, label fix `a438167`
- Tests: +24 new (119 total)
- Spec: `docs/superpowers/specs/2026-07-05-preparationpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-preparationpage.md`

### Phase 5: 成图审核页 ReviewExportPage — ✅ COMPLETE
- ActionHeader (title + 3 action buttons + rules chips), QCIssueTable (one row per QC rule, derived 通过/警告/待处理 result + colored cell), ResultSummary (pass/warning/error counts + advisory + export artifacts list); shared derive_rule_result helper (error precedence)
- Commits: `a70a19f`..`3ad80ce`, refactor `1bdd23d`
- Tests: +30 new (149 total)
- Spec: `docs/superpowers/specs/2026-07-05-reviewexportpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-reviewexportpage.md`

### Phase 6: 层序格架页 SequenceFrameworkPage — ✅ COMPLETE
- SequenceTargetPanel (target horizon + interpretation version + scheme selector + applicable well/seismic counts), SequenceBoundaryTable (sequence boundary rows + empty state), SequenceSchemeSummary (scheme + boundary count + systems tract labels + save action)
- Tests: +12 new (161 total)
- Spec: `docs/superpowers/specs/2026-07-05-sequenceframeworkpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-sequenceframeworkpage.md`

### Phase 7: 编图页 MappingPage — ✅ COMPLETE
- MapDocumentPanel (active map document + horizon + polygon/well counts + list), MapCanvasPanel (embedded geo-viz-engine `PaleoMapCanvas` loading facies polygons and well overlays), MapChromePanel (title/elements summary + draft/review actions)
- Tests: +11 new (172 total)
- Spec: `docs/superpowers/specs/2026-07-05-mappingpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-mappingpage.md`

### Phase 8: 测井预测页 WellLogPredictionPage — ✅ COMPLETE
- PredictionTaskPanel (active prediction task + status/probability/review counts + list), WellLogCanvasPanel (embedded geo-viz-engine `WellLogCanvas` fed by deterministic `PredictionTask` → `WellLogData` conversion), PredictionEvidencePanel (evidence weights + mock/replaceable status + actions)
- Tests: +12 new (184 total)
- Spec: `docs/superpowers/specs/2026-07-05-welllogpredictionpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-welllogpredictionpage.md`

### Phase 9: 地震预测页 SeismicPredictionPage — ✅ COMPLETE
- SeismicTaskPanel (active prediction task + status/probability + list), SeismicViewPanel (embedded geo-viz-engine `SeismicView` fed by deterministic `PredictionTask` → seismic volume conversion), SeismicControlPanel (volume shape + mode + mock/replaceable status + actions)
- Tests: +12 new (196 total)
- Spec: `docs/superpowers/specs/2026-07-05-seismicpredictionpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-seismicpredictionpage.md`

### Phase 10: 可视化页 VisualizationPage — ✅ COMPLETE
- VisualizationSummaryPanel (resource/prediction/map counts), CompositeVisualizationPanel (WellLogCanvas + SeismicView + CrossWellWidget tabs), VisualizationTracePanel (active task/map + actions)
- Tests: +9 new (205 total)
- Spec: `docs/superpowers/specs/2026-07-05-visualizationpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-05-visualizationpage.md`

### Phase 11: 数据管理中心 Data Management Center — ✅ COMPLETE
- Upgrade DataPage from resource summary/table/actions into a project-wide data, result, and file management center with import, catalog filters, dedupe, details, and lightweight previews.
- Added `DataImportService` with deterministic path-first/checksum-second dedupe.
- Added `PreviewState` helpers for resources and export artifacts; PDF uses first-page thumbnails while LAS/SEGY/PPT/Excel remain non-deep-loaded summaries.
- Rebuilt DataPage around `DataCatalogPanel`, `DataAssetTable`, `DataDetailPanel`, and expanded `ActionPanel`.
- Wired file/folder import dialog seams and AppShell/PaleoWorkbenchWindow project/artifact propagation.
- Spec: `docs/superpowers/specs/2026-07-06-datamanagementpage-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-datamanagementpage.md`
- Tests: +27 new/updated in this phase, 239 total

### Phase 12: 数据预览格式增强 Data Preview Formats — ✅ COMPLETE
- Added bounded TXT/XML/CSV/DAT preview with maximum 8192 bytes and 20 lines.
- Added inline image thumbnails in `DataDetailPanel` using `QPixmap`, with invalid-image warnings.
- Added PDF first-page thumbnail preview; kept LAS/SEGY/PPT/Excel/WLP/DFB safe summary-only by default.
- Added DataPage selection-flow coverage for imported text and image preview rendering.
- Spec: `docs/superpowers/specs/2026-07-06-data-preview-formats-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-data-preview-formats.md`
- Tests: +9 new/updated in this phase, 248 total

### Phase 13: 数据页 V2 交互完善 Data Page V2 Interaction Polish — ✅ COMPLETE
- Replaced the fixed-width data preview area with a horizontal splitter so catalog, asset table, and preview/detail panel can be resized.
- Replaced PDF thumbnail-only rendering with a page preview panel that supports previous/next page navigation and page count display.
- Wired `重新扫描`, `移出项目`, and `打开目录` action buttons to concrete DataPage behaviors.
- Added import/action status feedback in the action panel.
- Removed the `ActionHeader` stylesheet padding rule that caused Qt runtime stylesheet parse warnings.
- Replaced the left text sidebar placeholder with real page context sections; the Data page context now shows resource counts, artifact counts, current selection, reader capabilities, and operations.
- Tests: +7 new/updated in this phase, 259 total

### Phase 14: 项目管理 V1 Project Management — ✅ COMPLETE
- Made the top-level toolbar actions real workflows: 新建工程 (new empty project), 打开工程 (file picker → load `.paleo.json`), 保存工程 (save / save-as with `.paleo.json` normalization), 工程属性 (read-only QMessageBox with 7 fields).
- Window-level controller in `PaleoWorkbenchWindow`; shell rebuilt on new/open via `_refresh_shell` + `_apply_project_to_shell`; signal wiring centralized in `_wire_toolbar()` (called from both `__init__` and `_refresh_shell`).
- Non-destructive error handling: open failures (JSONDecodeError/ValidationError/OSError) return False with current project preserved; save OSError → error dialog + None return.
- Also fixed a baseline break: 07-06 接入的 SeismicPredictionPage 依赖 scipy 等 geoviz 包但未声明, 导致 36 个测试收集失败; added `requirements-geoviz.txt` + completed `pythonpath` to restore 259-test baseline.
- Commits: `397993e` (baseline fix), `336bf2e`..`4cee4e1` (5 SDD tasks), cleanup `d…` (drop redundant FileNotFoundError).
- Tests: +24 new (283 total; was 259 after baseline fix)
- Spec: `docs/superpowers/specs/2026-07-07-project-management-design.md`
- Plan: `docs/superpowers/plans/2026-07-07-project-management.md`

### Phase 15: 数据页 UI/性能优化 Data Page UI & Performance — ✅ COMPLETE (merged PR #1)

Surgical performance pass for 2000+ assets; floating-panel workspace layout preserved.

| Slice | Work | Key modules |
|-------|------|-------------|
| S1 | Virtual table: `QTableWidget` → `QTableView` + `AssetTableModel` | `asset_table_model.py`, `data_table_columns.py`, `data_asset_table.py` |
| S2 | `FilterIndex` + 180ms search debounce; single `set_assets_filtered` reset | `filter_index.py`, `data_toolbar.py` |
| S3 | Async preview + generation tokens + loading; rescan invalidates in-flight | `preview_worker.py`, `data_reader_panel.py`, `data_page.py` |
| S4 | UI-thread `PreviewCache` LRU (32); pure `PreviewProvider` | `preview_cache.py` |
| S5 | Import batch refresh (one model reset; no reader rebuild) | `data_page._apply_import_report` |
| S6 | Checkable catalog/reader toggles; page margins 12px | `data_toolbar.py`, `tokens.py` |
| Review fix | Serial latest-only preview queue + `shutdown()` on close/deleteLater | `preview_worker.py`, `data_page.py` |

- Approach: balanced surgical (virtualize + index + async cache), not layout redesign
- Spec: `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-datapage-ui-perf-optimization.md`
- Branch: `feature/datapage-ui-perf` → merged `main` as PR #1 (`bc8b68b`)
- Tests: ~385 passed at merge

## Known Follow-up Items (Minor, non-blocking)

| # | Item | Source |
|---|------|--------|
| 1 | `save_project` OSError branch lacks a dedicated test (only `save_project_as` tested) | Project Management V1 final review |
| 2 | `_on_open_project` error message generic — doesn't distinguish missing file vs corrupt JSON | Project Management V1 final review |
| 3 | Test magic index `page_stack.widget(1)` for DataPage (pre-existing pattern) | Project Management V1 final review |
| 4 | Floating catalog tab vs toolbar checked-state can desync if tab used directly | Data page perf final review |
| 5 | Image/PDF decode still on UI thread after async path returns path-only result | Data page perf final review |
| 6 | `FilterIndex.rebuild` still runs on pure search/category (could rebuild only on asset list change) | Data page perf final review |
| 7 | Search haystack uses raw `type` (`well_log`), not Chinese labels | Data page perf final review |

## Page Progress Matrix

| # | Page | Status | Tests | Spec | Plan |
|---|------|--------|-------|------|------|
| 1 | 首页 | ✅ Complete | 23 | ✅ | ✅ |
| 2 | 数据 | ✅ Complete | 14 | ✅ | ✅ |
| 3 | 测井预测 | ✅ Complete | 12 | ✅ | ✅ |
| 4 | 地震预测 | ✅ Complete | 12 | ✅ | ✅ |
| 5 | 层序格架 | ✅ Complete | 12 | ✅ | ✅ |
| 6 | 可视化 | ✅ Complete | 9 | ✅ | ✅ |
| 7 | 制备 | ✅ Complete | 24 | ✅ | ✅ |
| 8 | 编图 | ✅ Complete | 11 | ✅ | ✅ |
| 9 | 成图审核 | ✅ Complete | 30 | ✅ | ✅ |
| 11 | 数据管理中心升级 | ✅ Complete | 27 | ✅ | ✅ |
| 12 | 数据多格式预览 | ✅ Complete | 9 | ✅ | ✅ |
| 13 | 数据页 V2 交互完善 | ✅ Complete | 7 | ✅ | ✅ |
| 14 | 项目管理 V1 | ✅ Complete | 24 | ✅ | ✅ |
| 15 | 数据页 UI/性能优化 | ✅ Complete (PR #1) | ~100+ | ✅ | ✅ |

## Test History

| Date | Tests | Status |
|------|-------|--------|
| 2026-07-05 (AppShell) | 57 | ✅ |
| 2026-07-05 (HomePage) | 80 | ✅ |
| 2026-07-05 (HomePage polish) | 81 | ✅ |
| 2026-07-05 (DataPage) | 95 | ✅ |
| 2026-07-05 (PreparationPage) | 119 | ✅ |
| 2026-07-05 (ReviewExportPage) | 149 | ✅ |
| 2026-07-05 (SequenceFrameworkPage) | 161 | ✅ |
| 2026-07-05 (MappingPage) | 172 | ✅ |
| 2026-07-05 (WellLogPredictionPage) | 184 | ✅ |
| 2026-07-05 (SeismicPredictionPage) | 196 | ✅ |
| 2026-07-05 (VisualizationPage) | 205 | ✅ |
| 2026-07-06 (Post-implementation hardening) | 206 | ✅ |
| 2026-07-06 (Post-implementation hardening 2) | 212 | ✅ |
| 2026-07-06 (Preflight warning cleanup) | 212 | ✅ |
| 2026-07-06 (Data Management Center) | 239 | ✅ |
| 2026-07-06 (Data Preview Formats) | 248 | ✅ |
| 2026-07-06 (Data Page V2 Polish) | 259 | ✅ |
| 2026-07-07 (Project Management V1) | 283 | ✅ |
| 2026-07-10 (Data page redesign + preview formats era) | ~350+ | ✅ |
| 2026-07-10 (Data Page UI/Perf Optimization, PR #1) | ~385 | ✅ |
