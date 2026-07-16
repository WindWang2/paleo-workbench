# Findings: Paleogeography Workbench

## 数据管理思维 (Data Management Mindset)

> 数据页不是「资源摘要卡片」，而是**工程级数据 / 成果 / 文件管理中枢**。后续任何数据页改动、导入链路、预览与性能优化，都先对齐这套思维。

### 1. 管什么（资产宇宙）

数据页管理 `ProjectDocument` 上**一切文件型资产**，不限于测井/地震：

| 类别 | 典型内容 | 模型落点 |
|------|----------|----------|
| **输入数据** | 测井 LAS、地震 SEG-Y、层位、井分层、时深、表格 | `resources`（`artifact_role`≈input） |
| **参考资料** | PDF/文档、影像、历史图件、WLP 等 | `resources`（document / image_reference / …） |
| **成果 / 导出** | 单因素图、预测结果、成图 PDF、导出物 | `export_artifacts` + 派生 resource |
| **异常** | missing / warning / failed / error | 同一表，状态着色 + 目录「异常」 |

原则：**一张表看全工程文件面**；目录按「角色 + 类型」切片，不是按 UI 装饰分区。

### 2. 项目登记 vs 磁盘真相

- 工程文件（`.paleo.json`）登记的是 **路径 + 元数据 + checksum**，默认**不拷贝**进工程目录。
- **导入** = 扫盘 / 选文件 → 分类 → **去重**（path 优先，checksum 次之）→ 写入 `ProjectDocument`。
- **移出项目** = 从工程登记删除，**绝不删磁盘文件**。
- **重新扫描** = 用磁盘刷新元数据；文件没了 → `status=missing`，记录仍在，便于补路径。
- **打开目录** = 定位源文件所在位置，方便外部工具编辑。

思维口诀：**登记可丢、磁盘不碰；缺失可标、源文件可找。**

### 3. 工作台隐喻（怎么用）

数据页是**文件管理器 + 多格式阅读器**，不是报表 dashboard：

```
[摘要条：就绪/计数]
[工具栏：导入 | 搜索 | 列设置 | 目录/阅读器开关]
┌────────────────────┬────────────────────┐
│  资产表（主工作面）   │  阅读器（选中即读）   │
│  虚拟滚动 / 筛选     │  有界预览，非元数据卡  │
└────────────────────┴────────────────────┘
  浮动「目录」          浮动「操作」
  （overlay，不抢宽）    （导入/扫描/移出/状态）
```

- **表 + 阅读器** 是第一视口；目录/操作是**可收起 overlay**，禁止再改回「三列固定卡片抢宽度」。
- **选中即读**：支持的格式立刻给出可读预览；不支持的给清晰 message，管理动作仍可用。
- **阅读器优先于元数据卡片**：元数据做 header/次要信息，主体是 PDF 翻页、表格预览、文本、图件等。

### 4. 操作闭环（用户心智）

1. **进工程** → 打开/新建 → 数据页反映当前 `ProjectDocument`  
2. **补数据** → 导入文件/目录（后台线程）→ 表 + 目录计数一次刷新  
3. **找数据** → 目录分类 / 搜索 / 列显隐 → 只动过滤视图，不读文件体  
4. **看数据** → 点行 → loading → 有界预览（cache 命中则秒开）  
5. **管数据** → 重扫 / 移出 / 开目录；状态与侧栏上下文同步  
6. **交给下游** → 测井/地震/制备/编图等页消费同一批 `resources` / artifacts  

数据页是 workflow 第一步（`data_check` / 数据管理）的**常驻中枢**，不是一次性检查表。

### 5. 预览边界（安全默认）

| 做 | 不做（数据页内） |
|----|------------------|
| 有界文本/表（行列表上限） | 全文件编辑 |
| PDF 按页阅读 | 深度 OCR / 全文检索引擎 |
| 图按视口缩放 | 批量缩略图流水线 |
| LAS / SEG-Y **有界预览**（LAS 曲线轨；SEGY 中剖面 + **滑条 scrub**） | 全道集体可视化、OpenGL 解释工作台（属地震预测/可视化页） |
| 失败降级 message | 崩溃或阻塞 UI |

深度可视化属于 **测井预测 / 地震预测 / 可视化页**；数据页只保证「认得、管得住、能预览到可用程度」。

### 6. 规模与响应（性能思维）

目标体感：**2000+ 行仍可滚、可筛、可切预览**。

| 路径 | 原则 |
|------|------|
| 表 | 虚拟 model/view；`data()` 永不读文件体 |
| 筛选 | 内存 `FilterIndex`；防抖搜索；不触发预览 |
| 预览 | 后台/串行队列 + generation；UI 线程 LRU；stale 丢弃 |
| 导入 | 后台导入；完成时 **一次** 批量 refresh |
| 生命周期 | page 销毁 / shell rebuild 时 shutdown worker |

成功标准是**体感流畅**，不是 CI 硬 latency SLO。

### 7. 与项目管理的关系

- **工程** 拥有资源列表；**数据页** 是编辑/检视该列表的主界面。
- new/open 会 rebuild `AppShell` → 新 `DataPage(project=…)`；数据状态以当前工程为准。
- 保存工程 = 持久化登记信息（含相对路径策略），不是打包全部二进制。

### 8. 决策检查清单（改数据页前先问）

1. 这是在**管理工程登记**，还是在做专用可视化？后者考虑别的页。  
2. 会不会**误删磁盘**？默认禁止。  
3. 会不会让**表/阅读器失去第一视口**（固定侧栏回潮）？禁止。  
4. 大列表/大切换会不会**堵主线程**？要有界、异步、可丢弃。  
5. 导入完成是否**一次刷新**？禁止逐条重绘风暴。  
6. 缺失/不支持是否**可解释**且管理动作仍可用？

### 9. 关键规格（按时间线）

| 文档 | 贡献的思维 |
|------|------------|
| `2026-07-06-datamanagementpage-design.md` | 工程级资产中心、目录分类、去重、非破坏删除 |
| `2026-07-07-datapage-ui-management-performance-design.md` | 阅读器主表面、有界预览 |
| `2026-07-09-data-management-page-redesign.md` | 工作台 + 浮动目录/操作、表\|阅读器 |
| `2026-07-10-datapage-ui-perf-optimization-design.md` | 2000+ 虚拟化、异步预览、缓存与导入批量刷新 |

