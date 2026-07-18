# Task Plan: Paleogeography Workbench — UI Page Implementation

> **Updated:** 2026-07-17
> **Goal:** Ship a demo-ready paleogeography desktop workbench (10 AppShell pages, data center, project lifecycle, mapping editor, geo-viz previews). Current focus: Phase 27 system-state, GIS-core, and thread-lifecycle hardening.

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

### Phase 27: 系统状态、GIS 核心与线程生命周期审计重构 — ✅ COMPLETE

**Goal:** 在保持现有业务与 `.paleo.json` 兼容性的前提下，验证并修复 Project I/O、三大空间页、核心数学模型、异步预览/插值生命周期，并将专业解析与重计算收拢到 `geo-viz-engine` 公共 API。

**自动设计决策（用户已授权 Fully Automated Loop）：**

| 方案 | 取舍 | 决策 |
|------|------|------|
| 风险优先、证据驱动、engine-first 原子迁移 | 先复现高危缺陷；每次只修一条链路，兼容性最好 | **采用** |
| 页面/engine 一次性重写 | 边界最整齐，但回归面和交付风险过大 | 拒绝 |
| 仅在页面层打补丁 | 速度快，但继续制造重复解析、线程与算法债务 | 拒绝 |

#### Audit / Issue Board

| ID | Priority | Scope | Acceptance | Status |
|----|----------|-------|------------|--------|
| ISS-AUDIT-01 | P0 | 10 页 AppShell 路由、适配器、Project I/O 路径流 | 相对路径不可 `..` 越界；合法内部/绝对外部路径 round-trip；旧工程兼容 | ✅ audited |
| ISS-TOPO-01 | P0 | 多环多边形拖拽、闭合环、Shape 校验 | 外环/洞环按稳定 vertex id 编辑；首尾闭合不破裂；校验与命令栈一致 | ✅ fixed |
| ISS-THREAD-01 | P0 | DataPage 多模态预览、导入与 shell rebuild | stale result 丢弃；所有 QThread/worker 可取消、等待并安全销毁；无竞态告警 | ✅ fixed |
| ISS-ASYNC-01 | P0 | 制备页 IDW/断层屏障/等值线高负载 | GUI 主线程只调度/渲染；N≥2000 计算在 worker；错误/取消可恢复 | ✅ fixed |
| ISS-ALG-01 | P0 | MAD modified z-score | 严格实现 `0.6745*(x-median)/MAD`；MAD=0 有明确定义且测试覆盖 | ✅ fixed |
| ISS-ALG-02 | P0 | 砂地比约束 | 强制 `0 <= Hs <= Ht`、处理 Ht=0/NaN，输出范围 `[0,1]` | ✅ fixed |
| ISS-ALG-03 | P0 | 异向距离与方向加权趋势面 | 旋转坐标 `(u,v)`、轴尺度 `(a,b)` 与归一加权公式真实落地并有数值基准 | ✅ fixed |
| ISS-ARCH-01 | P1 | LAS/SEGY/插值/等值线解析边界 | workbench 页面仅依赖 `geoviz` facade；解析、重计算和 worker 核心在 engine | ✅ fixed |
| ISS-STATE-01 | P1 | ProjectDocument 内存状态与保存时序 | dirty scene/后台结果不会静默覆盖；保存原子且 `updated_at`/路径一致 | ✅ fixed |
| ISS-ROUTE-01 | P1 | 10 页路由与快捷键 | rail/stack/sidebar/窗口更新索引完全一致；第 10 页可由键盘访问；无陈旧 9 页假设 | ✅ fixed |
| ISS-ALG-04 | P0 | IDW 断层屏障与规模安全 | 非有限输入拒绝/过滤；接触/共线交点阻断正确；chunked 内存；大 N 质控不做无界 O(N²) | ✅ fixed |
| ISS-REPRO-01 | P1 | 演示采样可复现性 | 同参数跨进程生成相同 synthetic points/snapshot | ✅ fixed |

#### Execution Gates

