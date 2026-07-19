# Seismic Analysis Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the 地震预测 page as a reference-inspired seismic-analysis workbench while preserving its current workflow and SeismicView behavior.

**Architecture:** `SeismicPredictionPage` will compose a new context toolbar, a new attribute-tree dock, the existing `SeismicViewPanel`, and the existing control dock redesigned as analysis results. The page remains the signal bridge and active-task resolver; all seismic data loading and prediction logic stays in its current modules.

**Tech Stack:** Python 3, PySide6, pytest, pytest-qt, existing `geoviz.SeismicView`.

## Global Constraints

- Visual/layout only: do not add seismic analysis algorithms, data schemas, or geoviz engine APIs.
- Keep `SeismicViewPanel` as the owner of loading, ready, empty, and error states.
- Use `paleo_workbench.ui.tokens` shared colors, spacing, and button roles; do not introduce local full-widget stylesheets.
- Preserve active-task fallback, attribute selection, display mode, Auto-Tie, prediction, and send-to-mapping behavior.
- Remove `SeismicTaskPanel` from the page composition; do not delete it in this change because it is an existing public widget with independent tests.

---

## File Structure

- Create: `paleo_workbench/ui/pages/seismic_attribute_panel.py` — attribute-group tree and a selected-label signal.
- Create: `paleo_workbench/ui/pages/seismic_context_toolbar.py` — active-task context and primary actions.
- Modify: `paleo_workbench/ui/pages/seismic_prediction_page.py` — compose the new four-region workbench and bridge new signals.
- Modify: `paleo_workbench/ui/pages/seismic_control_panel.py` — present as intelligent analysis results and retain only secondary view actions.
- Modify: `paleo_workbench/ui/tokens.py` — add narrowly-scoped selectors for new dock and card roles if existing shared roles cannot express them.
- Create: `tests/test_seismic_attribute_panel.py` — focused attribute-tree tests.
- Create: `tests/test_seismic_context_toolbar.py` — focused context/action tests.
- Modify: `tests/test_seismic_prediction_page.py` — page-composition and state-routing tests.
- Modify: `tests/test_seismic_control_panel.py` — results-dock expectations.
- Modify: `tests/test_seismic_workflow.py` — primary run-action routing assertions.
- Modify: `tests/test_work_page_presentation.py` — new dock-chrome contracts.

## Task 1: Add the grouped attribute dock

**Files:**
- Create: `paleo_workbench/ui/pages/seismic_attribute_panel.py`
- Create: `tests/test_seismic_attribute_panel.py`

**Interfaces:**
- Consumes: `SEISMIC_ATTRIBUTE_LABELS: tuple[str, ...]` from `paleo_workbench.workflow.seismic_prediction`.
- Produces: `SeismicAttributePanel(QFrame)` with `attribute_changed = Signal(str)`, `attribute_tree: QTreeWidget`, `set_selected_attribute(label: str) -> None`, and `selected_attribute() -> str`.
- Produces: exactly four category labels: `振幅属性`, `频率属性`, `连续性属性`, `结构属性`.

- [ ] **Step 1: Write the failing attribute grouping test**

```python
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel


def test_attribute_panel_groups_all_supported_labels(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "SeismicAttributePanel"
    assert [panel.attribute_tree.topLevelItem(i).text(0) for i in range(4)] == [
        "振幅属性", "频率属性", "连续性属性", "结构属性",
    ]
    leaves = [
        panel.attribute_tree.topLevelItem(i).child(j).text(0)
        for i in range(panel.attribute_tree.topLevelItemCount())
        for j in range(panel.attribute_tree.topLevelItem(i).childCount())
    ]
    assert set(leaves) == {"振幅", "包络", "瞬时相位", "瞬时频率", "RMS振幅", "甜点"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_attribute_panel.py::test_attribute_panel_groups_all_supported_labels -q`

Expected: FAIL during collection because `seismic_attribute_panel` does not exist.

- [ ] **Step 3: Write the minimal attribute-dock implementation**

```python
class SeismicAttributePanel(QFrame):
    attribute_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicAttributePanel")
        self.attribute_tree = QTreeWidget()
        self.attribute_tree.setHeaderHidden(True)
        self._populate_tree()
        self.attribute_tree.itemClicked.connect(self._on_item_clicked)

    def _on_item_clicked(self, item, _column: int) -> None:
        if item.childCount() == 0:
            self.attribute_changed.emit(item.text(0))
```

Populate the categories with the six current labels, assign `MapDockTitle` to the title label, and use `WorkListWidget` on the tree so it inherits existing chrome.

- [ ] **Step 4: Run the grouping test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_attribute_panel.py::test_attribute_panel_groups_all_supported_labels -q`

Expected: PASS.

- [ ] **Step 5: Write the failing selection-signal test**

```python
def test_attribute_panel_emits_leaf_selection_and_syncs_programmatically(qtbot):
    panel = SeismicAttributePanel()
    qtbot.addWidget(panel)
    selected: list[str] = []
    panel.attribute_changed.connect(selected.append)

    panel.set_selected_attribute("包络")
    assert panel.selected_attribute() == "包络"

    item = panel.attribute_tree.topLevelItem(0).child(0)
    panel.attribute_tree.itemClicked.emit(item, 0)
    assert selected == ["振幅"]