---

## Project Architecture

- **Two repos:** `paleo_workbench` (root, business logic + UI shell) + `geo-viz-engine` (submodule, visualization rendering engine)
- **Tech stack:** Python 3.12, PySide6 6.6+, Pydantic v2, pytest+pytest-qt
- **Design system:** Standalone HTML prototype (`古地理图编制系统 (standalone).html`, 3.7MB minified bundle) is the single source of truth for UI. Colors/fonts/dimensions extracted via headless browser computed-CSS inspection.
- **数据管理思维：** 见上文「数据管理思维」——工程文件中枢、非破坏登记、表+阅读器工作台、有界预览、规模体感优先。

## Design Tokens (extracted from prototype)

### Colors
| Token | Value | Source |
|-------|-------|--------|
| Primary | `#1f6fe0` | Primary button, active accents |
| Accent | `#6f47cf` | Prediction, step 3 |
| Success | `#1f9d57` | Completion/success |
| Teal | `#0f93a4` | Step 2 indicator |
| Warning | `#c47e12` | Step 4 indicator |
| Coral | `#e2705b` | Step 5 indicator |
| BG Body | `#eef0f4` | Main content area |
| BG Header | `#f3f5f9` | Menu bar, header toolbar |
| BG Sidebar | `#ffffff` | Text sidebar |
| BG Search | `#eef2f7` | Search box, status bar |
| Rail gradient | `linear-gradient(#1f5fbf, #184c97)` | Icon rail background |
| Text Primary | `#28323f` | Main text |
| Text Secondary | `#7e8794` | Status/secondary text |
| Border | `#e2e6ec` | Card/sidebar borders |
| Error Red | `#dc2626` | Failed/missing indicators |

### Typography
- Family: `"PingFang SC", "Microsoft YaHei", system-ui, -apple-system, "Segoe UI", sans-serif`
- Base: 12.5px, Status: 11px, Nav label: 9.5px/500, Sidebar secondary: 10.5px

### Dimensions
- Menu bar: 36px, Header: 38px, Icon rail: 60px, Sidebar: 248px, Status bar: 24px
- Nav item: 46x46px, radius 8px. Badge: 30x30px, radius 8px
- Button radius: 5px, Card radius: 9px, Panel radius: 10px

## Prototype Navigation (9 pages)

The prototype has 9 icon-rail navigation items (initial screen inventory said 7, corrected after browser extraction):

1. 首页 (HomePage) — project dashboard
2. 数据 (DataPage) — multi-source data management
3. 测井预测 (WellLogPredictionPage) — well log + prediction
4. 地震预测 (SeismicPredictionPage) — seismic + prediction
5. 层序格架 (SequenceFrameworkPage) — sequence stratigraphy
6. 可视化 (VisualizationPage) — composite visualization
7. 制备 (PreparationPage) — factor map preparation
8. 编图 (MappingPage) — paleogeographic map
9. 成图审核 (ReviewExportPage) — QC and export

## Workflow Model