- [x] A1：完整静态清单（确认 10 个 rail 路由 + shell/窗口入口）与路径调用图
- [x] A2：数学实现与公式逐项数值核验，Mock/placeholder/deep-import 清单落入 `findings.md`
- [x] A3：拓扑命令、Shape 校验、QThread 生命周期根因与最小复现
- [x] R1：按 P0 顺序 TDD 原子修复；每个模块 focused offscreen pytest
- [x] R2：engine facade 收口与 Thin Host 依赖测试
- [x] V1：root/engine 全量 non-slow 通过；无 Qt 线程销毁告警；`compileall`/`git diff --check` 通过

#### Inline TDD Implementation Plan

> 用户已授权 Fully Automated Loop；本计划在当前 checkout 内联执行。每个任务严格 RED → GREEN → focused regression；连续三次失败触发 RCA/策略切换。

##### Task 27.1 — 路由与 ProjectManager 事务语义（ISS-ROUTE-01 / ISS-STATE-01）

**Files:** `tests/test_keyboard_shortcuts.py`, `tests/test_app_shell.py`, `tests/test_project_manager.py`, `paleo_workbench/ui/app_shell.py`, `paleo_workbench/project/manager.py`

- [x] RED：新增 `0` 键进入第 10 页、非法 page index 无副作用、保存 `os.replace` 失败不修改内存 `updated_at`。
- [x] Run: 3 个新增用例按预期全部失败（3 failed in 4.59s）。
- [x] GREEN：数字映射 1–9+0、所有 helper 使用 `PAGE_INDEX_*`、switch 范围防御；timestamp 先写 data copy，原子 replace 成功后才 commit 到 model。
- [x] Regression：`37 passed in 7.70s`。

##### Task 27.2 — Engine 数学核心与有界 IDW（ISS-ALG-01..04 / ISS-ARCH-01）

- [x] RED：零 MAD、砂地比边界、异向轴校验、趋势面分块等价。
- [x] RED：断层端点/共线相交、非有限样点过滤、IDW 分块接口。
- [x] RED：合成样点不应依赖 Python 随机哈希。
- [x] GREEN：纯数学实现下沉并从 `geoviz` 门面导出。
- [x] GREEN：IDW 改为鲁棒相交、有限输入过滤与受限内存分块。
- [x] GREEN：workbench 包装层委托 engine，并采用稳定摘要种子。
- [x] GREEN：大样本 LOO 验证固定上限 64，采用确定性等距样本。

**Files:** `geo-viz-engine/packages/geoviz_plots/geoviz_plots/analytics/well_qc.py` (new), `.../interpolation/directional.py` (new), `.../interpolation/idw.py`, `geo-viz-engine/geoviz/__init__.py`/facade exports, workbench `workflow/well_qc.py`, `workflow/directional_trend.py`, `workflow/factor_interpolation.py`, engine/root tests.

- [x] RED：MAD=0+偏离值 → ±inf；砂地比边界；负 axis 拒绝；chunked trend/IDW 等价；fault endpoint/collinear 阻断；inf 输入不传播；跨进程 synthetic 稳定。
- [x] Run engine/root focused tests；确认失败原因分别命中现有行为。
- [x] GREEN：新增纯 NumPy engine API；workbench model wrappers 仅调用 `geoviz` facade；IDW/趋势按目标 cell block 计算；健壮 segment orientation；稳定 SHA256 seed；LOO 对大 N 确定性限样。
- [x] Regression：engine `39 passed`；root `30 passed`。

##### Task 27.3 — Engine polygon closure/MultiPolygon invariants（ISS-TOPO-01）

**Files:** engine `geoviz_paleo_map/topology.py`, `edit_commands.py`, tests `test_edit_commands.py`, `test_topology.py`/new focused cases.

- [x] RED：hole 全图拖拽/undo；删除首闭合 vertex 后 ring 仍闭合；open input 自动闭合；MultiPolygon round-trip 不扁平为 hole（3 failed / 38 passed）。
- [x] GREEN：ring mutation 同步 closing id；FeatureRef 保存 polygon part grouping；serialization 保留 Polygon/MultiPolygon。
- [x] Regression：engine topology/edit/canvas/hierarchy `89 passed`。

##### Task 27.4 — Workbench 多环 Thin Host（ISS-TOPO-01 / ISS-ARCH-01）

