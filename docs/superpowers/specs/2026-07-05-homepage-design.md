# HomePage Dashboard Design

> **Date:** 2026-07-05
> **Status:** Approved (pending user spec review)
> **Predecessor:** `2026-07-05-appshell-design.md`
> **Scope:** 首页 real content — workflow progress + recent activity + data completeness

## Background

The AppShell skeleton (commit `203c457`) has 9 placeholder pages. This spec implements real content for the 首页 (HomePage), replacing its `PagePlaceholder` widget. The 首页 is the first page users see — it shows the compilation workflow status, recent activity, and data readiness at a glance.

Layout data extracted from the standalone prototype via headless browser computed-CSS inspection.

## Goal

Replace the 首页 placeholder with a production dashboard containing: a 6-step workflow progress bar, a recent activity card, and a data completeness card. All data comes from the existing `dashboard_state()` function and `CompilationRun.workflow_steps`.

## Non-Goals

- Clicking a workflow step to trigger actions (display-only this phase).
- Clicking an activity item to navigate (display-only).
- Charts or visualizations inside cards (text/list only this phase).
- Real-time activity log (derived from workflow step status, no event sourcing).
- Other page content (only 首页 in this spec).

## Layout Structure

```
┌─ HomePage (bg #eef0f4, padding 16px) ──────────────┐
│                                                     │
│  ┌─ WorkflowProgress (horizontal, 6 steps) ────────┐ │
│  │ [1]数据管理  [2]数据转换  [3]制图数据制备       │ │
│  │  [4]沉积相预测 [5]古地理图编制 [6]质控与导出    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  ┌─ 最近活动 ──────┐  ┌─ 数据完整度 ─────────┐      │
│  │ ~412×252px      │  │ ~324×252px           │      │
│  │ activity list   │  │ readiness indicators  │      │
│  └─────────────────┘  └──────────────────────┘      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- HomePage replaces `PagePlaceholder("首页")` at index 0 in AppShell's QStackedWidget.
- Outer layout: QVBoxLayout with 16px margins, 16px spacing.
- WorkflowProgress takes full width.
- Bottom row: QHBoxLayout with activity card (stretch proportional) + completeness card (fixed ~324px).

## Components

### WorkflowProgress Widget

Horizontal row of 6 step cards, each containing:
- Numbered badge: 30x30px, border-radius 8px, white text, colored per step.
- Step label: Chinese name, font-size 13px, font-weight 500, color #28323f.
- Status text: e.g. "完成" / "进行中" / "待开始", font-size 11px, color #7e8794.
- Connected by a horizontal line between badges.

Step mapping (prototype labels → existing step_type):

| # | Display Label | Badge Color | step_type |
|---|---------------|-------------|-----------|
| 1 | 数据管理 | `#1f6fe0` | data_check |
| 2 | 数据转换 | `#0f93a4` | factor_map |
| 3 | 制图数据制备 | `#6f47cf` | prediction |
| 4 | 沉积相预测 | `#c47e12` | map_compile |
| 5 | 古地理图编制 | `#e2705b` | qc |
| 6 | 质控与导出 | `#7e8794` | export |

Status display mapping (WorkflowStep.status → Chinese text + visual):
- complete → "完成" (green checkmark)
- running → "进行中" (blue pulse)
- ready → "就绪" (blue dot)
- warning → "警告" (amber triangle)
- failed → "失败" (red x)
- pending → "待开始" (gray circle)
- skipped → "已跳过" (gray dash)
- mock → "Mock" (purple tag)

Data source: `CompilationRun.workflow_steps` from the active run. If no active run, all steps show "待开始".

### RecentActivityCard Widget

Card with title "最近活动" and a scrollable list of activity entries.

