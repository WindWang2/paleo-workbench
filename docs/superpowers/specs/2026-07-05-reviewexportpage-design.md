# ReviewExportPage Design

> **Date:** 2026-07-05
> **Status:** Approved (pending implementation)
> **Predecessor:** `2026-07-05-preparationpage-design.md`
> **Scope:** 成图审核页 real content — QC issue table + result summary + action header

## Background

The AppShell has 9 pages. 首页 (0), 数据 (1), 制备 (6) have real content. This spec implements real content for 成图审核 (index 8, the last page) — quality-control review of paleogeographic maps plus an export-artifacts list. Data-driven from `project.quality_reports` and `project.export_artifacts`.

## Goal

Replace the 成图审核 placeholder with a ReviewExportPage containing three panels:
1. **ActionHeader** — title (map horizon), action buttons (运行检查/规则配置/导出检查报告), rules chips row.
2. **QCIssueTable** — one row per QC rule with result (通过/警告/待处理) and message.
3. **ResultSummary** — pass/warning/error counts + advisory text + export artifacts list.

## Non-Goals

- Real QC rule execution / running checks (buttons non-functional this phase).
- Rule configuration UI (button non-functional).
- Actual export generation (button non-functional).
- Map preview / facies polygon rendering (needs geo-viz-engine).
- Interactive issue resolution.
- Other page content (only 成图审核 in this spec).

## Layout Structure

```
┌─ ReviewExportPage (bg #eef0f4, padding 16px) ──────────────────────────────┐
│                                                                              │
│  ┌─ ActionHeader (full width) ─────────────────────────────────────────────┐│
│  │ 成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）                  ││
│  │ [运行检查]  [规则配置]  [导出检查报告]                                 ││
│  │ 检查规则: 层级一致性 · 未分类区域 · 低可信区 · ...                     ││
│  └────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│  ┌─ QCIssueTable (stretch 1) ─────────────────┐ ┌─ ResultSummary (~240px) ┐│
│  │ 检查项目 │ 检查说明 │ 结果说明              │ │ 检查结果输出           ││
│  │ 层级一致性│ 各层级…  │ ✓通过                 │ │ 通过项: 5  (green)     ││
│  │ 未分类区域│ 是否存在…│ !警告 1处未分类       │ │ 警告项: 2  (amber)     ││
│  │ 低可信区  │ 是否复核 │ !待处理 1处未复核     │ │ 待处理项:1 (red)       ││
│  │ ...      │          │                       │ │                         ││
│  └────────────────────────────────────────────┘ │ 建议先处理待处理项...   ││
│                                                  │                         ││
│                                                  │ ─ 导出图件 ─           ││
│                                                  │ • GeoTIFF — path1       ││
│                                                  │ • Shapefile — path2     ││
│                                                  └─────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

- ReviewExportPage replaces `PagePlaceholder("成图审核")` at index 8.
- Outer: `QVBoxLayout`, 16px margins, 16px spacing.
- ActionHeader: full width on top (stretch 0).
- Content row: `QHBoxLayout`, 16px spacing.
  - `QCIssueTable` (stretch 1)
  - `ResultSummary` (fixed ~240px, stretch 0)

## Components

### ActionHeader Widget — `action_header.py`

Top banner with title, buttons, and rules chips.

- Style: QFrame, bg `BG_SIDEBAR`, border 1px `BORDER`, radius `RADIUS_CARD`, padding 12px.
- Title label: `f"成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）"`. Horizon derived from the map document linked to the first quality report (`linked_map_document_id` → `paleomap_documents` → `linked_target_horizon`), or "—" if no reports.
- Button row (`QHBoxLayout`): `run_btn` (运行检查, objectName `PrimaryButton`), `config_btn` (规则配置, objectName `SecondaryButton`), `export_btn` (导出检查报告, objectName `PrimaryButton`). All non-functional this phase.
- Rules chips label: read-only `QLabel` showing `f"检查规则: {rules_joined}"` where rules_joined = " · ".join(first_report.rules) or " · ".join(DEFAULT_QC_RULES) if empty.
- `update_state(reports: list, map_documents: list)`: set title horizon from linked map; set chips text.

### QCIssueTable Widget — `qc_issue_table.py`

QTableWidget showing one row per QC rule with derived result.

- Style: mirrors `resource_table.py` (alternating row colors, header bg, border, radius).
- Columns: 检查项目 (rule, 160px), 检查说明 (description, stretch), 结果说明 (result, 160px).
- Row height: 28px.
- For each rule in the active (first) report:
  - 检查项目 = rule name.
  - 检查说明 = static description derived from rule via a `RULE_DESCRIPTIONS` map (defined in tokens; fallback to rule name itself if unmapped).
  - 结果说明 = derived: find issue in report.issues where `issue["rule"] == rule`. If found → `f"{QC_RESULT_LABELS[severity]} {message}"` (e.g. "!警告 1处未分类"); if not found → "✓通过".
  - Result cell foreground colored: pass→`SUCCESS`, warning→`WARNING`, error→`ERROR_RED`.
- `update_state(reports: list)`: use first report; populate rows. Empty state: 0 rows.

### ResultSummary Widget — `result_summary.py`

Right panel with QC result counts + advisory + export artifacts.

- Style: QFrame, bg `BG_SIDEBAR`, border 1px `BORDER`, radius `RADIUS_CARD`, padding 12px, fixed ~240px.
- Title label: `检查结果输出`.
- Three count labels (`QLabel`), each `f"{label}: {count}"`:
  - 通过项 (color `SUCCESS`)
  - 警告项 (color `WARNING`)
  - 待处理项 (color `ERROR_RED`)
- Counts computed from active report: for each rule, derive result; pass = rules with no matching issue; warning = issues with severity "warning"; error = issues with severity "error".
- Advisory label: if error count > 0 → "建议先处理待处理项后再输出成果" (color `ERROR_RED`); else "全部通过，可输出成果" (color `SUCCESS`).
- Divider (horizontal line / styled frame).
- Export section title: `导出图件`.
- Export list: `QVBoxLayout` of `QLabel`s, one per artifact: `f"• {artifact.format} — {artifact.output_path}"`. Empty state: single `QLabel` "暂无导出图件".
- `update_state(reports: list, artifacts: list)`: recompute counts; rebuild export list.

### ReviewExportPage Assembly — `review_export_page.py`

```python
class ReviewExportPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReviewExportPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.action_header = ActionHeader()
        layout.addWidget(self.action_header)
        content = QHBoxLayout()
        content.setSpacing(16)
        self.qc_table = QCIssueTable()
        self.result_summary = ResultSummary()
        content.addWidget(self.qc_table, 1)
        content.addWidget(self.result_summary, 0)
        layout.addLayout(content, 1)

    def update_state(self, reports: list, map_documents: list, artifacts: list) -> None:
        self.action_header.update_state(reports, map_documents)
        self.qc_table.update_state(reports)
        self.result_summary.update_state(reports, artifacts)
