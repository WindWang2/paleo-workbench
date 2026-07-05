# WellLogPredictionPage Design

> **Date:** 2026-07-05
> **Scope:** Phase 8 of the Paleogeography Workbench UI page implementation.

## Goal

Replace the `测井预测` placeholder at AppShell index 2 with a real prediction page that embeds `geo-viz-engine`'s `WellLogCanvas` and renders the latest workbench `PredictionTask`.

## Design

This phase is an MVP integration. It does not parse LAS files or run prediction models from the UI. It visualizes already-recorded prediction task output in a deterministic well-log style view.

The page has three zones:

1. `PredictionTaskPanel` on the left shows the active prediction task name, adapter kind, status, mean probability, review-area count, and task list.
2. `WellLogCanvasPanel` in the center embeds `WellLogCanvas`. It converts `PredictionTask.result_summary["predicted_regions"]` into a synthetic `WellLogData` object containing a prediction-probability curve and facies intervals, then calls `build_qpainter_tracks()` and `canvas.set_tracks()`.
3. `PredictionEvidencePanel` on the right lists evidence contribution weights, mock/replaceable status, and non-functional `运行测井预测` / `发送制备` action buttons.

## Data Flow

`PaleoWorkbenchWindow` passes `project.prediction_tasks` into `AppShell.update_well_log_prediction_page()`. `AppShell` delegates to page index 2. `WellLogPredictionPage.update_state(prediction_tasks)` selects the latest prediction task as active and passes it to child widgets.

Missing data renders conservative defaults:

- active task: `未选择预测任务`
- status: `待开始`
- mean probability: `—`
- review areas: `0 个`

## Out of Scope

This phase does not implement LAS file parsing, prediction model execution, single-well/batch switches, editable picks, or persistence from UI controls. Those should be separate follow-up slices after the page is wired into the workbench shell.

## Tests

Add pytest-qt coverage for task summary, synthetic well-log data conversion, `WellLogCanvas` track loading, evidence display, page assembly/delegation, AppShell index 2 replacement, and `PaleoWorkbenchWindow` wiring from `ProjectDocument.prediction_tasks`.
