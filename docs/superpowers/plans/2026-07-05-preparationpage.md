# PreparationPage Implementation Plan

> **Date:** 2026-07-05
> **Spec:** `docs/superpowers/specs/2026-07-05-preparationpage-design.md`
> **Approach:** SDD (subagent-driven development) — fresh subagent per task, review after each, final whole-branch review.

## Baseline

- Current tests: 95 passing.
- Branch: `main`.
- Files: `paleo_workbench/ui/pages/`, `tests/`, `paleo_workbench/ui/tokens.py`, `paleo_workbench/ui/app_shell.py`, `paleo_workbench/app.py`.

## Tasks (TDD — each dispatched to a fresh subagent)

### Task 1: Tokens — `TASK_STATUS_*`, `INTERPOLATION_METHODS`, `SMOOTHING_LEVELS`

**Files:** `paleo_workbench/ui/tokens.py`, `tests/test_tokens.py`

**Changes:**
- Add to `tokens.py`:
  ```python
  TASK_STATUS_COLORS = {"complete": SUCCESS, "pending": TEXT_SECONDARY, "running": PRIMARY, "failed": ERROR_RED}
  TASK_STATUS_LABELS = {"complete": "已生成", "pending": "待生成", "running": "进行中", "failed": "失败"}
  INTERPOLATION_METHODS = ["克里金", "IDW", "样条"]
  SMOOTHING_LEVELS = ["弱", "中", "强"]
  ```
- Add tests in `tests/test_tokens.py`:
  - `test_task_status_colors`: 4 mappings, complete→SUCCESS, pending→TEXT_SECONDARY, running→PRIMARY, failed→ERROR_RED.
  - `test_task_status_labels`: 4 mappings, complete→"已生成", pending→"待生成", running→"进行中", failed→"失败".
  - `test_interpolation_methods`: `["克里金", "IDW", "样条"]`, len 3.
  - `test_smoothing_levels`: `["弱", "中", "强"]`, len 3.

**Verify:** `pytest tests/test_tokens.py -q` passes; full suite still 95.

**Commit:** `feat: add task status/interpolation/smoothing tokens for PreparationPage`

---

### Task 2: FactorTaskPanel — `factor_task_panel.py`

**Files:** `paleo_workbench/ui/pages/factor_task_panel.py`, `tests/test_factor_task_panel.py`

**Behavior:**
- `FactorTaskPanel(QFrame)`, objectName "FactorTaskPanel".
- Header: `self.horizon_label` (QLabel "层位: —"), `self.method_combo` (QComboBox with `INTERPOLATION_METHODS`).
- `self.generate_btn` (QPushButton "批量生成单因素图", objectName "PrimaryButton").
- `self.task_container` (QWidget inside QScrollArea) holding `FactorTaskRow` mini-widgets.
- `self.summary_label` (QLabel "已制备 0 / 0 个单因素图").
- `update_state(tasks)`: set horizon from `tasks[0].target_horizon` or "—"; set method combo to most common method (or index 0); rebuild rows; update summary `f"已制备 {complete} / {total} 个单因素图"`.

**FactorTaskRow** (nested or same file, QWidget):
- name_label (QLabel, task.name), sublabel (QLabel, `f"{task.method} · {task.parameters.get('grid', '50m')}"`, TEXT_SECONDARY), status_badge (QLabel, colored text from TASK_STATUS_LABELS/COLORS).
- Row style: bg BG_SIDEBAR, border-bottom 1px BORDER_LIGHT, padding 6px 4px.

**Tests (~6):**
1. `test_panel_object_name`: objectName == "FactorTaskPanel".
2. `test_panel_has_horizon_label`: horizon_label exists, default "层位: —".
3. `test_panel_method_combo`: method_combo has 3 INTERPOLATION_METHODS items.
4. `test_panel_update_populates_rows`: 3 tasks → 3 rows; row names match; status badge text correct.
5. `test_panel_summary_count`: 3 tasks (2 complete, 1 pending) → "已制备 2 / 3 个单因素图".
6. `test_panel_empty_state`: update_state([]) → "已制备 0 / 0 个单因素图", horizon "—".