```

- [ ] **Step 6: Run the selection test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_attribute_panel.py::test_attribute_panel_emits_leaf_selection_and_syncs_programmatically -q`

Expected: FAIL because synchronization methods are missing.

- [ ] **Step 7: Implement selection synchronization and verify all attribute-panel tests**

Implement `set_selected_attribute()` to locate and select a leaf without emitting a new selection signal, and `selected_attribute()` to return the current leaf text or `"振幅"` when no leaf is selected.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_attribute_panel.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the attribute dock**

```bash
git add paleo_workbench/ui/pages/seismic_attribute_panel.py tests/test_seismic_attribute_panel.py
git commit -m "feat: add grouped seismic attribute dock"
```

## Task 2: Add the top context toolbar

**Files:**
- Create: `paleo_workbench/ui/pages/seismic_context_toolbar.py`
- Create: `tests/test_seismic_context_toolbar.py`

**Interfaces:**
- Consumes: task fields through `field_value(task, field, default)`.
- Produces: `SeismicContextToolbar(QFrame)` with a `run_requested` signal, `set_context(task, horizon: str, attribute: str, display_mode: str) -> None`, and `run_btn`.
- Emits: `run_requested` when `run_btn` is clicked.

- [ ] **Step 1: Write the failing context/action test**

```python
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar


def test_context_toolbar_displays_active_context_and_emits_run(qtbot):
    task = MockPredictionAdapter().run(ProjectDocument.new("Test"), [], seed=3)
    toolbar = SeismicContextToolbar()
    qtbot.addWidget(toolbar)
    runs: list[bool] = []
    toolbar.run_requested.connect(lambda: runs.append(True))

    toolbar.set_context(task, "C6", "包络", "wiggle")
    toolbar.run_btn.click()

    assert toolbar.task_value.text() == task.name
    assert toolbar.horizon_value.text() == "C6"
    assert toolbar.attribute_value.text() == "包络"
    assert toolbar.mode_value.text() == "wiggle"
    assert runs == [True]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_context_toolbar.py::test_context_toolbar_displays_active_context_and_emits_run -q`

Expected: FAIL during collection because `seismic_context_toolbar` does not exist.

- [ ] **Step 3: Write the minimal toolbar implementation**

```python
class SeismicContextToolbar(QFrame):
    run_requested = Signal()

    def set_context(self, task, horizon: str, attribute: str, display_mode: str) -> None:
        self.task_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.horizon_value.setText(horizon or "—")
        self.attribute_value.setText(attribute or "振幅")
        self.mode_value.setText(display_mode or "vd")
```

Build it with compact labels using `WorkFieldLabel`/`WorkFieldValue` and `运行预测` as `PrimaryButton`.

- [ ] **Step 4: Run the context/action test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_context_toolbar.py::test_context_toolbar_displays_active_context_and_emits_run -q`

Expected: PASS.

- [ ] **Step 5: Commit the context toolbar**

```bash
git add paleo_workbench/ui/pages/seismic_context_toolbar.py tests/test_seismic_context_toolbar.py
git commit -m "feat: add seismic analysis context toolbar"
```

## Task 3: Assemble the workbench and reshape the results dock

**Files:**
- Modify: `paleo_workbench/ui/pages/seismic_prediction_page.py`
- Modify: `paleo_workbench/ui/pages/seismic_control_panel.py`
- Modify: `paleo_workbench/ui/tokens.py`
- Modify: `tests/test_seismic_prediction_page.py`
- Modify: `tests/test_seismic_control_panel.py`
- Modify: `tests/test_seismic_workflow.py`
- Modify: `tests/test_work_page_presentation.py`

**Interfaces:**
- Consumes: `SeismicAttributePanel.attribute_changed`, `SeismicContextToolbar.run_requested`, `SeismicControlPanel.send_requested`, `SeismicControlPanel.display_mode_changed`, and `SeismicControlPanel.well_tie_toggled`.
- Produces: `SeismicPredictionPage.attribute_panel`, `SeismicPredictionPage.context_toolbar`, `SeismicPredictionPage.view_panel`, and `SeismicPredictionPage.control_panel`.
- Preserves: `SeismicPredictionPage.prediction_updated`, `send_to_mapping_requested`, `_on_run()`, and `SeismicViewPanel` public bridge methods.

- [ ] **Step 1: Replace the obsolete page-composition test with a failing workbench test**

```python
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar


def test_seismic_prediction_page_assembles_analysis_workbench(qtbot):
    page = SeismicPredictionPage()
    qtbot.addWidget(page)

    assert isinstance(page.context_toolbar, SeismicContextToolbar)
    assert isinstance(page.attribute_panel, SeismicAttributePanel)
    assert isinstance(page.view_panel, SeismicViewPanel)
    assert isinstance(page.control_panel, SeismicControlPanel)
    assert not hasattr(page, "task_panel")
```

- [ ] **Step 2: Run the workbench test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_prediction_page.py::test_seismic_prediction_page_assembles_analysis_workbench -q`