**Files:** `mapping/geometry_schema.py`, `mapping/document_io.py`, `ui/pages/map_edit_items.py`, `map_edit_commands.py`, `map_edit_scene.py`, mapping tests.

- [x] RED（I/O/item）：Polygon holes/MultiPolygon load→save 保真、洞内不填充、move/undo 全 ring（3 failed / 2 passed）。
- [x] RED（commands/validation）：hole ring handle/闭合编辑、geometry-aware hit-test、逐 ring save validation（3 failed）。
- [x] GREEN（I/O/item）：记录保留 geometry/rings；facies 使用 OddEven `QGraphicsPathItem`；move/undo 覆盖所有 part/ring。
- [x] GREEN（scene）：handle 标识 part/ring/vertex；RingEditCommand 携带稳定 ring address；whole Shape 验证调用 engine facade。
- [x] Regression：mapping editor/topology/document/project round-trip suites `122 passed`；hole mouse drag `1 passed`。

##### Task 27.5 — 通用可取消 Job 生命周期（ISS-THREAD-01 / ISS-ASYNC-01）

**Files:** engine 新增 bounded job/cancel primitives（具体落点在 geoviz facade 所属 package），workbench `preview_worker.py`, `data_page.py`, `factor_prepare_worker.py`, `preparation_page.py`, lifecycle tests.

- [x] RED：live project mutation、preview/import timeout owner、media unbounded preload 四项失败（4 failed）。
- [ ] RED：factor stale result 不 commit、running factor timeout keeper。
- [!] 3-Strike：running prepare shutdown 连续三次 hang；已完成 RCA，暂停猜测式修补，切换 faulthandler 精确栈策略（详见 `findings.md`）。
- [!] 3-Strike：preview terminal cleanup 三次全域失败；queued relay 后停在第 9 项，暂停 mutation并切换 faulthandler + deletion-order 审计。
- [x] preview 3-Strike 新策略验证：GUI cleanup 后删除 QThread；focused 1 passed / 全域 30 passed。
- [x] GREEN：不可变 snapshot→result DTO→GUI commit；超时 job 移交 application-level keeper；禁止丢失最后 owner。
- [x] GREEN：CancellationToken 下沉到 IDW/directional chunk checkpoint，取消延迟受单 chunk 约束。
- [x] Regression：preview/import/preparation teardown `95 passed`，无 `QThread destroyed`/self-wait/deleted-wrapper。

##### Task 27.6 — 等值线与地震专业解析异步收口（ISS-ASYNC-01 / ISS-ARCH-01）

**Files:** engine contour/seismic facade + workers, workbench thin hosts/pages, focused tests.

- [x] RED：contour extraction 不在 GUI thread；快速连续 SEGY load 只保留 latest；异常路径关闭 loader；体素预算生效；同步全量 fallback 不可由 host 调用。
- [x] GREEN：engine prepared-job APIs；generation/cancel；loader `finally close`；budget-derived downsample；GUI 仅 render/commit。
- [x] Regression：engine contour/SEGY `57 passed`；root contour/preparation/seismic host/lifecycle/package facade `63 passed`。

##### Task 27.7 — 全量审计门禁

- [x] root full（同一 non-slow 集合以 `-vv + faulthandler` 完成诊断门禁）：`993 passed, 4 skipped, 8 deselected`。
- [x] engine: `QT_QPA_PLATFORM=minimal QT_OPENGL=software LIBGL_ALWAYS_SOFTWARE=1 geo-viz-engine/.venv/bin/python -m pytest -m 'not slow' -q --timeout=60` → `1027 passed, 2 skipped, 134 deselected`。
- [x] `python -m compileall -q paleo_workbench geo-viz-engine/packages`
- [x] root + engine `git diff --check`；三份 PWF 与 Issue 状态已同步。

#### Errors Encountered

