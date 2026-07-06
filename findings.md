# Findings: Paleogeography Workbench

## Project Architecture

- **Two repos:** `paleo_workbench` (root, business logic + UI shell) + `geo-viz-engine` (submodule, visualization rendering engine)
- **Tech stack:** Python 3.12, PySide6 6.6+, Pydantic v2, pytest+pytest-qt
- **Design system:** Standalone HTML prototype (`古地理图编制系统 (standalone).html`, 3.7MB minified bundle) is the single source of truth for UI. Colors/fonts/dimensions extracted via headless browser computed-CSS inspection.

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
- Heavy professional formats remain metadata-first until dedicated parsers/viewers are introduced: LAS, SGY, SEGY, XLSX, XLS, PDF, PPT, PPTX, WLP, and DFB.