Use fixture building `FactorMapTask(name=..., target_horizon="ZJ-2", factor_type="地层厚度", method="mock", status="complete"/"pending")`.

**Verify:** `pytest tests/test_factor_task_panel.py -q` passes; full suite green.

**Commit:** `feat: add FactorTaskPanel widget for factor map task list`

---

### Task 3: FactorPreviewGrid — `factor_preview_grid.py`

**Files:** `paleo_workbench/ui/pages/factor_preview_grid.py`, `tests/test_factor_preview_grid.py`

**Behavior:**
- `FactorPreviewGrid(QWidget)`, objectName "FactorPreviewGrid".
- `self.header_label` (QLabel, default "单因素图集").
- `self.grid_container` (QWidget inside QScrollArea) with `QGridLayout` (2 columns).
- `update_state(tasks)`: filter to status=="complete"; set header `f"{horizon} 单因素图集（{method}插值 · 网格 {grid} m）"`; rebuild grid with `FactorPreviewCard`s; empty state → header "单因素图集", grid shows single "暂无已生成的单因素图" label.

**FactorPreviewCard** (nested, QFrame):
- name_label (QLabel, task.factor_type or task.name, bold 13px).
- range_label (QLabel, `task.quality_metrics.get("range", "—")`).
- rsquared_label (QLabel, `f"R² {task.quality_metrics.get('r_squared', '—')}"` if present, else hide).
- Card style: bg BG_SIDEBAR, border 1px BORDER, radius RADIUS_CARD, padding 10px, min 160×100.

**Tests (~5):**
1. `test_grid_object_name`.
2. `test_grid_header_format`: 2 completed tasks same horizon/method → header contains "ZJ-2", "克里金", "网格".
3. `test_grid_filters_completed`: 3 tasks (2 complete, 1 pending) → 2 cards.
4. `test_grid_card_shows_range`: task with `quality_metrics={"range": "12 — 86 m", "r_squared": 0.91}` → card range_label "12 — 86 m".
5. `test_grid_empty_state`: update_state([]) → no cards, placeholder label present.

**Verify:** `pytest tests/test_factor_preview_grid.py -q` passes; full suite green.

**Commit:** `feat: add FactorPreviewGrid widget for completed factor map cards`

---

### Task 4: BoundaryPanel — `boundary_panel.py`

**Files:** `paleo_workbench/ui/pages/boundary_panel.py`, `tests/test_boundary_panel.py`

**Behavior:**
- `BoundaryPanel(QFrame)`, objectName "BoundaryPanel".
- Title label "初始岩相边界制备".
- `self.threshold_spin` (QDoubleSpinBox, 0.0–1.0, single step 0.05, default 0.55, decimals 2).
- `self.smoothing_combo` (QComboBox, SMOOTHING_LEVELS, default 中).
- `self.area_spin` (QDoubleSpinBox, 0.0–10.0, single step 0.1, default 0.5, decimals 1, suffix " km²").
- `self.facies_label` (QLabel placeholder "三角洲前缘砂体 · 分流间湾泥").
- `self.generate_btn` (QPushButton "生成初始边界并送入编图", objectName "PrimaryButton").
- Panel style: bg BG_SIDEBAR, border 1px BORDER, radius RADIUS_CARD, padding 12px, fixed width ~220px.

**Tests (~3):**
1. `test_boundary_object_name`.
2. `test_boundary_threshold_default`: threshold_spin.value() == 0.55 (approx).
3. `test_boundary_smoothing_options`: smoothing_combo items == ["弱", "中", "强"], current "中".
4. `test_boundary_generate_button_present`: generate_btn text contains "生成初始边界".

**Verify:** `pytest tests/test_boundary_panel.py -q` passes; full suite green.