| Attempt | Error | Resolution |
|---------|-------|------------|
| Baseline 1 | `QT_QPA_PLATFORM=offscreen pytest -q --timeout=60 -m 'not slow'` 在 51% 后超过 3 分钟无输出，pytest-timeout 未中断 | 精确终止 PID 391169；不重复同一 quiet 命令，改用 focused suites + `-vv` 定位 |
| PWF patch 1 | 同一 patch 同时修改较远上下文时 verification failed | 用精确 `rg` 定位后拆分 patch；无代码影响 |
| Task 27.2 RED command | root pytest 同时收集 `geo-viz-engine/tests` 与 root node id 时 rootdir 切到 engine，导致 `tests.test_factor_interpolation` ModuleNotFoundError | 分成 engine cwd 与 root cwd 两条 focused 命令，避免 pytest rootdir 混用 |
| Task 27.2 facade regression 1 | `prepared_codec` 顶层导入 `geoviz_cross_well.FormationTop`，可选包屏蔽测试失败 | 延迟可选模型导入到对应 decode 分支，恢复 core-only import 契约 |
| Task 27.2 facade regression 2 | FormationTop 延迟后暴露 `prepared_codec -> previews.dat -> geoviz_plots` 第二条顶层链 | 同样延迟 XY/Surface payload 类型导入；第三次失败即按 3-Strike 重审 codec 分层 |
| Task 27.5 prepare hang 1–2 | keeper release 后 pytest Qt teardown 不退出；main in Qt poll | 将 finished→release 强制 queued 到 keeper GUI thread；第三次失败执行 3-Strike RCA |
| Task 27.5 prepare hang 3 | queued relay 后仍被 GNU timeout 15s 终止（124）；faulthandler 定位 stale failed slot 打开 QMessageBox modal | adopt 断开 completed+failed page slots；failure token guard；改非模态状态文本 |
| Task 27.5 preview cleanup 1–3 | 两次 cache rewrite idle timeout；queued relay 后全域第 9 项前 timeout 124 | 3-Strike：faulthandler 定位；审计 `finished→deleteLater` 与 relay 顺序，GUI cleanup 后再 delete wrapper |
| Task 27.7 engine full 1 / DTW focused 2 | cross-well DTW 1k 分别 1.061s / 1.045s，超过 1s 门槛 | 第三次前审计热区；将逐 cell Python DP 等价改写为 NumPy min-plus prefix scan，DTW suite 10 passed |

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

### Phase 28: Review 缺陷修复与 Clean-Checkout 交付 — ✅ COMPLETED

**Goal:** 修复 reviewer 指出的 6 条交付/数据完整性/异步生命周期问题，并把 engine 变更与 parent gitlink 固化为 clean checkout 可复现提交。

| ID | Priority | Acceptance | Status |
|----|----------|------------|--------|
| REV-PACK-01 | P1 | 两个新 workbench 模块进入父仓提交；clean checkout 可 import `PreparationPage` | ✅ done |
| REV-ENGINE-01 | P1 | engine 变更独立提交，父仓 gitlink 指向含 jobs/算法/拓扑 API 的 commit | ✅ done |
| REV-GEOM-01 | P1 | complex Polygon/MultiPolygon merge/split 明确拒绝，原 feature 不删除 | ✅ done |
| REV-PREVIEW-01 | P1 | preview 优先 editor record 的标准 geometry，holes/MultiPolygon 保真且不崩 | ✅ done |
| REV-SEGY-01 | P1 | clear/demo/empty 离开 path load 时取消并递增 generation；旧 worker 不覆盖新状态 | ✅ done |
| REV-IO-01 | P2 | preview mode/payload 门禁先于 stat/read；非 image/PDF 与已有 bytes 零读盘 | ✅ done |

#### TDD / Delivery Plan

- [x] RED：分别为 complex merge/split、preview geometry、SEGY invalidation、preload no-read 添加失败测试。
- [x] GREEN：最小产品修复；每个原子缺陷 focused offscreen pytest。
- [x] REGRESSION：mapping/preview/seismic/package suites。
- [x] COMMIT：engine scoped commit；父仓纳入新模块、更新 gitlink并提交（排除用户未跟踪资产）。
- [x] CLEAN CHECKOUT：临时 worktree/submodule 初始化后 import + focused tests；compileall/diff-check。

### Phase 29: PDF 预览加载失败诊断与修复 — ✅ COMPLETED

