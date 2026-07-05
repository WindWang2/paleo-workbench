# VisualizationPage Design

> **Date:** 2026-07-05
> **Scope:** Phase 10 of the Paleogeography Workbench UI page implementation.

## Goal

Replace the `可视化` placeholder at AppShell index 5 with a composite visualization page that brings together well-log, seismic, and cross-well views from `geo-viz-engine`.

## Design

This phase is an MVP integration. It reuses already-recorded project data and prediction output; it does not introduce new interpretation tools.

The page has three zones:

1. `VisualizationSummaryPanel` on the left shows counts for prediction tasks, map documents, and core resource types.
2. `CompositeVisualizationPanel` in the center contains a `QTabWidget` with three tabs:
   - `测井`: `WellLogCanvas` fed by the same deterministic `PredictionTask` → `WellLogData` conversion used by Phase 8.
   - `地震`: `SeismicView(auto_load=False)` fed by the same deterministic seismic volume conversion used by Phase 9.
   - `连井`: `CrossWellWidget` containing two lightweight `WellLogCanvas` instances built from the active prediction task.
3. `VisualizationTracePanel` on the right shows the active task, map document, and non-functional `刷新视图` / `导出组合视图` buttons.

## Data Flow

`PaleoWorkbenchWindow` passes `project.resources`, `project.prediction_tasks`, and `project.paleomap_documents` into `AppShell.update_visualization_page()`. `AppShell` delegates to page index 5. `VisualizationPage.update_state(resources, prediction_tasks, map_documents)` passes project slices to each child widget.

Missing data renders conservative defaults and empty widgets.

## Out of Scope

This phase does not implement linked cursor synchronization, saved composite layouts, cross-well picking, export artifacts, or data import. Those should be separate follow-up slices.

## Tests

Add pytest-qt coverage for summary counts, composite widget loading, trace display, page assembly/delegation, AppShell index 5 replacement, and `PaleoWorkbenchWindow` wiring.