**Commit:** `feat: add BoundaryPanel widget for facies boundary config`

---

### Task 5: PreparationPage assembly — `preparation_page.py`

**Files:** `paleo_workbench/ui/pages/preparation_page.py`, `tests/test_preparation_page.py`

**Behavior:**
- `PreparationPage(QWidget)`, objectName "PreparationPage".
- Assembles `FactorTaskPanel` (stretch 0, ~260px), `FactorPreviewGrid` (stretch 1), `BoundaryPanel` (stretch 0, ~220px) in QHBoxLayout inside QVBoxLayout (16px margins/spacing).
- `update_state(tasks)`: delegates to `task_panel.update_state(tasks)` and `preview_grid.update_state(tasks)`.

**Tests (~2):**
1. `test_preparation_page_assembles_three_panels`: has `task_panel`, `preview_grid`, `boundary_panel` attributes of correct types; objectName "PreparationPage".
2. `test_preparation_page_update_delegates`: monkeypatch or spy on sub-widget `update_state` — verify both called with task list.

**Verify:** `pytest tests/test_preparation_page.py -q` passes; full suite green.

**Commit:** `feat: assemble PreparationPage from factor task/preview/boundary panels`

---

### Task 6: Integration — AppShell idx 6, exports, app.py wiring

**Files:** `paleo_workbench/ui/app_shell.py`, `paleo_workbench/ui/pages/__init__.py`, `paleo_workbench/app.py`, `tests/test_preparation_integration.py`

**Changes:**
- `pages/__init__.py`: export `PreparationPage`.
- `app_shell.py`:
  - Import `PreparationPage`.
  - Replace the placeholder loop with explicit page construction so PreparationPage lands at index 6:
    ```python
    self.page_stack.addWidget(HomePage())        # 0
    self.page_stack.addWidget(DataPage())        # 1
    for name in tokens.PAGE_NAMES[2:6]:          # 2,3,4,5
        self.page_stack.addWidget(PagePlaceholder(name))
    self.page_stack.addWidget(PreparationPage()) # 6
    for name in tokens.PAGE_NAMES[7:]:           # 7,8
        self.page_stack.addWidget(PagePlaceholder(name))
    ```
  - Add `update_preparation_page(self, tasks)` delegating to widget 6's `update_state`.
- `app.py`: after `update_data_page`, add `self.app_shell.update_preparation_page(self.project.factor_map_tasks)`.

**Tests (~2):**
1. `test_app_shell_page_six_is_preparation_page`: `page_stack.widget(6)` is `PreparationPage`.
2. `test_preparation_page_has_factor_tasks`: build project with 2 factor map tasks via `create_mock_factor_map`, pass through `PaleoWorkbenchWindow`, verify page 6 `task_panel` summary shows "2 / 2".

**Verify:** `pytest -q` full suite (~112 tests) green.

**Commit:** `feat: wire PreparationPage into AppShell at page index 6`

---

### Task 7: Final review + ledger update

**Actions:**
- Whole-branch review: read all new files, verify spec conformance, check for unused imports / dead code, verify token usage consistency.
- Run full test suite, confirm count.
- Update `task_plan.md`: Phase 4 → ✅ COMPLETE, page matrix row 7, test history row.
- Update `progress.md`: add Phase 4 section with task/commit/test table.
- Update `findings.md`: append any new technical decisions / errors.

**Commit:** `chore: sync SDD progress ledger (PreparationPage complete)`

## Risk / Notes

- `FactorMapTask.method` is "mock" in `create_mock_factor_map` — the method combobox/preview header will show "mock", not the prototype's "克里金". This is acceptable for the Low-complexity phase (data comes from the real model, not hardcoded prototype strings). If desired, a later task can map "mock"→"克里金" display.
- `quality_metrics` is `{}` for mock tasks — preview cards will show "—" placeholders, which the empty-state test path covers.
- Fixed widths (~260px / ~220px) are approximations; exact tuning can happen in a polish pass if needed.