| ID | Priority | Acceptance | Status |
|----|----------|------------|--------|
| ISS-PDF-01 | P1 | QIODevice PDF 以 status/error 判定；Ready 正常渲染，Loading 等待，Error 才失败 | ✅ fixed |

- [x] 核验 QtPdf / QtPdfWidgets 安装与版本。
- [x] 用实际 44.6 MiB、248 页 PDF 验证直接路径加载。
- [x] 验证 `QIODevice` overload 返回语义与 widget 误判状态。
- [x] 用户批准推荐方案 A：状态驱动、保留异步预载 bytes。
- [x] RED：真实 QBuffer PDF 加载后 widget 不得误判 `_load_failed`。
- [x] GREEN：统一以 `QPdfDocument.status()/error()/pageCount()` 收敛 load 状态；Loading 由 `statusChanged` 完成。
- [x] REGRESSION：PDF widget、preview async、data page focused tests。
- [x] FINAL：root non-slow、compileall、diff-check；更新 PWF。

#### Approved Design / Inline Plan

- 仅修改 `paleo_workbench/ui/pages/preview_widgets.py` 与对应测试，不改变 worker 预载预算、不回退为 GUI 线程路径读盘。
- `load(path, pdf_bytes)` 保存当前 source identity；QIODevice overload 调用后不读取其 Python 返回值，转而调用单一 `_finish_document_load()`。
- `_finish_document_load()`：`Loading` 时保持加载态并等待 `statusChanged`；`Ready + pageCount>0` 调用 `_render_page()`；`Error` 或 Ready 但零页才显示失败。
- `statusChanged` 槽只处理当前 document；旧 buffer 在下一次 load 前释放，QBuffer 生命周期继续覆盖 document 使用期。
- 执行方式：当前会话 inline TDD；用户未授权 subagent，且本任务为单原子缺陷。

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

### Phase 30: 重复实现审计与分阶段收敛 — 🔄 AUDITING

**Goal:** 在不改变现有业务行为和公开工程格式的前提下，识别重复职责的单一真源（Single Source of Truth），逐批消除 workbench 页面、适配器与 `geo-viz-engine` 之间的重复实现。

| ID | Priority | Candidate scope | Acceptance | Status |
|----|----------|-----------------|------------|--------|
| ISS-DEDUP-THREAD-01 | P1 | Data / Preparation / Mapping / Preview 的 QThread 生命周期 | 统一任务托管、取消、generation 与安全回收契约；页面只编排业务事件 | 🟡 audit |
| ISS-DEDUP-ALG-01 | P1 | QC、方向趋势、IDW、等值线编译的 engine/workbench 边界 | 专业算法仅保留 engine 单一实现；workbench 仅 DTO/兼容委托 | 🟡 audit |
| ISS-DEDUP-PREVIEW-01 | P2 | preview provider / fallback / widgets 的 revision、stat 与格式分派 | 统一 source identity 与 preview dispatch，消除重复文件探测 | 🟡 audit |
| ISS-DEDUP-GEOM-01 | P2 | geometry schema / mapping helper / adapter 的几何规范化 | 明确 canonical geometry 所有权，转换链无重复降维且兼容旧数据 | 🟡 audit |
| ISS-DEDUP-SIZE-01 | P2 | 超大视图/渲染模块 | 按职责拆分，不以机械拆文件替代行为去重 | 🟡 audit |

#### Design Gate

- [x] 恢复 PWF、git 与既有 Phase 27–29 状态；确认没有待提交产品改动。
- [x] 建立第一轮重复职责候选地图与大文件热点。
- [x] 用户确认第一批优先收敛线程生命周期职责（选择 1）。
- [ ] 对选定范围完成调用图、兼容面与重复证据审计。
- [ ] 提出 2–3 个收敛方案及取舍，获得设计批准后再进入 TDD 实现。
- [ ] 分批 focused / full offscreen pytest、compileall、diff-check 与 clean-checkout 验证。

> 当前处于设计门禁：在用户确认优先范围并批准方案前，不修改业务代码。

**Selected direction:** 先统一任务生命周期基础设施；业务 worker、结果提交槽及 Preview 的 latest-only 调度语义保持独立。