Expected: FAIL because the page still creates `task_panel` and has no new workbench surfaces.

- [ ] **Step 3: Implement the new composition and signal routing**

In `SeismicPredictionPage`, add the context toolbar above a horizontal layout with a fixed-width attribute dock, expandable view panel, and fixed-width analysis-results dock. Replace `task_panel` connections with:

```python
self.context_toolbar.run_requested.connect(self._on_run)
self.attribute_panel.attribute_changed.connect(self._on_attribute)
self.control_panel.send_requested.connect(self.send_to_mapping_requested.emit)
self.control_panel.display_mode_changed.connect(self.view_panel.set_display_mode)
self.control_panel.well_tie_toggled.connect(self.view_panel.set_well_tie_enabled)
```

During `update_state()`, continue deriving `task = self._current_task()`, update the view and control panels, then synchronize the toolbar and attribute dock from the live view's selected attribute and display mode. Remove selectable-task state and `_on_task_selected()`.

In `SeismicControlPanel`, rename the title to `智能分析结果`, add a task-status value, preserve the dimension/horizon/output/attribute/display-mode fields, and remove `run_btn`. Keep Auto-Tie and `send_btn`; the toolbar owns the run action and the results dock owns the send action. Preserve the existing `send_requested` signal. Update `tokens.QSS_TEMPLATE` with `SeismicAttributePanel` and `SeismicContextToolbar` dock selectors plus only the minimal tree/card rules needed for readable hierarchy.

- [ ] **Step 4: Run the page-composition test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_prediction_page.py::test_seismic_prediction_page_assembles_analysis_workbench -q`

Expected: PASS.

- [ ] **Step 5: Write the failing integration-routing test**

```python
def test_seismic_page_routes_attribute_and_toolbar_actions(qtbot):
    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    with qtbot.waitSignal(page.prediction_updated, timeout=1000):
        page.context_toolbar.run_btn.click()

    page.attribute_panel.set_selected_attribute("包络")
    item = page.attribute_panel.attribute_tree.topLevelItem(0).child(1)
    page.attribute_panel.attribute_tree.itemClicked.emit(item, 0)
    assert page.view_panel.attribute_label() == "包络"
```

- [ ] **Step 6: Run the routing test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_prediction_page.py::test_seismic_page_routes_attribute_and_toolbar_actions -q`

Expected: FAIL until the new action and attribute signals are connected to the existing workflow bridges.

- [ ] **Step 7: Finish state synchronization and update affected contracts**

Update existing seismic tests to click `page.context_toolbar.run_btn`, use the analysis-results dock's send action, and assert results-dock fields. Update presentation contracts to construct `SeismicAttributePanel` and `SeismicContextToolbar`, assert their dock titles, and stop expecting `SeismicTaskPanel` inside `SeismicPredictionPage`.

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_prediction_page.py tests/test_seismic_control_panel.py tests/test_seismic_workflow.py tests/test_work_page_presentation.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the assembled workbench**

```bash
git add paleo_workbench/ui/pages/seismic_prediction_page.py paleo_workbench/ui/pages/seismic_control_panel.py paleo_workbench/ui/tokens.py tests/test_seismic_prediction_page.py tests/test_seismic_control_panel.py tests/test_seismic_workflow.py tests/test_work_page_presentation.py
git commit -m "feat: redesign seismic analysis workbench"
```

## Task 4: Verify visual and regression behavior

**Files:**
- Modify only if verification exposes a task-scoped defect: files listed in Tasks 1–3.

**Interfaces:**
- Consumes: completed widget composition and existing offscreen Qt test setup.
- Produces: a verified workbench with all existing seismic data-load behavior intact.

- [ ] **Step 1: Run the focused seismic suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_seismic_attribute_panel.py tests/test_seismic_context_toolbar.py tests/test_seismic_prediction_page.py tests/test_seismic_control_panel.py tests/test_seismic_view_panel.py tests/test_seismic_workflow.py tests/test_seismic_async_contract.py -q`

Expected: PASS with no failures.

- [ ] **Step 2: Run presentation and empty-state checks**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_work_page_presentation.py tests/test_empty_states.py -q`

Expected: PASS with no failures.

- [ ] **Step 3: Run the full regression suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`

Expected: PASS. If a pre-existing failure appears, report its exact test and do not fold unrelated repairs into this change.

- [ ] **Step 4: Visually inspect the page in the desktop app**

Run: `QT_QPA_PLATFORM=offscreen python -m paleo_workbench.main`

Expected: the application opens without import or layout errors. In an interactive desktop session, navigate to `地震预测` and confirm the top context toolbar, four-group attribute dock, dominant center view, and right-side `智能分析结果` dock are visible.

- [ ] **Step 5: Commit any task-scoped verification repair**

```bash
git add paleo_workbench/ui/pages tests/test_seismic_attribute_panel.py tests/test_seismic_context_toolbar.py tests/test_seismic_prediction_page.py tests/test_seismic_control_panel.py tests/test_seismic_workflow.py tests/test_work_page_presentation.py
git commit -m "fix: polish seismic analysis workbench"
```

Only create this commit when a verification-specific fix was required.