- Card style: bg `#ffffff`, border `1px solid #e2e6ec`, border-radius 9px, padding 16px.
- Title: "最近活动", font-size 14px, font-weight 600, color #28323f.
- Activity entries: each row has a timestamp (left, 11px, #7e8794) + description (right, 12.5px, #28323f).
- Data source: derived from `CompilationRun.workflow_steps` — each step with status != "pending" generates an activity entry: "{step_label}: {status_text}".
- If no active run or all steps pending: show "暂无活动" placeholder.
- Max 10 entries shown; scrollable if more.

### DataCompletenessCard Widget

Card with title "数据完整度" and resource readiness indicators.

- Card style: same as RecentActivityCard.
- Title: "数据完整度", font-size 14px, font-weight 600.
- Three resource type rows, each with:
  - Type name: "测井数据" / "地震数据" / "层位数据"
  - Count badge: e.g. "57井" / "8条测线" / "3层位"
  - Status indicator: green checkmark (available) or red x (missing)
- Data source: `dashboard_state().resource_readiness` — well_log / seismic / horizon.
- Bottom row: overall readiness text — "数据完整" (green) or "缺少: {missing_types}" (red).

## Architecture

### File Structure

```
paleo_workbench/ui/pages/
  __init__.py            # exports HomePage
  home_page.py          # HomePage(QWidget) — assembles 3 sub-widgets
  workflow_progress.py  # WorkflowProgress(QWidget) — 6-step horizontal bar
  activity_card.py      # RecentActivityCard(QFrame) — activity list
  completeness_card.py  # DataCompletenessCard(QFrame) — readiness indicators
```

### HomePage Assembly

`HomePage(QWidget)` replaces the PagePlaceholder at index 0.

```python
class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.workflow_progress = WorkflowProgress()
        layout.addWidget(self.workflow_progress)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        self.activity_card = RecentActivityCard()
        self.completeness_card = DataCompletenessCard()
        bottom.addWidget(self.activity_card, 1)
        bottom.addWidget(self.completeness_card, 0)
        layout.addLayout(bottom, 1)

    def update_state(self, state: dict, steps: list) -> None:
        self.workflow_progress.update_steps(steps)
        self.activity_card.update_state(state, steps)
        self.completeness_card.update_state(state)
```

### Integration with AppShell

- `AppShell._switch_page` already handles page switching.
- `PaleoWorkbenchWindow` (app.py) will call `app_shell.update_home_page(project)` after creating the AppShell, which delegates to `HomePage.update_state(dashboard_state(project), active_run.workflow_steps)`.
- The AppShell needs a `home_page` reference and an `update_home_page` method.

### Design Tokens

New tokens needed in `tokens.py`:

| Token | Value | Usage |
|-------|-------|-------|
| `STEP_COLORS` | `["#1f6fe0", "#0f93a4", "#6f47cf", "#c47e12", "#e2705b", "#7e8794"]` | Workflow step badge colors |
| `STEP_LABELS` | `["数据管理", "数据转换", "制图数据制备", "沉积相预测", "古地理图编制", "质控与导出"]` | Step display labels |
| `STATUS_TEXT` | `{"complete": "完成", "running": "进行中", ...}` | Status → Chinese text |
| `SUCCESS` | `#1f9d57` (existing) | Complete checkmark color |
| `WARNING_AMBER` | `#c47e12` (existing, = step 4 color) | Warning indicator |
| `ERROR_RED` | `#dc2626` | Failed/missing indicator |

### Card QSS

Cards use inline stylesheet referencing tokens (not global QSS) since they are page-specific:

```python
card.setStyleSheet(f"""
    QFrame#ActivityCard, QFrame#CompletenessCard {{
        background: {tokens.BG_SIDEBAR};
        border: 1px solid {tokens.BORDER};
        border-radius: {tokens.RADIUS_CARD}px;
    }}
""")
```

## Testing

### Unit Tests (target: 20+ new tests)

- `tests/test_workflow_progress.py`: 6 steps rendered; correct badge colors; status text mapping; default all pending when no run.
- `tests/test_activity_card.py`: Title text; entries from steps; empty state "暂无活动".
- `tests/test_completeness_card.py`: 3 resource types; count badges; missing type display; overall readiness.
- `tests/test_home_page.py`: Assembles 3 sub-widgets; update_state delegates correctly.
- `tests/test_home_integration.py`: AppShell page 0 is HomePage (not PagePlaceholder); update_home_page populates state.

### Regression

- All existing 57 tests must still pass.
- AppShell tests that check `page_stack.count() == 9` and `currentIndex() == 0` still hold (HomePage replaces placeholder at index 0, count unchanged).

## Acceptance Criteria

1. 首页 shows 6-step workflow progress bar with colored badges.
2. Each step shows correct label and status text from workflow data.
3. 最近活动 card shows activity entries derived from workflow steps.
4. 数据完整度 card shows resource readiness for well_log / seismic / horizon.
5. `python -m paleo_workbench.main` launches with 首页 as default page showing real content.
6. All 57 existing + 20+ new tests pass.
