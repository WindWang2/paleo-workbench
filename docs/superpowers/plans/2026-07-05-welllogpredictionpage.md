# WellLogPredictionPage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `测井预测` page at AppShell index 2 with `WellLogCanvas` backed by `ProjectDocument.prediction_tasks`.

**Architecture:** Add helper conversion from `PredictionTask` to synthetic `WellLogData`, three focused child widgets under `paleo_workbench/ui/pages/`, assemble them in `WellLogPredictionPage`, then wire the page through `AppShell` and `PaleoWorkbenchWindow`. The center widget embeds `geoviz_well_log.WellLogCanvas` and keeps track rendering in geo-viz-engine.

**Tech Stack:** Python 3.12, PySide6, pytest, pytest-qt, local `geo-viz-engine` package on the existing pytest pythonpath.

## Global Constraints

- Do not add runtime dependencies.
- Keep widgets display-first; do not mutate `ProjectDocument`.
- Use the latest `PredictionTask` as the active prediction task.
- Preserve AppShell page order from `tokens.PAGE_NAMES`; `测井预测` stays index 2.
- Use `WellLogCanvas.set_tracks(build_qpainter_tracks(well_log_data))` rather than reimplementing well-log rendering.
- Use TDD: write failing tests before production code.

---

### Task 1: Prediction Helpers

**Files:**
- Create: `paleo_workbench/ui/pages/prediction_helpers.py`
- Test: `tests/test_prediction_helpers.py`

**Interfaces:**
- Produces: `active_prediction_task(prediction_tasks)`, `well_log_data_from_prediction(task)`

- [ ] Add failing tests for latest-task selection and conversion from predicted regions to `WellLogData`.
- [ ] Run `pytest tests/test_prediction_helpers.py -q` and confirm failure.
- [ ] Implement helper functions with conservative defaults.
- [ ] Re-run helper tests.

### Task 2: Well Log Prediction Child Widgets

**Files:**
- Create: `paleo_workbench/ui/pages/prediction_task_panel.py`
- Create: `paleo_workbench/ui/pages/well_log_canvas_panel.py`
- Create: `paleo_workbench/ui/pages/prediction_evidence_panel.py`
- Test: `tests/test_prediction_task_panel.py`
- Test: `tests/test_well_log_canvas_panel.py`
- Test: `tests/test_prediction_evidence_panel.py`

**Interfaces:**
- Produces: `PredictionTaskPanel.update_state(prediction_tasks)`, `WellLogCanvasPanel.update_state(task)`, `PredictionEvidencePanel.update_state(task)`

- [ ] Add failing tests for task summary, canvas track loading, and evidence display.
- [ ] Run the three new test files and confirm import failures.
- [ ] Implement the three child widgets with existing card styling.
- [ ] Re-run the three new test files.

### Task 3: WellLogPredictionPage Assembly

**Files:**
- Create: `paleo_workbench/ui/pages/well_log_prediction_page.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_well_log_prediction_page.py`

**Interfaces:**
- Produces: `WellLogPredictionPage.update_state(prediction_tasks)`

- [ ] Add failing tests asserting object name, child widget types, and update delegation.
- [ ] Run `pytest tests/test_well_log_prediction_page.py -q` and confirm failure.
- [ ] Implement `WellLogPredictionPage`.
- [ ] Export `WellLogPredictionPage` from the pages package.
- [ ] Re-run `pytest tests/test_well_log_prediction_page.py -q`.

### Task 4: App Integration

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_well_log_prediction_integration.py`

**Interfaces:**
- Consumes: `WellLogPredictionPage.update_state(prediction_tasks)`
- Produces: `AppShell.update_well_log_prediction_page(prediction_tasks)`

- [ ] Add failing tests asserting AppShell index 2 is `WellLogPredictionPage` and `PaleoWorkbenchWindow` renders project prediction task values.
- [ ] Run `pytest tests/test_well_log_prediction_integration.py -q` and confirm failure.
- [ ] Wire `WellLogPredictionPage` into AppShell index 2.
- [ ] Add `AppShell.update_well_log_prediction_page()`.
- [ ] Call it from `PaleoWorkbenchWindow`.
- [ ] Re-run integration tests.

### Task 5: Verification and Ledger

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [ ] Run focused WellLogPrediction tests with `QT_QPA_PLATFORM=offscreen`.
- [ ] Run full `QT_QPA_PLATFORM=offscreen pytest -q`.
- [ ] Update progress from 6/9 to 7/9 pages complete and record the final test count.
