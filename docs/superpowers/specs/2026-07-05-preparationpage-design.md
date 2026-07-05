# PreparationPage Design

> **Date:** 2026-07-05
> **Status:** Approved (pending implementation)
> **Predecessor:** `2026-07-05-datapage-design.md`
> **Scope:** 制备页 real content — factor map task list + preview grid + boundary config panel

## Background

The AppShell has 9 pages. 首页 (index 0) and 数据 (index 1) have real content. This spec implements real content for 制备 (index 6) — factor map preparation showing all `FactorMapTask`s from `project.factor_map_tasks`, with a preview grid of completed factor maps and a boundary-generation config form.

## Goal

Replace the 制备 placeholder with a PreparationPage containing three panels:
1. **FactorTaskPanel** — list of factor map tasks with status badges + horizon/method header + summary footer.
2. **FactorPreviewGrid** — grid of completed factor map preview cards (name + value range + R² quality).
3. **BoundaryPanel** — probability-threshold form controls for initial facies boundary generation.

## Non-Goals

- Actual map/canvas rendering (requires geo-viz-engine — deferred to Phase 7+).
- Persisting boundary config to the project model (no model field exists today).
- Real interpolation method execution / batch generation logic.
- Facies chips with real data (placeholder text only this phase).
- Other page content (only 制备 in this spec).

## Layout Structure

```
┌─ PreparationPage (bg #eef0f4, padding 16px) ───────────────────────────────┐
│                                                                              │
│  ┌─ FactorTaskPanel (left, ~260px) ─┐ ┌─ FactorPreviewGrid ───────────────┐ │
│  │ 层位: ZJ-2       插值: 克里金 ▾   │ │ ZJ-2 单因素图集（克里金插值…）   │ │
│  │ [批量生成单因素图]                │ │ ┌──────┐ ┌──────┐                │ │
│  │ ─────────────────────────────────│ │ │ 地层  │ │ 砂体  │                │ │
│  │ ▸ 地层厚度图  克里金·50m [已生成] │ │ │ 厚度  │ │ 厚度  │  ...           │ │
│  │ ▸ 砂体厚度图  克里金·50m [已生成] │ │ │ 12-86 │ │ 2-34  │                │ │
│  │ ▸ 粒度中值图  待生成     [待生成] │ │ │ R².91 │ │ R².88 │                │ │
│  │ ...                              │ │ └──────┘ └──────┘                │ │
│  │ 已制备 6 / 8 个单因素图          │ │                                    │ │
│  └──────────────────────────────────┘ └────────────────────────────────────┘ │
│                                                       ┌─ BoundaryPanel ───┐│
│                                                       │ 初始岩相边界制备  ││
│                                                       │ 概率阈值: 0.55    ││
│                                                       │ 平滑强度: 中 ▾    ││
│                                                       │ 最小图斑: 0.5 km² ││
│                                                       │ 相带: 砂体 泥…    ││
│                                                       │ [生成初始边界]    ││
│                                                       └───────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

- PreparationPage replaces `PagePlaceholder("制备")` at index 6 in AppShell's QStackedWidget.
- Outer layout: `QVBoxLayout` with 16px margins, 16px spacing.
- Content row: `QHBoxLayout` with 16px spacing.
  - `FactorTaskPanel` (fixed ~260px width, stretch 0)
  - `FactorPreviewGrid` (stretch 1)
  - `BoundaryPanel` (fixed ~220px width, stretch 0)

## Components

### FactorTaskPanel Widget — `factor_task_panel.py`

Left sidebar listing all factor map tasks.

- Style: QFrame, bg `BG_SIDEBAR`, border 1px `BORDER`, border-radius `RADIUS_CARD`, padding 12px.
- Header row: `层位` label (target horizon name) + `插值` combobox (克里金/IDW/样条), populated from unique methods in tasks (default 克里金 if empty).
- `批量生成单因素图` primary button (object name `PrimaryButton`, non-functional this phase).
- Task list: `QVBoxLayout` inside a `QScrollArea`. Each row is a `FactorTaskRow` mini-widget showing task name (left), method/grid sublabel (middle, `TEXT_SECONDARY`), and status badge (right, colored).
- Status badge color: from new `TASK_STATUS_COLORS` token (complete→`SUCCESS`, pending→`TEXT_SECONDARY`, running→`PRIMARY`, failed→`ERROR_RED`). Label: from `TASK_STATUS_LABELS` (complete→已生成, pending→待生成, running→进行中, failed→失败).
- Footer summary label: `已制备 N / M 个单因素图` (count of status=="complete" vs total).
- `update_state(tasks: list[FactorMapTask])`: rebuild rows, set horizon from first task's `target_horizon` (or "—" if empty), set combobox to most common method, update footer.

### FactorPreviewGrid Widget — `factor_preview_grid.py`

Center grid showing completed factor map previews as cards.

- Style: QWidget with scroll, header label on top.
- Header label: `"{horizon} 单因素图集（{method}插值 · 网格 {grid} m）"`. `horizon`/`method` from first completed task; `grid` from `quality_metrics.grid` (default "50×50" if missing).
- `QGridLayout` (2 columns) of `FactorPreviewCard` mini-cards. Only tasks with status=="complete" are shown.
- Card content: factor name (title, `TEXT_PRIMARY` 13px bold), value range from `quality_metrics.range` (e.g. "12 — 86 m"), R² from `quality_metrics.r_squared` (e.g. "R² 0.91", `TEXT_SECONDARY` 11px). Placeholder "—" if metrics missing.
- Card style: bg `BG_SIDEBAR`, border 1px `BORDER`, border-radius `RADIUS_CARD`, padding 10px, min size ~160×100.
- `update_state(tasks: list[FactorMapTask])`: filter to completed, rebuild grid; empty state shows "暂无已生成的单因素图".

### BoundaryPanel Widget — `boundary_panel.py`

Right form panel for initial facies boundary generation config.

- Style: QFrame, bg `BG_SIDEBAR`, border 1px `BORDER`, border-radius `RADIUS_CARD`, padding 12px.
- Title label: `初始岩相边界制备` (`TEXT_PRIMARY` 13px bold).
- Form rows (each: label above + control):
  - 概率阈值: `QDoubleSpinBox` (range 0.0–1.0, step 0.05, default 0.55, single decimal).
  - 边界平滑强度: `QComboBox` with options 弱/中/强 (default 中).
  - 最小图斑面积 (km²): `QDoubleSpinBox` (range 0.0–10.0, step 0.1, default 0.5, one decimal).
  - 参与制备的相带: read-only `QLabel` (placeholder text "三角洲前缘砂体 · 分流间湾泥" since no facies data this phase).
- `生成初始边界并送入编图` primary button (object name `PrimaryButton`, non-functional).
- Form state is local widget state (not persisted to project) this phase.

### PreparationPage Assembly — `preparation_page.py`

```python
class PreparationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PreparationPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        content = QHBoxLayout()
        content.setSpacing(16)
        self.task_panel = FactorTaskPanel()
        self.preview_grid = FactorPreviewGrid()
        self.boundary_panel = BoundaryPanel()
        content.addWidget(self.task_panel, 0)
        content.addWidget(self.preview_grid, 1)
        content.addWidget(self.boundary_panel, 0)
        layout.addLayout(content, 1)

    def update_state(self, tasks: list) -> None:
        self.task_panel.update_state(tasks)
        self.preview_grid.update_state(tasks)
