# Task Plan: Paleogeography Workbench — UI Page Implementation

> **Updated:** 2026-07-17
> **Goal:** Ship a demo-ready paleogeography desktop workbench (9 AppShell pages, data center, project lifecycle, mapping editor, geo-viz previews). Current focus after Phase 21 / B→A→C data overhaul: **stability hardening** (full-project audit fixes) and **interactive data previews** (SEGY slice scrub).

## Project Status

On `main` (+ local WIP): 9/9 pages + Data Management + Mapping + Visualization + sample pipeline + polish + audit (22) + SEGY scrub (23) + **Phase 24 viz modularization / engine alignment** (thin hosts + facade loaders).

`map_edit_core` C++ + `shapely` available for topology merge/split.

## Current Architecture

- **Subproject `geo-viz-engine/`** (git submodule → `WindWang2/geo-viz-engine`): **visualization algorithm & widget library** for the workbench. Pip-installable packages (`geoviz_*`) + top-level `geoviz` facade; consumed via editable installs / `pythonpath` (see `requirements-geoviz.txt`, root `pyproject.toml`). Workbench owns project lifecycle / UI pages; engine owns LAS/SEGY/map/plot render pipelines and prepared previews. Prefer engine-side fixes for viz bugs; workbench wires `GeoVizEngine` / `VizAdapter` only.
- **AppShell** (4-zone): menu bar (36px) + header toolbar (36px post Phase 19) + icon rail (60px, 9 nav, gradient bg, SVG icons) + text sidebar (248px) + QStackedWidget (9 pages) + status bar (24px)
- **Design tokens** in `paleo_workbench/ui/tokens.py` — colors, fonts, dimensions, density scale (`SPACE_*`, `PAGE_MARGIN`, `CONTROL_HEIGHT*`), interaction colors, QSS_TEMPLATE, step colors/labels, status text, resource labels/units
- **Global QSS** applied in `main.py` via `app.setStyleSheet(tokens.QSS_TEMPLATE)` (buttons/tables/focus/PanelCard/ToolbarStrip/EmptyState)
- **Shared UI widgets** (post Phase 19): `PanelCard`, `SectionHeader`, `ToolbarStrip`, `EmptyStateLabel`, `PageScaffold` under `paleo_workbench/ui/widgets/`
- **Pages package** at `paleo_workbench/ui/pages/`
- **DataPage (post Phase A/B/C):** DEVONthink 3-pane (`NavigationTree` | asset table | reader+inspector); multimodal previews; concurrent scan; async `PreviewRequestController` + LRU + **project-local `.preview_cache/`** (horizon/tops/well-head); SEGY via `geoviz` facade with **slice scrub slider** (Phase 23)
- **MappingPage (post Phase 16 + 20):** GIS shell — toolbar · layer tree · `MapEditView`/`MapEditScene` · attribute table; save draft to `PaleoMapDocument`; geometry via `map_edit_api` (+ optional C++ `map_edit_core`); dirty-doc guards on refresh (Phase 22)
- **Visualization (post Phase 17):** pure `paleo_workbench/viz/` (`VizRef` / `VizPayload` / `VizAdapter`); data-page jump → page index 5 + `open_ref`; composite tabs 测井/地震/连井/古地理; prediction mock fallback when no ref
- **Sample pipeline (post Phase 18a–18c):** `paleo_workbench/pipeline/` bootstrap + asset bind + `compile_map_draft`; CLI `--with-demo-tasks` / `--with-map-draft`; toolbar 「打开样例工程」 + mapping 「生成演示草稿」; bootstrap seeds full `workflow_steps` (Phase 22)
- **Project I/O (Phase 22):** atomic save, `meta.updated_at`, resource/artifact/**reference_layer** path relativize/resolve; QC status derives error; GeoJSON adapter exports real features

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

### Phase 16: 编图编辑器 V1 Mapping Editor — ✅ COMPLETE (merged PR #3)

GIS-shell vector editor replacing display-only three-column mapping page.

| Slice | Work |
|-------|------|
| Schema I/O | `mapping/geometry_schema.py`, `document_io.py`; `line_features` / `label_features` on `PaleoMapDocument` |
| GIS shell | Toolbar · layer tree · attribute table · `MapEditView` |
| Scene | Facies/well/line/label items; select/move/vertex; undo stack |
| Topology | Snap + self-intersection warnings via `map_edit_api` |
| Save | Draft write-back to active `PaleoMapDocument` |
| Native | Optional C++ `map_edit_core` (pybind11) under `native/map_edit_core/` |

- Spec: `docs/superpowers/specs/2026-07-10-mapping-editor-v1-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-mapping-editor-v1.md`
- PR #3 → `2e98da6`; ~449 tests at merge
- Build C++: `pip install -e native/map_edit_core` (see `mapping/CPP_EXTENSION.md`)

### Phase 17: 可视化 geo-viz 适配器 Visualization geo-viz Adapter — ✅ COMPLETE

Shared adapter turns project LAS / SEGY / paleomap assets into geo-viz payloads; data page jumps to visualization; visualization loads real assets with prediction mock fallback.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | Pure `viz/` package: models, LAS/SEGY/map loaders, `VizAdapter` | `paleo_workbench/viz/*`, `tests/test_viz_adapter.py` |
| T2 | Visualization `open_ref` + 古地理 tab + summary list + trace refresh | `visualization_page.py`, `composite_visualization_panel.py`, summary/trace panels |
| T3 | Data page 「在可视化中打开」 + window jump to index 5 | `action_panel.py`, `data_page.py`, `app.py` |
| T4 | Message clears canvas; `from_prediction` soft-fail; full suite + planning docs | composite clear, adapter hardening |

- Spec: `docs/superpowers/specs/2026-07-10-visualization-geoviz-adapter-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-visualization-geoviz-adapter.md`
- Branch: `feature/viz-geoviz-adapter` → **merged `main`** (fast-forward `6d8a131`)
- Bounds: LAS max 12 curves / 2000 samples; SEGY product ≤ 64³
- Tests: **501 passed** (post-merge; shapely declared + installed)

### Phase 18a: 样例工程引导 Sample Project Bootstrap — ✅ COMPLETE

Scan repo `data/` into a loadable `.paleo.json` sample project (CLI + toolbar); large-file checksum skip for SEGY-class assets.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | Skip large-file checksums in `scan_resources` | `paleo_workbench` scan path |
| T2 | `bootstrap_sample_project` pure pipeline | `paleo_workbench/pipeline/` |
| T3 | CLI entry for bootstrap | `python -m paleo_workbench.pipeline` |
| T4–T5 | Toolbar 「打开样例工程」 + workbench open path | header toolbar / `app.py` |

- Spec: `docs/superpowers/specs/2026-07-10-e2e-real-data-pipeline-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-e2e-real-data-pipeline-18a.md`
- Branch: `feature/e2e-pipeline-18a`
- Smoke: `python -m paleo_workbench.pipeline --data-root data --out /tmp/sample.paleo.json` → **200 resources**
- Tests: **509 passed**, 4 skipped (at 18a close)

### Phase 18b: 预测资产绑定 Prediction Asset Binding — ✅ COMPLETE

Bind prediction tasks to real LAS/SEGY `ResourceItem`s via `input_refs`; canvases load through `VizAdapter` with mock fallback when unbound; sample open seeds a demo prediction.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | `bind_prediction_assets` / `suggest_assets_for_demo` / `ensure_demo_prediction` | `pipeline/assets.py` |
| T2 | Well log + seismic canvases: bound path → VizAdapter, unbound → mock | `well_log_canvas_panel.py`, `seismic_view_panel.py` |
| T3 | Sample open + CLI `--with-demo-tasks` seed bound prediction | `app.py`, `pipeline/__main__.py` |

### Phase 18c: 演示相带草稿 Demo Map Draft — ✅ COMPLETE

Deterministic `compile_map_draft` always produces an editable paleomap (placeholder when empty); mapping toolbar 「生成演示草稿」; CLI `--with-map-draft`.

| Slice | Work | Key modules |
|-------|------|-------------|
| T4 | `compile_map_draft` pure compiler (polygons + wells + demo flags) | `pipeline/compile_map.py` |
| T5 | Mapping toolbar generates demo draft + page refresh | `map_edit_toolbar.py`, `app.py` |
| T6 | CLI `--with-map-draft`, docs, full suite | `pipeline/__main__.py` |

- Spec: `docs/superpowers/specs/2026-07-10-e2e-real-data-pipeline-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-e2e-pipeline-18b-18c.md`
- Branch: `feature/e2e-pipeline-18b-18c`
- Smoke: `python -m paleo_workbench.pipeline --data-root data --out /tmp/demo18.paleo.json --with-demo-tasks --with-map-draft` → **200 resources** + prediction_tasks + paleomap_documents
- Tests: **533 passed**, 4 skipped

### Phase 19: UI 视觉抛光 UI Visual Polish — ✅ COMPLETE

Demo-ready global visual system: density tokens, richer QSS, five shared widgets, shell + high-traffic page adoption—without changing business logic.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | Density tokens + interaction colors + expanded `QSS_TEMPLATE` | `ui/tokens.py`, `tests/test_tokens.py` |
| T2 | Five shared widgets | `ui/widgets/` (`PanelCard`, `SectionHeader`, `ToolbarStrip`, `EmptyStateLabel`, `PageScaffold`) |
| T3 | Denser AppShell chrome (toolbar height 36, margins/spacing) | `header_toolbar.py`, `sidebar.py`, shell chrome |
| T4 | Density on home / data / mapping chrome | `home_page.py`, data chrome, map toolbar |
| T5 | Unify page outer margins to `PAGE_MARGIN` | all 9 page roots |
| T6 | Adopt `PanelCard` / `EmptyStateLabel` objectNames; drop duplicate local QSS | activity/completeness cards, result/scheme/action panels, empty labels |

- Brief: density tokens (`SPACE_*`, `PAGE_MARGIN`, `CONTROL_HEIGHT*`), richer global QSS (button states, tables, focus, panel/toolbar/empty selectors), 5 shared widgets, shell + page density, `PanelCard`/`EmptyState` objectName adoption
- Spec: `docs/superpowers/specs/2026-07-10-ui-visual-polish-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-ui-visual-polish.md`
- Branch: `feature/ui-visual-polish`
- Tests: **544 passed**, 4 skipped

### Phase 20: 编图 GIS 壳抛光 Mapping GIS Shell Polish — ✅ COMPLETE

Make the 编图 page feel like a compact professional GIS shell: grouped toolbar, unified dock chrome, denser spacing, clearer status coordinates—without changing tool / topology / save behavior.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | Mapping + status QSS selectors in `QSS_TEMPLATE` | `ui/tokens.py`, `tests/test_tokens.py` |
| T2 | Non-interactive toolbar separators between visual groups | `map_edit_toolbar.py` |
| T3 | Unified layer tree + attribute dock chrome (objectNames, drop local QSS) | `map_layer_tree.py`, `map_attribute_table.py` |
| T4 | Canvas/chrome dock QSS + denser mapping page spacing | `map_canvas_panel.py`, `map_chrome_panel.py`, `mapping_page.py` |
| T5 | Status bar coordinate zone (`StatusCoordLabel`) | `status_bar.py` |
| T6 | Full suite + planning docs | `task_plan.md`, `progress.md` |

- Brief: global QSS for MapEditToolbar / MapLayerTree / MapAttributeTable / MapCanvasPanel / MapChromePanel / StatusCoordLabel; toolbar separators (order unchanged); docks use objectNames over local card CSS; logic freeze on edit/topology/save
- Spec: `docs/superpowers/specs/2026-07-10-mapping-gis-shell-polish-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-mapping-gis-shell-polish.md`
- Branch: `feature/mapping-gis-shell-polish`
- Tests: **549 passed**, 4 skipped

### Phase 21: 数据页压测 + 热点修复 Data Page Stress + Hotspots — ✅ COMPLETE

Reproducible DataPage stress harness (S1–S4 with printed timings) and production alignment of import scan with large-file checksum skip; no CI wall-clock gates; second UI hotspot not needed after measurement.

| Slice | Work | Key modules |
|-------|------|-------------|
| T1 | Timing + synthetic fixture helpers | `tests/perf/` |
| T2 | Stress scenarios S1–S4 with `[datapage-stress]` logs | `tests/test_datapage_stress.py` |
| T3 | Import path: `skip_checksum_over_bytes` (default 50 MiB) via `import_files` / `import_folder` | `paleo_workbench/resources/import_service.py` |
| T4 | Optional second hotspot — **SKIPPED** (S1 update ~4ms, S3 ~3ms at N=2000) | — |
| T5 | Full suite + planning docs | `task_plan.md`, `progress.md` |

- Brief: test-only stress harness (S1 set_assets / S2 filter / S3 rapid select / S4 import_folder); production win is large-file import checksum skip aligned with bootstrap scanner policy; no second UI hot-path change required
- Spec: `docs/superpowers/specs/2026-07-10-datapage-stress-hotspots-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-datapage-stress-hotspots.md`
- Branch: `feature/datapage-stress-hotspots`
- Sample timings (local, post-import-fix): S1_update n=2000 ~3.7ms; S2_filter ~0.2–0.5ms; S3_rapid_select n=30 ~2.7ms; S4_import_folder n=300 ~24.6ms
- Tests: **557 passed**, 4 skipped

### Phase B: 多模态预览扩展 Multimodal Preview Formats — ✅ COMPLETE

Sub-project B of the data page overhaul (B multimodal → A DEVONthink 3-pane → C performance). Added 4 new inline preview formats to the DataPage reader panel, all reusing the existing pipeline (worker thread + LRU cache + generation invalidation):

| Format | mode | Widget | Notes |
|--------|------|--------|-------|
| Markdown/HTML | `rich_text` | `RichTextPreviewWidget(QTextBrowser)` | md→HTML via `markdown` lib; network resources blocked, local file images allowed |
| JSON/GeoJSON | `json_tree` | `JsonTreePreviewWidget(QTreeView)` | arrays >100 collapse to "[N items]" lazy-expanded nodes; 5MB parse cap |
| GeoTIFF | `geotiff` | `GeoTiffPreviewWidget` | rasterio CRS/bounds/dims + decimated PNG thumbnail (Pillow); 3-path fallback to image mode |
| Audio | `media` | `MediaPreviewWidget(QMediaPlayer)` | wav/mp3/flac/ogg/m4a; play/pause/seek/volume; graceful codec-missing message |

New deps: `markdown`, `rasterio`, `pillow` (declared in pyproject). Worker preload extended for geotiff mode. Classifier recognizes md/markdown/htm/html.

- Spec: `docs/superpowers/specs/2026-07-12-multimodal-preview-design.md`
- Plan: `docs/superpowers/plans/2026-07-12-multimodal-preview.md`
- Branch: `main`
- Commits: `8eaec39`..`13643e4` (8 SDD tasks + 3 fixes: JSON bytes-first truncation, geotiff preload, Pillow dep + dead-code cleanup)
- Tests: 582 → **612** (+30 new), all passing (1 upstream rasterio/numpy DeprecationWarning)

### Phase A: DEVONthink 三栏重构 Three-Pane Layout — ✅ COMPLETE

Sub-project A of the data page overhaul. Restructured DataPage from 2-splitter + floating-overlay-panel layout into a fixed DEVONthink-style 3-pane layout:

| Pane | Component | Notes |
|------|-----------|-------|
| Left | NavigationTree (new QTreeWidget) | Smart-group tree: 全部 + 4 groups (输入数据/成果/参考资料/异常) + type leaves with count badges; emits category_changed (same CATEGORIES contract as FilterIndex) |
| Center | DataAssetTable (unchanged) | Moved into splitter middle segment |
| Right (vertical split) | DataReaderPanel (preview, unchanged) + InspectorPanel (new) | Inspector shows read-only metadata (name/path/type/format/CRS/tags/checksum/status/size/source/external) |

Action buttons (remove/open-folder/visualize) + import status moved to DataToolbar. Deleted: DataCatalogPanel, ActionPanel, FloatingPanel. Extracted `compute_category_counts` + moved `CATEGORIES` to filter_index.py.

- Spec: `docs/superpowers/specs/2026-07-13-devonthink-three-pane-design.md`
- Plan: `docs/superpowers/plans/2026-07-13-devonthink-three-pane.md`
- Commits: `7623a33`..`3d82879` (5 SDD tasks + 1 dead-code cleanup)
- Tests: 612 → **625** (legacy panel tests deleted; new tree/inspector/workspace/filter tests added)
- Final review: APPROVED, ship. Minor deferred: reader-btn label says 阅读器 but hides whole right column; lost selection-status text; 测井参考 has no type leaf.

### Phase C: 并发扫描 Concurrent Resource Scan — ✅ COMPLETE

Sub-project C of the data page overhaul. The only remaining real perf gap after Phase 15 (virtual scroll + debounced search) and Phase 21 (checksum skip + stress harness): `scan_resources` was fully serial. Parallelized via `ThreadPoolExecutor` (stat + classify + checksum per-file concurrent; GIL released by stat/IO/hashlib). Added S5 stress scenario (N=10000, env-gated `DATAPAGE_STRESS_S5=1`) for validation.

Virtual scrolling and search debounce/index were already done in Phase 15/21 and measured as non-hotspots (S1=4ms, S2=0.5ms at N=2000) — no work needed.

- Spec: `docs/superpowers/specs/2026-07-13-concurrent-scan-design.md`
- Plan: `docs/superpowers/plans/2026-07-13-concurrent-scan.md`
- Commits: `ae69a8d`..`8ae4287` (2 SDD tasks)
- Tests: 625 → **632** (+6 scanner unit tests + S5 stress)
- Final review: approved (self-review; both tasks individually reviewed clean)

**Data page overhaul (B→A→C) complete.**

### Phase 22: 全项目审计加固 Full-Project Audit Hardening — ✅ COMPLETE

Line-level audit of `paleo_workbench` + `geo-viz-engine` packages (3 parallel reviewers + critical-item verification). Fixed high-confidence bugs: data integrity, crashes, leaks, silent data loss.

| Area | Fixes |
|------|--------|
| **geo-viz** | DTW pen `Qt.PenStyle.DashLine`; multi-ring `MovePolygonCmd` by vertex id; `geoviz_map` ScreenPathCache pan/size invalidation; sonic→true TWT (×2); curve meta keeps `unit`; contour major by level index |
| **project/mapping** | Facies/well attributes preserved on draft save; reference_layer path I/O; atomic project write + `updated_at`; GDAL dataset release; CRS normalize `EPSG:n / label`; closed-ring `insert_vertex`; SEGY single-pass preview load |
| **workflow/export** | QC unknown-id `ValueError`; status `error` when severity error; real GeoJSON export from layers; factor_tasks → mapping shelf; bootstrap `create_compilation_run` steps |
| **UI lifecycle** | Import QThread shutdown on page destroy; mapping preserve active doc + dirty; document switch Save/Discard/Cancel; project save flushes map draft; media stop on preview switch; page fade clears previous opacity; new/open UI confirm |

- Commits: parent `66b7436`, geo-viz-engine `1bf80d34` (both pushed to `origin/main`)
- Tests (sampled): workbench lifecycle/mapping/adapters **56+148+10**; geoviz edit/qpainter **72 / 60**
- Remaining open (not in this phase): Seismic Auto-Tie signal dead-end; hidden-layer hit-test; demo draft always appends; path `..` escape on resolve

### Phase 23: 数据页地震剖面滑条 SEGY Preview Slice Scrub — ✅ COMPLETE

Interactive slice scrub lives in **geo-viz-engine** (visualization subproject); data page only hosts the widget via `GeoVizEngine` prepare/render.

| Slice | Work | Status |
|-------|------|--------|
| T1 | `SeismicAxisSpec` + payload `source_path` / `axes` / `max_slice_axis` | ✅ |
| T2 | `load_preview_slice` in `geoviz_seismic`; prepare attaches axes | ✅ |
| T3 | `SeismicPreviewWidget` slider + label + debounced reload | ✅ |
| T4 | Tests (`test_widget_position_slider_reloads_slice`, capabilities) | ✅ (11 passed) |
| T5 | Commit engine + parent planning/submodule bump | ✅ |

- Key modules (engine): `packages/geoviz_seismic/.../preview_widget.py`, `geoviz/previews/seismic.py`
- Workbench impact: none beyond submodule pin — DataPage already uses geoviz SEGY preview

### Phase 24: 可视化模块化对齐 Engine-aligned Visualization Hosts — 🔄 IN PROGRESS

Thin workbench host + thick geo-viz-engine modules. Visualization page no longer owns render logic.

| Slice | Work | Status |
|-------|------|--------|
| T1 | `viz/hosts/*` — WellLog / Seismic / CrossWell / PaleoMap / EnginePreview | ✅ |
| T2 | Composite panel = tab coordinator only | ✅ |
| T3 | LAS via `geoviz.load_las_preview`; SEGY via `SeismicLoader` + `load_segy` path | ✅ |
| T4 | Facade exports `load_las_preview` / `SeismicLoader`; independence tests updated | ✅ |
| T5 | Summary lists horizon/tops/DAT engine kinds + multi-well 连井 + predictions | ✅ |
| T6 | Tests green; planning docs | 🔄 |

**Architecture rule:** workbench production code imports only public `geoviz` facade (+ project models). Parsing/render live in engine packages.

### Phase 25: 导入/导出机制增强 Rich Import & Export — ✅ COMPLETE (local)

| Area | Deliverable |
|------|-------------|
| Registry | `resources/io_registry.py` — types, roles, preferred extensions, view export specs |
| Import | Enriched summary (size/mtime/label), roles/tags, empty-file skip, `ImportReport.summary_text` |
| Convert | LAS→CSV/XLSX/JSON摘要; table→JSON/XLSX; SEGY→SUMMARY; GeoJSON normalize; images/text |
| Service | `export_service.py` — asset export + inventory + widget snapshot + artifact register |
| UI | Data context menu 工程清单; Viz PNG/SVG/PDF export on active tab |
| Facade | `export_svg` / `export_pdf` / `export_png` on `geoviz` for well-log canvases |



### Phase 26: Factor-map domain chain + baseline green — ✅ COMPLETE

**Goal:** Close single-factor pipeline domain objects/math/UI, then restore full-suite green after async prep worker.

#### Completed
- [x] WellTable / MAD / sand-ratio / constraints / directional trend / ContourDraft / VersionSet (ISS-DOM/ALG/MAP/PREP/E2E)
- [x] Baseline catchup: 949 passed, 2 failed → fixed
  - [x] facade-only contour import + allowlist `extract_contour_*`
  - [x] preparation integration waits for QThread worker
- [x] ISS-MAP-02: `edit_history` written on command push/undo/redo

#### Decisions Made
| Decision | Rationale |
|----------|-----------|
| Contour extract only via `geoviz` facade | Preserve package independence test contract |
| Prep batch generate stays async | GUI non-blocking; tests use waitUntil |
| Compact edit_history (op/ids/ts, no full rings) | Audit without bloating .paleo.json |

#### Errors Encountered
| Attempt | Error | Resolution |
|---------|-------|------------|
| 1 | facade test failed on geoviz_plots import in contour_draft | Remove deep import; allowlist facade exports |
| 1 | prep integration 0 tasks after click | Wait for FactorPrepareWorker completion |

#### Next pending (ISSUE_BOARD Medium)
- ISS-QC-01/02 IssueLayer depth
- ISS-PRED-01 prediction beyond mock
- ISS-VIZ-01 well-tie workspace tab

## Known Follow-up Items

| # | Item | Status |
|---|------|--------|
| 1–10 | Historical minor items (save tests, PAGE_INDEX, topology, shapely, …) | ✅ done |
| 11 | Seismic Auto-Tie / synthetic signals never consumed by `SeismicView` | ✅ done (T-SEIS-02) |
| 12 | Map edit hit-test ignores hidden layers | ✅ done (T-MAP-04) |
| 13 | Demo map draft always appends (no replace/idempotent) | ✅ done (T-MAP-05) |
| 14 | `resolve_project_path` allows `..` escape (trusted-local threat model) | ✅ done (T-PATH-01) |
| 15 | Commit + push Phase 23 SEGY slider | ✅ done (this session) |
| 16 | DataPage reader-btn label vs whole-right-column hide | ✅ done (T-UI-01: 预览栏) |
| 17 | Map edit_history not written from command stack | ✅ done (ISS-MAP-02) |

## Page Progress Matrix

| # | Page | Status | Tests | Spec | Plan |
|---|------|--------|-------|------|------|
| 1 | 首页 | ✅ Complete | 23 | ✅ | ✅ |
| 2 | 数据 | ✅ Complete | 14+ | ✅ | ✅ |
| 3 | 测井预测 | ✅ Complete | 12 | ✅ | ✅ |
| 4 | 地震预测 | ✅ Complete | 12 | ✅ | ✅ |
| 5 | 层序格架 | ✅ Complete | 12 | ✅ | ✅ |
| 6 | 可视化 | ✅ Complete + geo-viz adapter (Phase 17) | 9+ | ✅ | ✅ |
| 7 | 制备 | ✅ Complete | 24 | ✅ | ✅ |
| 8 | 编图 | ✅ Editor V1 (PR #3) | 60+ | ✅ | ✅ |
| 9 | 成图审核 | ✅ Complete | 30 | ✅ | ✅ |
| 11 | 数据管理中心升级 | ✅ Complete | 27 | ✅ | ✅ |
| 12 | 数据多格式预览 | ✅ Complete | 9 | ✅ | ✅ |
| 13 | 数据页 V2 交互完善 | ✅ Complete | 7 | ✅ | ✅ |
| 14 | 项目管理 V1 | ✅ Complete | 24 | ✅ | ✅ |
| 15 | 数据页 UI/性能优化 | ✅ Complete (PR #1–2) | ~100+ | ✅ | ✅ |
| 16 | 编图编辑器 V1 | ✅ Complete (PR #3) | ~60+ | ✅ | ✅ |
| 17 | 可视化 geo-viz 适配器 | ✅ Complete | ~20+ | ✅ | ✅ |
| 18a | 样例工程引导 (E2E pipeline) | ✅ Complete (branch) | ~8+ | ✅ | ✅ |
| 18b | 预测资产绑定 (input_refs + VizAdapter) | ✅ Complete (branch) | ~15+ | ✅ design | ✅ |
| 18c | 演示相带草稿 (compile_map_draft) | ✅ Complete (branch) | ~10+ | ✅ design | ✅ |
| 19 | UI 视觉抛光 (density tokens / QSS / widgets) | ✅ Complete (branch) | ~11+ | ✅ | ✅ |
| 20 | 编图 GIS 壳抛光 (toolbar groups / dock QSS / status coords) | ✅ Complete (branch) | ~5+ | ✅ | ✅ |
| 21 | 数据页压测 + 导入 checksum skip (S1–S4 harness) | ✅ Complete (branch) | ~8+ | ✅ | ✅ |
| 22 | 全项目审计加固 (audit fixes) | ✅ Complete (`main`) | sampled suites | audit reports | — |
| 23 | 数据页 SEGY 剖面滑条 (engine scrub) | ✅ Complete | +slider tests | — | — |

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
| 2026-07-10 (Mapping Editor V1 + post-V1 topology, PR #3) | ~475 | ✅ |
| 2026-07-10 (Visualization geo-viz adapter Phase 17, merged main) | 501 | ✅ |
| 2026-07-10 (Phase 18a sample project bootstrap) | 509 | ✅ |
| 2026-07-10 (Phase 18b asset binding + 18c map draft) | 533 | ✅ |
| 2026-07-10 (Phase 19 UI visual polish) | 544 | ✅ |
| 2026-07-10 (Phase 20 Mapping GIS shell polish) | 549 | ✅ |
| 2026-07-10 (Phase 21 DataPage stress + import checksum skip) | 557 | ✅ |
| 2026-07-13 (Phase B multimodal + A three-pane + C concurrent scan) | 632 | ✅ |
| 2026-07-16 (Preview disk cache + geoviz local preview era) | 800+ / geoviz 1000+ | ✅ (env-dependent full suite) |
| 2026-07-16 (Phase 22 full-project audit hardening, pushed) | sampled 56+148+72 | ✅ |
| 2026-07-16 (Phase 23 SEGY slider — geoviz seismic preview tests) | 11 (focused) | ✅ |
| 2026-07-17 (Phase 26 baseline + edit_history) | 949 pass / 2 fail→fixed; focused 3+9 green | ✅ |
