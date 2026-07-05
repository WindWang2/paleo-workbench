# SeismicPredictionPage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `地震预测` page at AppShell index 3 with `SeismicView` backed by `ProjectDocument.prediction_tasks`.

**Architecture:** Add helper conversion from `PredictionTask` to deterministic synthetic seismic volume, three focused child widgets under `paleo_workbench/ui/pages/`, assemble them in `SeismicPredictionPage`, then wire the page through `AppShell` and `PaleoWorkbenchWindow`. The center widget embeds `geoviz_seismic.SeismicView` and keeps seismic rendering in geo-viz-engine.

**Tech Stack:** Python 3.12, PySide6, numpy, pytest, pytest-qt, local `geo-viz-engine` package on the existing pytest pythonpath.

## Global Constraints

- Do not add runtime dependencies.
- Keep widgets display-first; do not mutate `ProjectDocument`.
- Use the latest `PredictionTask` as the active prediction task.
- Preserve AppShell page order from `tokens.PAGE_NAMES`; `地震预测` stays index 3.
- Use `SeismicView.load_demo(volume)` rather than reimplementing seismic rendering.
- Use TDD: write failing tests before production code.

---

### Task 1: Seismic Prediction Helpers

**Files:**
- Create: `paleo_workbench/ui/pages/seismic_prediction_helpers.py`
- Test: `tests/test_seismic_prediction_helpers.py`

**Interfaces:**
- Produces: `seismic_volume_from_prediction(task, shape=(8, 10, 12))`

- [ ] Add failing tests for deterministic volume shape, dtype, and repeatability.
- [ ] Run `pytest tests/test_seismic_prediction_helpers.py -q` and confirm failure.
- [ ] Implement helper function with conservative defaults.
- [ ] Re-run helper tests.

### Task 2: Seismic Prediction Child Widgets

**Files:**
- Create: `paleo_workbench/ui/pages/seismic_task_panel.py`
- Create: `paleo_workbench/ui/pages/seismic_view_panel.py`
- Create: `paleo_workbench/ui/pages/seismic_control_panel.py`
- Test: `tests/test_seismic_task_panel.py`
- Test: `tests/test_seismic_view_panel.py`
- Test: `tests/test_seismic_control_panel.py`

**Interfaces:**
- Produces: `SeismicTaskPanel.update_state(prediction_tasks)`, `SeismicViewPanel.update_state(task)`, `SeismicControlPanel.update_state(task, volume_shape=None)`

- [ ] Add failing tests for task summary, view demo loading, and control display.
- [ ] Run the three new test files and confirm import failures.
- [ ] Implement the three child widgets with existing card styling.
- [ ] Re-run the three new test files.

### Task 3: SeismicPredictionPage Assembly

**Files:**
- Create: `paleo_workbench/ui/pages/seismic_prediction_page.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_seismic_prediction_page.py`

**Interfaces:**
- Produces: `SeismicPredictionPage.update_state(prediction_tasks)`

- [ ] Add failing tests asserting object name, child widget types, and update delegation.
- [ ] Run `pytest tests/test_seismic_prediction_page.py -q` and confirm failure.
- [ ] Implement `SeismicPredictionPage`.
- [ ] Export `SeismicPredictionPage` from the pages package.
- [ ] Re-run `pytest tests/test_seismic_prediction_page.py -q`.

### Task 4: App Integration

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_seismic_prediction_integration.py`

**Interfaces:**
- Consumes: `SeismicPredictionPage.update_state(prediction_tasks)`
- Produces: `AppShell.update_seismic_prediction_page(prediction_tasks)`

- [ ] Add failing tests asserting AppShell index 3 is `SeismicPredictionPage` and `PaleoWorkbenchWindow` renders project prediction task values.
- [ ] Run `pytest tests/test_seismic_prediction_integration.py -q` and confirm failure.
- [ ] Wire `SeismicPredictionPage` into AppShell index 3.
- [ ] Add `AppShell.update_seismic_prediction_page()`.
- [ ] Call it from `PaleoWorkbenchWindow`.
- [ ] Re-run integration tests.

### Task 5: Verification and Ledger

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [ ] Run focused SeismicPrediction tests with `QT_QPA_PLATFORM=offscreen`.
- [ ] Run full `QT_QPA_PLATFORM=offscreen pytest -q`.
- [ ] Update progress from 7/9 to 8/9 pages complete and record the final test count.