**Selected boundary:** 用户选择 Workbench 优先；Phase 30 第一批不修改 `geo-viz-engine`，仅保证其独立包契约不被破坏。

#### Approved Architecture

- 新建 `paleo_workbench/ui/owned_worker_job.py`，提供持久的 `OwnedWorkerJob(QObject)`；一个实例在任一时刻最多拥有一个 QThread/worker。
- `start(worker, *, terminal_signals, result_connections=(), cancel=None, target=None)` 统一创建无页面 parent 的 QThread、moveToThread、started→run、terminal→quit（DirectConnection）、worker/thread 延迟释放和运行身份记录。
- `shutdown(wait_ms)` 统一取消、断开业务结果连接、requestInterruption、quit、有限 wait；超时后转交 `DetachedJobKeeper`，绝不调用 `terminate()`；返回是否在期限内完成。
- 公开只读属性：`is_running`、`thread`、`worker`、`target`；`released` 信号只表示该句柄已可再次启动。所有 finished relay 都以 thread/worker identity 校验，旧 detached job 不得清空新 job。
- `DetachedJobKeeper` 保留为 QApplication 生命周期最后防线，不增加调度职责。
- Preparation/Mapping 保留 completed/failed 槽与 GUI-thread commit；Data 保留单次 import 业务语义；Preview 保留 generation、latest-only pending、cache 和 pump 顺序。
- 本批不修改 `geo-viz-engine`、ProjectDocument schema、worker DTO/信号及页面公开行为。

#### Phase 30 Implementation Plan

> **Execution:** 当前会话 inline TDD；用户未授权 subagent。每个产品步骤严格 RED→GREEN→refactor，并执行 2-Action PWF 门禁。

##### Task 30.1 — 通用 OwnedWorkerJob 契约

**Files:**
- Create: `paleo_workbench/ui/owned_worker_job.py`
- Create: `tests/test_owned_worker_job.py`
- Modify: `paleo_workbench/ui/thread_keeper.py`（仅在契约测试证明需要时增加幂等释放，不扩展职责）

**Produces:**
```python
class OwnedWorkerJob(QObject):
    released = Signal()
    def start(
        self,
        worker: QObject,
        *,
        terminal_signals: tuple[object, ...],
        result_connections: tuple[tuple[object, object], ...] = (),
        cancel: Callable[[], None] | None = None,
        target: object | None = None,
    ) -> None: ...
    def shutdown(self, wait_ms: int = 3_000) -> bool: ...
    @property
    def is_running(self) -> bool: ...
```

- [ ] RED：真实 QObject worker 证明 run 不在 GUI thread；完成后 `released` 且引用清空。
- [ ] RED：阻塞 worker 的 `shutdown(1)` 必须取消、断开结果槽、被 keeper 托管，释放后 keeper 清零。
- [ ] RED：旧 detached worker 后结束不得清空同一 handle 上的新 job；禁止 `QThread.terminate`。
- [ ] Run: `QT_QPA_PLATFORM=offscreen pytest -q tests/test_owned_worker_job.py -vv --timeout=30`；Expected: 因模块/API 不存在而 FAIL。
- [ ] GREEN：实现上述最小 API；不实现队列、重试、优先级或业务 generation。
- [ ] Run 同一命令；Expected: 全部 PASS。

##### Task 30.2 — Preparation/Mapping contour 同构迁移

**Files:**
- Modify: `paleo_workbench/ui/pages/preparation_page.py`
- Modify: `paleo_workbench/ui/pages/mapping_page.py`
- Modify: `tests/test_contour_draft_ui.py`
- Modify: `tests/test_mapping_contour_async.py`

**Consumes:** `OwnedWorkerJob.start()` / `shutdown()`。

- [ ] RED：两页 contour 都通过 handle 在非 GUI thread 执行；shutdown 后 stale result 不提交；超时 job 进入 keeper。
- [ ] Run: `QT_QPA_PLATFORM=offscreen pytest -q tests/test_contour_draft_ui.py tests/test_mapping_contour_async.py -vv --timeout=30`；Expected: 新 handle 契约断言 FAIL。
- [ ] GREEN：两页各持有 `_contour_job`，删除重复 `_contour_thread/_worker/_token/_target` 启停代码；页面保留不同成功提示和 commit 行为。
- [ ] Run 同一命令；Expected: PASS。