```

### Integration with AppShell

- AppShell uses `ReviewExportPage` at page_stack index 8.
- `AppShell.update_review_export_page(reports, map_documents, artifacts)` delegates to widget 8's `update_state`.
- `app.py` calls `update_review_export_page(project.quality_reports, project.paleomap_documents, project.export_artifacts)` after construction.

### Design Tokens (new)

Add to `tokens.py`:

```python
WARNING = "#c47e12"  # amber, previously only embedded in STEP_COLORS

QC_RESULT_COLORS = {
    "pass": SUCCESS,
    "warning": WARNING,
    "error": ERROR_RED,
}
QC_RESULT_LABELS = {
    "pass": "✓通过",
    "warning": "!警告",
    "error": "!待处理",
}
DEFAULT_QC_RULES = [
    "层级一致性", "未分类区域", "低可信区",
    "边界碎斑异常", "图例符号完整性", "字段与输出格式完整性",
]
RULE_DESCRIPTIONS = {
    "层级一致性": "各层级结构与命名是否一致",
    "未分类区域": "是否存在未分类或未赋值区域",
    "低可信区": "低可信区是否已复核确认",
    "边界碎斑异常": "是否存在碎斑、孤岛等异常斑块",
    "图例符号完整性": "图例符号与备注是否完整",
    "字段与输出格式完整性": "字段是否齐全、格式是否规范",
    # QC engine rule keys map to display via these too:
    "facies_polygons_present": "古地理图相带多边形是否存在",
    "target_horizon_present": "古地理图是否关联目标层位",
}
```

## Testing

### Unit Tests (target ~18 new tests)

- `tests/test_tokens.py` (extend, ~3): `WARNING` hex; `QC_RESULT_COLORS`/`QC_RESULT_LABELS` mappings; `DEFAULT_QC_RULES` length; `RULE_DESCRIPTIONS` has expected keys.
- `tests/test_action_header.py` (~4): objectName; title format with horizon; 3 buttons with correct objectNames; rules chips from report; empty state horizon "—".
- `tests/test_qc_issue_table.py` (~5): 3 columns; populates from report rules; pass result (no issue) green; warning result amber; error result red; empty state.
- `tests/test_result_summary.py` (~4): pass/warning/error counts correct; advisory text switches on error; export list populates; empty export state.
- `tests/test_review_export_page.py` (~1): assembles 3 sub-widgets; update_state delegates.
- `tests/test_review_export_integration.py` (~1): AppShell page 8 is ReviewExportPage; receives data.

### Regression

All 119 existing tests must continue to pass.

## Acceptance Criteria

1. 成图审核页 shows action header with title, 3 buttons, rules chips.
2. QC table shows one row per rule with derived result (通过/警告/待处理) and colored result cell.
3. Result summary shows pass/warning/error counts + advisory text.
4. Result summary shows export artifacts list (or empty state).
5. AppShell page 8 is ReviewExportPage (not placeholder).
6. All 119 existing + ~18 new tests pass.