```

### Integration with AppShell

- AppShell uses `PreparationPage` at page_stack index 6 instead of `PagePlaceholder`.
- `AppShell.update_preparation_page(tasks)` delegates to widget 6's `update_state`.
- `app.py` calls `update_preparation_page(project.factor_map_tasks)` after construction.

### Design Tokens (new)

Add to `tokens.py`:

```python
TASK_STATUS_COLORS = {
    "complete": SUCCESS,
    "pending": TEXT_SECONDARY,
    "running": PRIMARY,
    "failed": ERROR_RED,
}
TASK_STATUS_LABELS = {
    "complete": "已生成",
    "pending": "待生成",
    "running": "进行中",
    "failed": "失败",
}
INTERPOLATION_METHODS = ["克里金", "IDW", "样条"]
SMOOTHING_LEVELS = ["弱", "中", "强"]
```

## Testing

### Unit Tests (target ~17 new tests)

- `tests/test_tokens.py` (extend): `TASK_STATUS_COLORS`, `TASK_STATUS_LABELS`, `INTERPOLATION_METHODS`, `SMOOTHING_LEVELS` exist with expected mappings.
- `tests/test_factor_task_panel.py` (~6): header horizon label; method combobox populated; task rows built with name/method/status; status badge color mapping; footer count "6 / 8"; empty state shows "0 / 0".
- `tests/test_factor_preview_grid.py` (~5): header text format; grid filters to completed tasks only; card shows value range; card shows R²; empty state.
- `tests/test_boundary_panel.py` (~3): threshold spinbox default 0.55; smoothing combo has 3 options; generate button present.
- `tests/test_preparation_page.py` (~2): assembles 3 sub-widgets; update_state delegates.
- `tests/test_preparation_integration.py` (~1): AppShell page 6 is PreparationPage (not PagePlaceholder); page 6 receives factor_map_tasks.

### Regression

- All existing 95 tests must continue to pass.

## Acceptance Criteria

1. 制备页 shows factor task panel with all `project.factor_map_tasks` listed.
2. Task status badges show colored 已生成/待生成/进行中/失败 labels.
3. Footer shows `已制备 N / M 个单因素图`.
4. Preview grid shows cards only for completed tasks, with value range + R².
5. Boundary panel has threshold/smoothing/area form controls with prototype defaults.
6. AppShell page 6 is PreparationPage (not placeholder).
7. All 95 existing + ~17 new tests pass.