##### Task 30.3 — Preparation factor job 迁移

**Files:**
- Modify: `paleo_workbench/ui/pages/preparation_page.py`
- Modify: `tests/test_prep_well_table_worker.py`
- Modify: `tests/test_preparation_integration.py`

- [ ] RED：补充 handle running/target、取消后 stale snapshot 不提交、正常完成恢复按钮的行为测试。
- [ ] Run: `QT_QPA_PLATFORM=offscreen pytest -q tests/test_prep_well_table_worker.py tests/test_preparation_integration.py -vv --timeout=45`；Expected: 新 handle 契约断言 FAIL。
- [ ] GREEN：用 `_prepare_job` 替代四个并行字段与重复 shutdown；FactorPrepareWorker 和 GUI commit 逻辑不变。
- [ ] Run 同一命令；Expected: PASS。

##### Task 30.4 — DataPage import 生命周期迁移

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `tests/test_data_page.py`

- [ ] RED：正常 import 保持 queued GUI commit；页面销毁/显式 shutdown 后 blocked import 被托管且不能发出 stale 页面事件。
- [ ] Run: `QT_QPA_PLATFORM=offscreen pytest -q tests/test_data_page.py -vv --timeout=45`；Expected: 新 job ownership 断言 FAIL。
- [ ] GREEN：用一个 `_import_job` 取代 `_import_jobs` tuple 列表及 sender 查找/手工 disconnect/wait；保留 `_import_in_progress` 和工具栏状态。
- [ ] Run 同一命令；Expected: PASS。

##### Task 30.5 — PreviewController 仅迁移 transport ownership

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_worker.py`
- Modify: `tests/test_preview_async.py`
- Modify: `tests/test_preview_disk_cache.py`
- Modify: `tests/test_datapage_stress.py`

- [ ] RED：锁定 single in-flight、latest-only、generation 丢弃、thread-stopped 后再 pump、blocking shutdown keeper 五项行为，并断言 active ownership 来自 `OwnedWorkerJob`。
- [ ] Run: `QT_QPA_PLATFORM=offscreen pytest -q tests/test_preview_async.py tests/test_preview_disk_cache.py tests/test_datapage_stress.py -vv --timeout=45`；Expected: ownership 新断言 FAIL，既有行为测试保持基线。
- [ ] GREEN：以 `_active_job` 替代 `_jobs/_active` 的裸 QThread tuple 与重复 shutdown；pending/cache/generation 函数保持原样。
- [ ] Run 同一命令；Expected: PASS。

##### Task 30.6 — 去重审查与回归门禁

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [ ] `rg` 确认页面不再直接重复 `QThread()`、moveToThread、wait/adopt 组合；允许 engine 与 `OwnedWorkerJob` 单一底层实现。
- [ ] Focused: 上述所有受影响测试独立进程通过。
- [ ] Full root: `QT_QPA_PLATFORM=offscreen pytest -q --timeout=60 -m 'not slow'`；若复现既有长寿命 Qt stall，按已验证的文件区间分段并闭合 collection 数量。
- [ ] Static: `python -m compileall -q paleo_workbench`、`git diff --check`。
- [ ] Clean checkout: 导入 AppShell 并执行 owned-job/contour/data/preview focused contracts。

#### Plan Self-Review

- [x] Coverage：启动、正常完成、失败、取消、stale、防销毁竞态、Preview latest-only、Data queued commit 均有对应任务。
- [x] Scope：不修改 engine、算法、项目 schema、几何或预览内容生成。
- [x] DRY/YAGNI：通用层只有单 owned-job 生命周期；没有全局 scheduler、优先级或重试。
- [x] Type/API consistency：所有迁移任务只依赖 Task 30.1 定义的 `start/shutdown/is_running/thread/worker/target/released`。
- [x] Placeholder scan：无 TBD/TODO/“类似前项”占位描述。