6 compilation steps (STEP_ORDER in `workflow/service.py`):
1. data_check → 数据管理 (blue #1f6fe0)
2. factor_map → 数据转换 (teal #0f93a4)
3. prediction → 制图数据制备 (purple #6f47cf)
4. map_compile → 沉积相预测 (amber #c47e12)
5. qc → 古地理图编制 (coral #e2705b)
6. export → 质控与导出 (gray #7e8794)

Step statuses: pending, ready, running, complete, warning, failed, skipped, mock

## Data Models

- `ProjectDocument`: meta, stratigraphy, resources, factor_map_tasks, prediction_tasks, compilation_runs, quality_reports, export_artifacts
- `ResourceItem`: name, path, type (well_log/seismic/horizon), format, status, crs, tags, source, parsed_summary, checksum, external, artifact_role
- `WorkflowStep`: step_type, status, required_input_resource_ids, produced_ids, blocking_issue_summary, provenance_summary
- `CompilationRun`: name, target_horizon, sequence_scheme_ref, status, workflow_steps

## Key Technical Decisions

1. **Icon rail uses QToolButton** (not QPushButton) with `ToolButtonTextUnderIcon` for icon-above-text layout
2. **Active state via QSS property selectors**: `setProperty("navItem", True)`, `setProperty("active", True)`, with `style().unpolish/polish` to force re-evaluation
3. **Icons extracted from prototype** as SVG files (stroke-based, 18-19px, `currentColor`, viewBox 0 0 24 24)
4. **Cards use inline stylesheet** referencing tokens (not global QSS) since they are page-specific
5. **SDD (subagent-driven development)** for all implementation: fresh subagent per task, review after each, final whole-branch review

## Browse Skill Notes

- Browse binary at `~/.claude/skills/gstack/browse/dist/browse` (NOT `gstack-backup`)
- standalone HTML is minified — use `js` command with `getComputedStyle()` for CSS extraction, `snapshot -i -c` for structure
- JSON return from `$B js` requires `JSON.stringify()` — `console.log` goes to browser console, not stdout
- Current model does NOT support image input — text-based DOM extraction only

## Errors Encountered

| Error | Resolution |
|-------|------------|
| JSON parsing failed on long Write/Bash content | Split into bash `cat >>` heredoc appends |
| SVG files written to wrong directory (`paleo_project/` instead of `paleo_workbench/`) | Moved files, deleted wrong dir |
| `empty_label` dangling reference in RecentActivityCard | Fixed: persistent label with show/hide instead of recreate |
| Status coloring dead code in ResourceTable | Fixed: apply `setForeground(QColor(status_color))` |

## PreparationPage (Phase 4) Notes

### Prototype 制备 Page Structure (3 panels)

Extracted from standalone HTML via headless browser:
1. **Left (单因素图清单)**: target horizon label + interpolation method combobox (克里金/IDW/样条) + "批量生成单因素图" button + 8 task rows (name + method/grid + status badge 已生成/待生成) + footer "已制备 6 / 8 个单因素图".
2. **Center (单因素图集预览)**: header "{horizon} 单因素图集（{method}插值 · 网格 50×50 m）" + 2-col grid of cards (factor name + value range + R²) + 沉积相概率体 + 初始岩相边界 preview placeholders.
3. **Right (初始岩相边界制备)**: probability threshold (0.55) + smoothing (中) + min area (0.5 km²) + participating facies chips + "生成初始边界并送入编图" button.

### New Tokens Added

- `TASK_STATUS_COLORS`: complete→SUCCESS, pending→TEXT_SECONDARY, running→PRIMARY, failed→ERROR_RED
- `TASK_STATUS_LABELS`: complete→已生成, pending→待生成, running→进行中, failed→失败
- `INTERPOLATION_METHODS`: ["克里金", "IDW", "样条"]
- `SMOOTHING_LEVELS`: ["弱", "中", "强"]

### Data Model Note

`FactorMapTask.method` from `create_mock_factor_map` is the literal string "mock" (not "克里金"). Displayed as-is — the method combobox and preview header will show "mock" for mock-generated tasks. A future task could map mock→display method.

### AppShell Integration Pattern (split-loop)

To insert a real page mid-stack while keeping index alignment with PAGE_NAMES, AppShell uses a split-loop:
```python
self.page_stack.addWidget(HomePage())        # 0
self.page_stack.addWidget(DataPage())        # 1
for name in tokens.PAGE_NAMES[2:6]:          # 2,3,4,5
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(PreparationPage()) # 6
for name in tokens.PAGE_NAMES[7:]:           # 7,8
    self.page_stack.addWidget(PagePlaceholder(name))
```
This pattern will be reused as more pages gain real content.

### Errors Encountered

| Error | Resolution |
|-------|------------|
| FactorPreviewGrid defaulted grid metric to "—" instead of "50×50" (spec deviation) | Fixed: default "50×50" + regression test; found in task review before merge |
| Card had double padding (stylesheet + layout margins) | Fixed: removed stylesheet padding, kept layout margins (sibling convention) |
| BoundaryPanel labels drifted from spec wording (岩相阈值 vs 概率阈值 etc.) | Fixed: aligned to spec strings (概率阈值/边界平滑强度/最小图斑面积) |

## ReviewExportPage (Phase 5) Notes

### Prototype 成图审核 Page Structure (3 panels)

Extracted from standalone HTML via headless browser. QC-centric page:
1. **ActionHeader**: title (map horizon) + 3 buttons (运行检查/规则配置/导出检查报告) + rules chips row.
2. **QCIssueTable**: 检查项目/检查说明/结果说明 columns, one row per QC rule, result ✓通过/!警告/!待处理.
3. **ResultSummary**: 通过项 N/警告项 N/待处理项 N counts + advisory text + export artifacts list.

### New Tokens Added

- `WARNING = "#c47e12"` (standalone; previously only embedded as STEP_COLORS[3])
- `QC_RESULT_COLORS`: pass→SUCCESS, warning→WARNING, error→ERROR_RED
- `QC_RESULT_LABELS`: pass→"✓通过", warning→"!警告", error→"!待处理"
- `DEFAULT_QC_RULES`: 6 prototype rule names
- `RULE_DESCRIPTIONS`: maps BOTH Chinese prototype rule names AND engine rule keys (facies_polygons_present, target_horizon_present) to descriptions — bridges the engine's English rule IDs to Chinese display text

### Severity Mapping Decision

Engine (`run_basic_qc`) emits severity "warning"/"error". Prototype displays 通过/警告/待处理. Mapping chosen: warning→警告 (amber), error→待处理 (red, treated as needs-action). The advisory text "待处理项" reinforces error=needs-action. Counts are one-result-per-rule (matches prototype's 通过项 5 / 警告项 2 / 待处理项 1 semantics).

### Shared Helper Pattern (qc_helpers.py)

Final review caught a divergence bug: QCIssueTable (last-issue-wins) and ResultSummary (error-precedence) derived per-rule results independently, so they could disagree when a rule had multiple issues of different severities. Fixed by extracting `derive_rule_result(rule, issues) -> (severity, text, color)` in `qc_helpers.py` with error-takes-precedence semantics, called by both widgets. This pattern (shared derivation helper for cross-widget consistency) should be reused if future pages derive display values from the same source data.

### AppShell Integration (split-loop, continued)

Page construction now uses three segments to keep index alignment with PAGE_NAMES:
```python
self.page_stack.addWidget(HomePage())            # 0
self.page_stack.addWidget(DataPage())            # 1
for name in tokens.PAGE_NAMES[2:6]:              # 2,3,4,5
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(PreparationPage())     # 6
for name in tokens.PAGE_NAMES[7:8]:              # 7 (编图)
    self.page_stack.addWidget(PagePlaceholder(name))
self.page_stack.addWidget(ReviewExportPage())    # 8
```

### Data Model Note

QualityReport carries rule keys that may be either Chinese display names (prototype) or engine keys (facies_polygons_present). RULE_DESCRIPTIONS maps both, so QCIssueTable's description column works for either source. The integration test confirms engine output renders descriptions correctly, not raw keys.

## Data Management Center Redesign Notes

### Current DataPage Limit

The current DataPage is a narrow resource-management page:
- `ResourceSummaryBar` displays readiness counts.
- `ResourceTable` displays five columns.
- `ActionPanel` contains import/convert buttons but they are not wired to behavior.

User clarified that the Data page should manage all project data, results, and files, and preview supported data types. This is broader than the current Phase 3 DataPage implementation.

### Existing Backend Pieces

- `scan_resources(root, project_path=None)` recursively scans files and creates `ResourceItem` records with name, path, type, format, status, source, `parsed_summary["size_bytes"]`, checksum, and external flag.
- `classify_path(path)` classifies LAS, SEGY/SGY, DAT variants, spreadsheets, documents, images, reference maps, WLP files, and unknowns.
- `ProjectDocument.resources` stores imported/reference resources.
- `ProjectDocument.export_artifacts` stores export outputs.
- `ProjectManager.save()` relativizes resource paths and export output paths.

### Design Decision

For the first Data Management Center implementation, keep the existing data model:
- Use `ProjectDocument.resources` for data/reference files.
- Use `ProjectDocument.export_artifacts` for generated export files.
- Use `ResourceItem.artifact_role` to distinguish input/reference/derived/export roles where needed.
- Store lightweight preview metadata in `ResourceItem.parsed_summary`.

Avoid introducing a new `ProjectFileItem` model until real usage proves the current model insufficient.

### Testing Gap

There are currently no standalone `tests/test_resources_scanner.py` or `tests/test_resources_classifier.py` files. The Data Management Center implementation should add direct tests for classifier, scanner, import service, dedupe, and preview strategy behavior.

### Implementation Notes

- Added direct classifier/scanner coverage in `tests/test_resources_classifier.py` and `tests/test_resources_scanner.py`.
- `DataImportService` normalizes paths against `project_path.parent` when a project path is available, so saved relative resource paths dedupe correctly against newly selected absolute files.
- Import reports separate `added`, `skipped_path`, `skipped_checksum`, and `warnings`; the UI can surface these counts without inspecting service internals.
- Preview strategy returns immutable `PreviewState` records and is intentionally metadata-only for heavy formats. Image resources expose an image path, but no image bytes are decoded in the strategy layer.
- DataPage now treats `ProjectDocument.resources` and `ProjectDocument.export_artifacts` as the two project-wide asset sources. Generated files are displayed as artifacts; derived resources can still be represented through `ResourceItem.artifact_role`.
- File dialog behavior is behind `_choose_import_files()` and `_choose_import_folder()` seams so tests can exercise import refresh without launching native dialogs.

## Data Preview Format Notes

- Text preview reads at most 8192 bytes and 20 lines.
- `txt` and `xml` use `PreviewState.mode == "text"`; `csv` and `dat` use `PreviewState.mode == "table"`.
- Binary-looking text-like files fall back to metadata-only with a safe-summary warning.
- Missing text/table/professional files return metadata mode with `"文件不存在"`.
- Image decoding is UI-only via `QPixmap`; `preview_strategy.py` returns only the image path.
- `DataDetailPanel` scales image thumbnails to fit a 220x160 preview area and shows `"图片预览加载失败"` for invalid images.
- PDF preview renders the first page to a thumbnail via `QPdfDocument.render()` and avoids `QPdfView` because the widget segfaulted under offscreen tests.
- PDF preview now keeps a `QPdfDocument` in a custom `PdfPreviewPanel`, renders the current page via `QPdfDocument.render()`, and exposes previous/next page controls instead of embedding `QPdfView`.
- Other heavy professional formats remain metadata-first until dedicated parsers/viewers are introduced: LAS, SGY, SEGY, XLSX, XLS, PPT, PPTX, WLP, and DFB.

## Data Page V2 Interaction Notes

- The lower data workspace uses `QSplitter` with catalog, asset table, and detail preview panels; the action panel remains fixed-width outside the splitter so buttons do not collapse.
- `DataDetailPanel` uses `setMinimumWidth(240)` instead of `setFixedWidth(260)`, allowing the preview panel to expand for PDFs and images.
- Data actions are non-destructive: `移出项目` unregisters resources but never deletes source files.
- `重新扫描` handles missing files by setting resource status to `missing` and preserving the project record.
- `TextSidebar` no longer uses the "上下文面板 (待实现)" placeholder. It renders page-specific context text for every AppShell page and receives live data counts from `AppShell.update_data_page()`.

## Project Management V1 (Phase 14) Notes

### Architecture Decision: Window-Level Controller

Per spec, project lifecycle logic lives in `PaleoWorkbenchWindow` (`app.py`), not a separate controller class. V1 scope is small enough (4 actions, no autosave/recent-projects/command-history) that a controller class would be premature.

### Shell Rebuild Pattern (critical for new/open)

When the active project changes (new/open), the entire `AppShell` is rebuilt rather than individually updating each page. This avoids stale references — `DataPage` and other pages are constructed from `AppShell.project` at build time, so a new project requires a new shell.

Decomposition:
- `_refresh_shell()`: tear down old shell (`removeWidget` + `setParent(None)` + `deleteLater()`), build new `AppShell(project=self.project)`, call `_apply_project_to_shell()`, re-add to layout.
- `_apply_project_to_shell()`: extracted from `__init__` — runs `set_project_name` + all `update_*` calls. Called by both `__init__` and `_refresh_shell`.
- `_wire_toolbar()`: connects the 4 HeaderToolbar signals to handlers. **CRITICAL**: called from BOTH `__init__` and `_refresh_shell`, because each rebuild creates a new `HeaderToolbar` whose signals would otherwise be dead. Guarded by `test_toolbar_signals_wired_after_refresh`.

### Non-Destructive Open (atomicity contract)

`open_project_path(path) -> bool` loads into a local var FIRST, then assigns `self.project`/`self.project_path` only after success. Any exception (JSONDecodeError, ValidationError, OSError) → return False, current project fully unchanged. This ordering is the airtight part — never assign self.project before load() completes.

### Extension Normalization

`save_project_as` normalizes the filename to end in `.paleo.json`: appends if missing, does NOT double-append if already present. Handles `"p"` → `"p.paleo.json"`, `"p.json"` → `"p.paleo.json"`, `"p.paleo.json"` → unchanged. Uses `Path.with_name()` so directory components are preserved.

### Dialog Testability Seams

`_choose_open_project` / `_choose_save_project` / `_show_project_error` / `_show_properties` are isolated private methods, monkeypatched in tests. NEVER instantiate real `QFileDialog`/`QMessageBox` in tests (would block CI). The path-based public methods (`open_project_path`, `save_project_as`) are the testable surface; dialogs are thin wrappers.

### Save Flow Amendment

`save_project()` final design: if `project_path` set → save there; else call `_choose_save_project()` and save to chosen path (or return None on cancel). This makes `_on_save_project` a one-liner. A Task 2 unit test premise ("returns None without dialog") had to be updated in Task 3 to monkeypatch the dialog — expected cross-task evolution.

### Baseline Lesson (geo-viz-engine deps)

07-06 接入 geo-viz-engine-backed pages (Seismic/WellLog/Visualization/Mapping) but did not declare the engine's heavy deps (scipy/segyio/pyqtgraph/PyOpenGL/matplotlib/shapely) in the main project. The engine's subpackages declare their own deps, but only get installed if each subpackage is `pip install -e`'d individually — they are NOT published to PyPI and the engine's top-level pyproject lists them as external deps that pip can't resolve.

Resolution: `requirements-geoviz.txt` lists all 8 subpackages in dependency order for `pip install -r`. The `pytest.ini pythonpath` makes tests work without installation, masking the gap. **Future pages adding geo-viz imports must ensure the subpackage is in `requirements-geoviz.txt` + `pythonpath`.**

## Data Page UI/Perf Optimization (Phase 15) Notes

### Architecture decisions (approved design Approach A)

- **Surgical only:** keep `DataWorkspace` (table | reader) + floating catalog/actions; no card-layout rollback.
- **Virtual table:** `QTableView` + `AssetTableModel` with `_filtered_rows: list[int]`. Never materialize thousands of `QTableWidgetItem`s. Column defs in `data_table_columns.py` to avoid circular imports.
- **FilterIndex:** pure category + substring filter over precomputed haystacks. Category semantics must match catalog (`全部` / role buckets / `异常` / `CATEGORIES` type map). Currently still imports `CATEGORIES` from `data_catalog_panel` (Qt panel) — purity nit for later.
- **Single model reset:** production path uses `set_assets_filtered(assets, rows, column_keys=...)` once per apply; avoid triple `beginResetModel`.
- **Preview pipeline:** UI-thread `PreviewRequestController` + generation tokens; `PreviewProvider.preview` is pure (no shared dict cache). Worker only builds `PreviewResult` dataclasses (no Qt widgets).
- **PreviewCache:** LRU 32 on controller (UI thread only). Key = kind, id, path, type, format, checksum, optional `(size, mtime_ns)` from `Path.stat()`. Type/format in key so rescan reclassification is a miss without model field changes.
- **Serial latest-only queue (post-review fix):** at most one in-flight `QThread`. Newer cache-miss requests replace `_pending`; superseded assets never start. Prevents unbounded concurrent LAS/SEG-Y work.
- **Shutdown:** `controller.shutdown()` on `DataPage.closeEvent` and `QEvent.DeferredDelete` so shell rebuild (`deleteLater`) does not destroy live threads.
- **Import path:** still one `_apply_import_report` → `update_state` → one table reset; does not rebuild reader for prior selection.

### Data page public contracts to preserve

- `DataPage.update_state(state, resources, artifacts=None)`
- Import / rescan / remove / open-folder
- `data_context_changed` payload (counts + selection + reader_mode)
- Toolbar search, catalog category, column settings
- Floating panels as overlays (not splitter children)

### Test patterns learned

- After selection via DataPage, **always** `qtbot.waitUntil` for reader mode (async). AppShell sidebar tests must wait before asserting `阅读器: text`.
- Tests that spin workers should `_wait_controller_idle` (jobs empty) before teardown.
- Import batch: assert `modelAboutToBeReset` count == 1, not just final row count.
- Rescan vs in-flight: gate first provider call with `threading.Event`, rescan, release, assert FRESH not STALE.

### Residual (non-blocking) perf notes

1. ~~Image/PDF still decode on UI thread after path-only async result~~ → **fixed**: worker `preload_media` loads image/PDF file bytes; small payloads kept in LRU (≤512KB); path-only cache hits re-read via `_MediaPreloadWorker`; UI only does QPixmap/QPdfDocument from bytes (Qt affinity). PDF structure parse/render still UI-bound (QtPdf not worker-safe).
2. `FilterIndex.rebuild` runs on every filter apply; could rebuild only when asset list changes (table path may already gate).
3. ~~Floating catalog tab does not sync toolbar check state~~ → fixed.
4. ~~Search haystack uses raw English type keys~~ → fixed (Chinese labels).

### Delivery trail

- Spec: `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md`
- Plan: `docs/superpowers/plans/2026-07-10-datapage-ui-perf-optimization.md`
- PR: https://github.com/WindWang2/paleo-workbench/pull/1 (merged `bc8b68b`)
- Worktree used: `.worktrees/datapage-ui-perf` on `feature/datapage-ui-perf`

## Mapping Editor V1 + C++ core notes

- **Layout:** GIS shell (toolbar / layer tree / MapEditView / attribute table), not the old fixed three-column display page.
- **Edit path:** QGraphicsScene items; geometry ops via `map_edit_api` façade.
- **Native:** `map_edit_core` pybind11 module under `native/map_edit_core/`. Hot path preference; Python fallback always works. Install with `pip install -e native/map_edit_core`.
- **Document:** `line_features` / `label_features` on `PaleoMapDocument`; save draft writes memory document (disk via project save).
- **Post-V1 shipped:** facies polygon draft tool; geometry hit-test select; line/facies vertex edit; **图面预览** mode; **forced topology rebuild** (shared-node snap + adjacency), merge/split (shapely), CI `HAS_CPP`.
- **Out of scope still:** QGIS, full multi-page print cartography, advanced shared-edge topology constraints.
- **Preview mode notes:** `preview_payload_from_*` converts editor rings → GeoJSON Feature and wells → `{lng,lat}` for canvas; unsaved dirty scene geometry is preferred over document; edit tools disabled while preview on; sidebar shows `模式: 编辑|图面预览`.
- **Topology rebuild:** pure-Python shared-node clustering; merge/split prefer shapely; undo via `BatchVertexEditCommand` / `CompositeCommand`.
- **CI:** Ubuntu job installs pybind11, builds `native/map_edit_core`, asserts `HAS_CPP`, runs full suite offscreen.

## Visualization geo-viz adapter (Phase 17) notes

### Adapter boundary

- **`paleo_workbench/viz/` is pure** — no Qt widgets, no AppShell page construction. Allowed bridges only: `mapping_helpers.preview_payload_from_document`, prediction mock helpers (`well_log_data_from_prediction`, `seismic_volume_from_prediction`).
- **UI owns canvases** — `CompositeVisualizationPanel` hosts `WellLogCanvas` / `SeismicView` / `CrossWellWidget` / `PaleoMapCanvas`; adapter only produces `VizPayload`.
- **Soft failure contract:** `resolve` and `from_prediction` never raise into UI handlers; missing/corrupt/unreadable → `kind="message"` with human text. Message path **clears** well/cross-well/map so prior graphics do not linger (seismic has no empty-clear API).

### Bounds constants

| Loader | Constant | Default |
|--------|----------|---------|
| LAS | `MAX_CURVES` / `MAX_SAMPLES` | 12 / 2000 (stride long curves) |
| SEGY | `MAX_DIM` / product budget | 64 / 64³; set `payload.warning` when downsampled |

### Jump wiring

1. Data page: `supports_resource` → enable 「在可视化中打开」 → emit `open_in_visualization(VizRef)` with `source="data_page"`.
2. Window: `icon_rail.set_active(PAGE_INDEX_VISUALIZATION)` + `_switch_page(5)` + `VisualizationPage.open_ref(ref)`.
3. Visualization: `adapter.resolve(ref, project_or_stub)` → `load_payload` + `trace.update_ref`.
4. Refresh: `_reload_current` re-resolves `_current_ref`; if no ref, `update_state(prediction_tasks)` mock fallback.
5. Load priority (测井/地震): current `VizRef` → else prediction mock → else empty.

### Tests / packaging notes

- Monkeypatch dotted paths into `paleo_workbench.ui.pages.*` can fail because pages package uses lazy `__getattr__` — patch the imported module object instead.
- Jump tests must drain/shutdown data-page preview QThreads before teardown (offscreen abort risk).
- Tab identity in tests: prefer `tabs.tabText(...)` over hard-coded indices (古地理 may move).

## Multimodal Preview Formats (Phase B) Notes

### Pipeline Extension Pattern (confirmed)

The preview pipeline is a clean 3-stage chain; each new format adds exactly 3 touch points:
1. `PreviewProvider._build_preview()` — format-set dispatch branch (before TEXT_FORMATS/IMAGE_FORMATS), returns `PreviewResult(mode=..., <fields>)`.
2. `preview_widgets.py` — concrete render widget.
3. `DataReaderPanel.render()` — stack slot + dispatch branch (before message fallback).

The existing `PreviewCache` (LRU 32), generation-based invalidation, and off-thread media preload apply automatically. New modes only need preload extension if they carry file-bytes payloads (`geotiff` needed it for cache-stripped thumbnails).

### Dispatch Ordering (load-bearing)

`GEOTIFF_FORMATS` overlaps `IMAGE_FORMATS` (both contain tif/tiff) — GeoTIFF dispatch MUST precede IMAGE_FORMATS. GeoTIFF takes precedence; non-GeoTIFF tiffs fail rasterio → image fallback → same outcome. Similarly MARKDOWN/JSON/AUDIO all precede TEXT_FORMATS (`.json` was removed from TEXT_FORMATS to eliminate the latent ordering trap).

### Worker-Thread Safety Invariants

- ✅ Pure off-thread: markdown→HTML, json.loads, rasterio.open/read, Pillow PNG encode.
- ❌ UI-thread-only: QStandardItemModel population, QPixmap.decode, QMediaPlayer.setSource.
- Payloads crossing threads: strings (`rich_html`), Python objects (`json_payload`), bytes (`image_bytes` PNG), scalars (`media_path` path only — no media decode off-thread).

### GeoTIFF Triple-Fallback

`_geotiff_preview` has 3 independent failure paths all routing to `_image_fallback`:
1. `ImportError` (rasterio not installed)
2. rasterio open/read `Exception` (corrupt file, not a raster)
3. Pillow encode `Exception`
Each returns `mode="image"` + warning "地理元数据读取失败，仅显示图像" + raw file bytes.

### JSON Large-Array Lazy Expansion

`JsonTreePreviewWidget._build_row`: arrays >100 items → collapsed "[N items]" node storing the list in `Qt.ItemDataRole.UserRole` with 0 children. The `expanded` signal handler reads UserRole and populates children on first expand, guarded by a `rowCount()==0` check (idempotent). The full parsed payload always ships from the worker (5MB cap); only the tree-model rendering is lazy.

### GeoTIFF Cache-Strip Edge Case

`cacheable_result` strips `image_bytes` >512KB. A large GeoTIFF thumbnail exceeding this becomes path-only in cache; on re-select, `needs_media_preload` (extended for geotiff mode) re-reads bytes off-thread. Note: this re-read gets RAW TIFF bytes (not the decimated PNG), so `GeoTiffPreviewWidget` depends on Qt's TIFF image plugin for the thumbnail — metadata table still renders from cached `geo_metadata`.

### Known Upstream Warning

rasterio 1.5.0 + numpy 2.5: `dataset.read(out_shape=...)` emits a DeprecationWarning (numpy shape mutation). Harmless; will need a rasterio bump when numpy hard-removes the API.

## DEVONthink Three-Pane Layout (Phase A) Notes

### Layout Migration

DataPage went from `QGridLayout` + 2 FloatingPanel overlays (catalog top-left, actions bottom-right over a 2-way QSplitter) to a fixed 3-segment horizontal QSplitter: NavigationTree | DataAssetTable | RightColumn(vertical QSplitter: DataReaderPanel | InspectorPanel). Both splitters `setChildrenCollapsible(False)`.

### Category Contract Preservation

The critical invariant: NavigationTree emits the SAME category-name strings (`CATEGORIES` dict keys) that `FilterIndex._matches_category` consumes. `FilterIndex`/`AssetTableModel`/`DataAssetTable` source is untouched. The tree is purely a new view over the existing filter model. `CATEGORIES` was moved from `data_catalog_panel.py` to `filter_index.py` (its canonical semantic home) to resolve a circular import.

### Count Logic Extraction

`compute_category_counts(resources, artifacts)` extracted from the deleted `DataCatalogPanel.update_counts` into `filter_index.py`. Pure function, Counter-based. Both NavigationTree and (formerly) DataCatalogPanel consume it.

### Signal Rewiring (Task 5 integration risks)

Two bugs caught during integration:
1. **Signal double-fire**: legacy per-button `clicked.connect` lines remained alongside the new toolbar-signal connections → handlers fired twice. Fixed by removing the redundant per-button wiring.
2. **Reader-toggle direction**: `_toggle_reader_from_toolbar` keyed off `reader_panel.isHidden()`, but `set_right_visible` hides the parent `right_splitter` (which makes `reader_panel.isHidden()` return True even when it was "visible"). Fixed by keying off `right_splitter.isHidden()`.

### What was deleted

- `DataCatalogPanel` (replaced by NavigationTree)
- `ActionPanel` (buttons moved to DataToolbar)
- `FloatingPanel` (no longer used — fixed panes replaced overlays)
- Their tests (`test_data_catalog_panel.py`, `test_floating_panel.py`)

### Known display refinements (deferred)

- `reader_btn` labeled 阅读器 but hides the whole right column (reader + inspector). Relabel pending.
- 成果/参考资料/异常 group headers show 0 (no children — they're aggregate-only groups). Display refinement.
- `测井参考` (well_reference) type has no leaf in the tree (omitted from TYPE_LEAVES) — counted under 参考资料 aggregate but not individually clickable.
- Lost selection-status text (legacy ActionPanel.selection_status_label gone; inspector empty/populated state conveys selection instead).

## Concurrent Resource Scan (Phase C) Notes

### Why ThreadPoolExecutor (not Process/async)

- `stat()` releases GIL during the kernel call.
- `hashlib.sha256` is a C extension that releases GIL during hash computation.
- File `open/read` is I/O (releases GIL).
- So threads achieve real parallelism for both I/O and CPU portions. ProcessPool would add ResourceItem serialization overhead + spawn latency; asyncio wouldn't help the checksum CPU work.

### _process_file Extraction

The per-file loop body extracted to a module-level `_process_file(path, project_path, skip_checksum_over_bytes) -> ResourceItem | None`. Module-level (not nested) so it's independently testable and monkeypatchable. Stateless — all transitive helpers (classify_path, _checksum, relativize_path) are pure functions with no shared mutable state.

### Graceful Vanished-File Skip (behavior refinement)

stat OSError (file vanished between rglob and processing) → `_process_file` returns None → filtered from results. Previously this would raise uncaught, abortting the whole scan. The graceful skip is strictly safer. checksum OSError behavior is unchanged (sets checksum_error flag, still includes the resource).

### S5 Stress Validation

Env-gated (`DATAPAGE_STRESS_S5=1`, N override via `DATAPAGE_STRESS_S5_N`). At small N (100) thread-pool overhead makes concurrent slower than serial — expected and irrelevant (the win is at N=10000 with real checksums). The test asserts correctness only (count + order), prints both timings, no wall-clock gate — consistent with Phase 21's measurement philosophy.

### Phase C Scope Discovery

Original plan had 3 items (virtual scrolling, import concurrency, search debounce). Exploration revealed Phase 15 already shipped virtual scrolling + debounced search (measured non-hotspots: S1=4ms, S2=0.5ms at N=2000), and Phase 21 shipped checksum skip. The only real gap was serial scan — so Phase C became a focused single-improvement spec rather than a 3-part project. YAGNI applied: a real inverted index for FilterIndex was considered and rejected (linear scan fast enough at measured scale).

---

## 2026-07-16 — Full-project audit findings (Phase 22)

### Already fixed before this session (prior deep_audit)
- chart_engine `utils` import, `_well_names` init, seismic `setShading`/loader `f`, hash()-based colors, `nice_number` negatives, IDW empty → NaN, WellLog path cache / mouseMove.

### Fixed this session (high confidence)

| Severity | Issue | Fix locus |
|----------|-------|-----------|
| high | DTW paint `QPainterPath.DashLine` AttributeError | `geoviz_cross_well/correlation_layer.py` |
| high | Multi-ring polygon drag uses outer-ring index only → holes jump/(0,0) | `edit_commands.MovePolygonCmd`, `edit_engine` |
| high | `geoviz_map` ScreenPathCache ignores pan center | `geoviz_map/screen_path_cache.py` (port paleo `_zoom_center`) |
| high | Sonic integration labeled TWT but was OWT | `well_tie/calibration.from_sonic` ×2 |
| high | `_apply_curve_meta` dropped `unit` | `qpainter_builder.py` |
| high | Map draft save stripped prediction properties | `mapping/document_io.apply_features_to_document` |
| high | Reference layer paths not relativized on project I/O | `project/manager.py` |
| high | GDAL datasets never closed | `mapping/reference_layers.py` |
| high | SEGY preview double full-trace pass | `viz/seismic_load.py` single pass |
| high | Import QThread destroyed while running on shell rebuild | `data_page._shutdown_import_jobs` |
| high | Mapping `update_state` always load last doc + wipe dirty | preserve `prefer_id` + skip reload if same dirty doc |
| high | Document tree switch discards dirty with no prompt | Save/Discard/Cancel |
| high | Project save did not flush map scene | `app._flush_mapping_draft` |
| high | PaleoMapAdapter GeoJSON always empty FeatureCollection | serialize `layers`/`features` |
| medium | QC `StopIteration` / status never `error` | `workflow/qc.py` |
| medium | Non-atomic project write; stale `updated_at` | tmp + `os.replace` |
| medium | Closed-ring insert_vertex opened ring | re-close after insert |
| medium | factor_tasks never passed to mapping page | `update_mapping_page(..., factor_tasks=)` |
| medium | Line vertex cancel only restored facies | `FaciesPolygonItem \| LineItem` |
| medium | Media kept playing after leave preview | `MediaPreviewWidget.stop` |
| medium | Page fade left previous page at partial opacity | clear previous effect |

### Still open (backlog)

1. **Seismic Auto-Tie:** ✅ `SeismicView` connects `auto_tie_requested` → `current_seismic_trace` → `panel.auto_tie`; `synthetic_changed` → IL/XL overlay.
2. **Hidden layer hit-test:** ✅ `hit_test_at` / `_feature_item_at` skip layers with `layer_is_visible=False` (export still full).
3. **Demo draft append:** ✅ `compile_map_draft` replaces same-generator demo (stable id); user maps untouched.
4. **Path escape:** ✅ relative paths confined to project dir (`ProjectPathError`); absolute external still allowed.

### Architecture notes from audit

- Prefer **vertex-id maps** over positional lists for multi-ring topology commands.
- Screen-space path caches that bake `center_world` must invalidate on pan **and** resize.
- Shell rebuild via `deleteLater` must shut down **all** page-owned `QThread`s (preview + import), not only preview.
- Export adapters that write placeholders should either implement real geometry or surface explicit warnings (now: geojson real + warnings).

---

## Subproject boundary: geo-viz-engine

`geo-viz-engine/` is a **git submodule** of paleo-workbench and the **visualization algorithm + widget library** for the product:

| Layer | Owns | Does not own |
|-------|------|----------------|
| **geo-viz-engine** | SEGY/LAS/map/plot pipelines, `PreparedPreview`, QPainter/OpenGL widgets, slice scrub, DTW/colormap math | Project file lifecycle, DataPage catalog, import/dedupe |
| **paleo_workbench** | AppShell, project I/O, pages, `VizAdapter` wiring, sample pipeline | Low-level seismic/well-log render kernels |

Install: editable subpackages via `requirements-geoviz.txt` + root `pythonpath`. Prefer fixing viz bugs **in the engine**; workbench only integrates.

---

## 2026-07-16 — SEGY data-page slice scrub (Phase 23)

### Product intent

Data page SEGY preview is **bounded 2-D slices**, not full 3-D OpenGL. Users need to **scrub position** along the current axis without leaving the reader pane. Implementation is **engine-side** so any host of `SeismicPreviewWidget` gets scrub for free.

### Design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Memory model | Keep middle-slice preload; scrub re-reads **one** slice from disk | Large SEGY cannot fit full volume in preview worker budget |
| Axis metadata | `SeismicAxisSpec(start, step, count)` on payload | Slider index → SEGY line/sample without re-inspect |
| Package boundary | `load_preview_slice` lives in **geoviz_seismic**, not engine-only | Widget must not import `geoviz` engine (layering) |
| Debounce | 80ms single-shot QTimer | Avoid open/read/close per mouse pixel |
| Failure | Overlay text `切片加载失败: …` | Reader stays up; no crash |

### UX

```
[Inline ▾]  [========●========]  Inline: 105
[ ProfileWidget heatmap…              ]
```

Mode change resets slider range from `axes[mode]`; preloaded middle position used when present.

### Interaction capability

`PreviewCapabilities.interactions` includes `slice_scrub` alongside `slice_switch`, `zoom`, `pan`.

---

## 2026-07-16 — Visualization modularization (Phase 24)

### Target architecture
Workbench **hosts** engine product surfaces; does not reimplement parse/render.

| Host | Engine widget | Load API |
|------|---------------|----------|
| WellLogHost | WellLogCanvas | `build_qpainter_tracks(load_las_preview(...))` |
| SeismicHost | SeismicView | `load_segy(path)` → fallback `load_demo(volume)` |
| CrossWellHost | CrossWellCanvas | multi WellLogCanvas via package API |
| PaleoMapHost | PaleoMapCanvas | `load_features` (edit stays MappingPage) |
| EnginePreviewHost | GeoVizPreviewHost | `GeoVizEngine.prepare/render` (DAT/plots/scrub) |

### Rules
1. Production imports: only `geoviz` facade names in allowlist.
2. Dual LAS/SEGY loaders removed: engine is single source of truth.
3. Composite panel must not grow domain logic — route payload to hosts only.

### Still deferred
- Wire composite export button to engine `export_*`
- Well-tie workspace tab
- Full SeismicView horizon/attribute project wiring

---

## 2026-07-16 — Module-by-module review (goal: find issues)

### Method
- Static AST boundary scan (workbench → geoviz facade only): clean
- Runtime smoke import/export/viz/qc: clean
- 3 parallel read-only reviewers: resources I/O · viz hosts · project/mapping/workflow
- Fix high-confidence bugs + **66 passed** focused suite

### Module scorecard

| Module | Status | Top issues (before fix) |
|--------|--------|-------------------------|
| **resources/import** | OK after enrich | Roles/summary good; UI must pass project_path (residual medium) |
| **resources/export** | Fixed | Inventory menu unwired; relative path not resolved |
| **resources/classifier** | OK | geojson/vector/csv |
| **viz/hosts** | Fixed | Stale tabs; seismic full-volume OOM risk; clear incomplete |
| **viz/adapter** | Fixed | False SEGY message; formation_tops alias |
| **ui/data_page** | Fixed | Import slots off UI thread; inventory; reclassify roles |
| **ui/visualization** | Fixed | project never wired; export registration dead |
| **app lifecycle** | Fixed | save ignored failed map draft flush |
| **mapping/document_io** | Partial fix | normalize_facies now keeps attrs; FaciesPolygonItem extras |
| **workflow/qc** | OK (prior) | residual: reports only append |
| **adapters/paleo_map** | OK geojson | residual: pdf/svg placeholder |

### Fixed this review pass
1. Wire 工程清单 export action
2. Import finished/failed → QueuedConnection (GUI thread)
3. `load_payload` always `_clear_all` before apply
4. SeismicHost prefers budgeted `load_demo(volume)`
5. `update_visualization_page(..., project=)`
6. `_flush_mapping_draft` returns bool; gate project save
7. `normalize_facies` + FaciesPolygonItem extras round-trip
8. formation_tops → well_stratification for engine prepare
9. Manual reclassify updates artifact_role/tags
10. export_service resolves relative asset paths

### Residual (not fixed this pass)
- Import/rescan still often omit real `project_path` from window
- Demo map generate without dirty prompt
- Reference layer offline status
- QC report append inflation
- SVG/PDF button enable gating by tab (tooltip only)
- Non-geojson PaleoMapAdapter placeholder formats
