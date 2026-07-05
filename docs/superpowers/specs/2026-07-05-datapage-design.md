# DataPage Design

> **Date:** 2026-07-05
> **Status:** Approved (pending user spec review)
> **Predecessor:** `2026-07-05-appshell-design.md`
> **Scope:** 数据页 real content — resource summary + resource table + action panel

## Background

The AppShell has 9 pages. 首页 (index 0) has real content (HomePage dashboard). The remaining 8 are placeholders. This spec implements real content for the 数据 page (index 1) — multi-source data management showing all project resources in a table with a summary bar and action panel.

## Goal

Replace the 数据 placeholder with a DataPage containing: a resource summary bar (counts + readiness), a resource table (QTableWidget with all ResourceItems), and an action panel (import/convert buttons, non-functional this phase).

## Non-Goals

- File import dialog (non-functional buttons this phase).
- Data format conversion logic.
- Resource detail preview or editing.
- Drag-and-drop file import.
- Other page content (only 数据 in this spec).

## Layout Structure

```
┌─ DataPage (bg #eef0f4, padding 16px) ──────────────┐
│                                                     │
│  ┌─ ResourceSummaryBar (horizontal) ──────────────┐ │
│  │ 测井: 57井 | 地震: 8条测线 | 层位: 3层位       │ │
│  │ 状态: 数据完整 / 缺少: xxx                      │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ ResourceTable ─────────────────────┐ ┌────────┐ │
│  │ QTableWidget                       │ │ Action │ │
│  │ 文件名 | 类型 | 格式 | 状态 | 路径 │ │ Panel  │ │
│  │                                    │ │        │ │
│  └────────────────────────────────────┘ └────────┘ │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- DataPage replaces PagePlaceholder("数据") at index 1 in AppShell's QStackedWidget.
- Outer layout: QVBoxLayout with 16px margins, 16px spacing.
- Bottom row: QHBoxLayout with table (stretch=1) + action panel (fixed ~180px).

## Components

### ResourceSummaryBar Widget

Horizontal bar showing resource counts and overall readiness.

- Style: QFrame, bg #ffffff, border 1px #e2e6ec, border-radius 9px, padding 12px.
- Content: 3 resource type badges (name + count with unit suffix) + readiness status label.
- Each badge: resource label (12.5px, #28323f) + count (14px, bold, colored by availability).
- Readiness: "数据完整" (green #1f9d57) or "缺少: 测井数据" (red #dc2626).
- Data source: `dashboard_state().resource_readiness`.

### ResourceTable Widget

QTableWidget wrapping all project resources.

- Columns: 文件名 (name), 类型 (type), 格式 (format), 状态 (status), 路径 (path).
- Column widths: name 200px, type 80px, format 60px, status 80px, path stretch.
- Row height: 28px.
- Alternating row colors: #ffffff / #f3f5f9.
- Header style: bg #f3f5f9, font-weight 600, 12.5px.
- Type column shows RESOURCE_LABELS mapping (e.g. "well_log" → "测井数据").
- Status column shows status with color: indexed (gray), parsed (green), error (red).
- Data source: `project.resources` list.

### ActionPanel Widget

Narrow vertical panel with action buttons.

- Style: QFrame, bg #ffffff, border 1px #e2e6ec, border-radius 9px, padding 12px.
- Buttons: "导入资源" (primary #1f6fe0), "数据转换" (secondary).
- Non-functional this phase (clickable but no action wired).

## Architecture

### File Structure

```
paleo_workbench/ui/pages/
  data_page.py          # DataPage(QWidget) — assembles 3 sub-widgets
  resource_summary.py   # ResourceSummaryBar(QFrame)
  resource_table.py     # ResourceTable(QWidget) — QTableWidget wrapper
```

### DataPage Assembly

```python
class DataPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.summary_bar = ResourceSummaryBar()
        layout.addWidget(self.summary_bar)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.resource_table = ResourceTable()
        self.action_panel = ActionPanel()
        bottom.addWidget(self.resource_table, 1)
        bottom.addWidget(self.action_panel, 0)
        layout.addLayout(bottom, 1)

    def update_state(self, state: dict, resources: list) -> None:
        self.summary_bar.update_state(state)
        self.resource_table.update_resources(resources)
```

### Integration with AppShell

- AppShell uses DataPage at page_stack index 1 instead of PagePlaceholder.
- `AppShell.update_data_page(state, resources)` delegates to `DataPage.update_state`.
- `app.py` calls `update_data_page` after construction.

### Design Tokens

Uses existing tokens: BG_SIDEBAR, BORDER, RADIUS_CARD, TEXT_PRIMARY, TEXT_SECONDARY, SUCCESS, ERROR_RED, RESOURCE_LABELS, RESOURCE_UNITS, PRIMARY.

## Testing

### Unit Tests (target: 15+ new tests)

- `tests/test_resource_summary.py`: Summary bar shows 3 types with counts; readiness text; ready/missing states.
- `tests/test_resource_table.py`: Table has 5 columns; populates from resource list; type mapping; status coloring; empty state.
- `tests/test_data_page.py`: Assembles 3 sub-widgets; update_state delegates.
- `tests/test_data_integration.py`: AppShell page 1 is DataPage.

### Regression

- All existing 81 tests must still pass.

## Acceptance Criteria

1. 数据页 shows resource summary bar with counts per type.
2. Resource table populates from project.resources with correct columns.
3. Type column maps to Chinese labels.
4. Status column shows colored status indicators.
5. Action panel has import + convert buttons (non-functional).
6. All 81 existing + 15+ new tests pass.
