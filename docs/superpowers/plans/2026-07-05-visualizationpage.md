# VisualizationPage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `可视化` page at AppShell index 5 with composite well-log, seismic, and cross-well views.

**Architecture:** Add three focused child widgets under `paleo_workbench/ui/pages/`, assemble them in `VisualizationPage`, then wire the page through `AppShell` and `PaleoWorkbenchWindow`. The center panel embeds geo-viz widgets and reuses existing prediction conversion helpers.

**Tech Stack:** Python 3.12, PySide6, pytest, pytest-qt, local `geo-viz-engine` packages on the existing pytest pythonpath.

## Global Constraints

- Do not add runtime dependencies.
- Keep widgets display-first; do not mutate `ProjectDocument`.
- Preserve AppShell page order from `tokens.PAGE_NAMES`; `可视化` stays index 5.
- Use geo-viz widgets (`WellLogCanvas`, `SeismicView`, `CrossWellWidget`) rather than reimplementing rendering.
- Use TDD: write failing tests before production code.

---

### Task 1: Visualization Child Widgets

**Files:**
- Create: `paleo_workbench/ui/pages/visualization_summary_panel.py`
- Create: `paleo_workbench/ui/pages/composite_visualization_panel.py`
- Create: `paleo_workbench/ui/pages/visualization_trace_panel.py`
- Test: `tests/test_visualization_summary_panel.py`
- Test: `tests/test_composite_visualization_panel.py`
- Test: `tests/test_visualization_trace_panel.py`

**Interfaces:**
- Produces: `VisualizationSummaryPanel.update_state(resources, prediction_tasks, map_documents)`, `CompositeVisualizationPanel.update_state(prediction_tasks)`, `VisualizationTracePanel.update_state(prediction_tasks, map_documents)`

- [ ] Add failing tests for summary counts, composite tab loading, and trace display.
- [ ] Run the three new test files and confirm import failures.
- [ ] Implement the three child widgets with existing card styling.
- [ ] Re-run the three new test files.

### Task 2: VisualizationPage Assembly

**Files:**
- Create: `paleo_workbench/ui/pages/visualization_page.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_visualization_page.py`

**Interfaces:**
- Produces: `VisualizationPage.update_state(resources, prediction_tasks, map_documents)`

- [ ] Add failing tests asserting object name, child widget types, and update delegation.
- [ ] Run `pytest tests/test_visualization_page.py -q` and confirm failure.
- [ ] Implement `VisualizationPage`.
- [ ] Export `VisualizationPage` from the pages package.
- [ ] Re-run `pytest tests/test_visualization_page.py -q`.

### Task 3: App Integration

**Files:**
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_visualization_integration.py`

**Interfaces:**
- Consumes: `VisualizationPage.update_state(resources, prediction_tasks, map_documents)`
- Produces: `AppShell.update_visualization_page(resources, prediction_tasks, map_documents)`

- [ ] Add failing tests asserting AppShell index 5 is `VisualizationPage` and `PaleoWorkbenchWindow` renders project slices.
- [ ] Run `pytest tests/test_visualization_integration.py -q` and confirm failure.
- [ ] Wire `VisualizationPage` into AppShell index 5.
- [ ] Add `AppShell.update_visualization_page()`.
- [ ] Call it from `PaleoWorkbenchWindow`.
- [ ] Re-run integration tests.

### Task 4: Verification and Ledger

**Files:**
- Modify: `task_plan.md`
- Modify: `progress.md`

- [ ] Run focused Visualization tests with `QT_QPA_PLATFORM=offscreen`.
- [ ] Run full `QT_QPA_PLATFORM=offscreen pytest -q`.
- [ ] Update progress from 8/9 to 9/9 pages complete and record the final test count.
