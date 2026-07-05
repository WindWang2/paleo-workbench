# SeismicPredictionPage Design

> **Date:** 2026-07-05
> **Scope:** Phase 9 of the Paleogeography Workbench UI page implementation.

## Goal

Replace the `地震预测` placeholder at AppShell index 3 with a real prediction page that embeds `geo-viz-engine`'s `SeismicView` and renders the latest workbench `PredictionTask`.

## Design

This phase is an MVP integration. It does not load SEGY files or run seismic models from the UI. It visualizes already-recorded prediction task output as a deterministic synthetic seismic volume.

The page has three zones:

1. `SeismicTaskPanel` on the left shows the active prediction task name, adapter kind, status, mean probability, review-area count, and task list.
2. `SeismicViewPanel` in the center embeds `SeismicView`. It converts the active `PredictionTask` into a small deterministic `numpy.float32` volume, then calls `SeismicView.load_demo(volume)`.
3. `SeismicControlPanel` on the right shows volume shape, display mode, mock/replaceable status, and non-functional `运行地震预测` / `发送编图` action buttons.

## Data Flow

`PaleoWorkbenchWindow` passes `project.prediction_tasks` into `AppShell.update_seismic_prediction_page()`. `AppShell` delegates to page index 3. `SeismicPredictionPage.update_state(prediction_tasks)` selects the latest prediction task as active and passes it to child widgets.

Missing data renders conservative defaults:

- active task: `未选择预测任务`
- status: `待开始`
- volume shape: `—`
- display mode: `vd`

## Out of Scope

This phase does not implement SEGY import, seismic attribute extraction, horizon picking, model execution, well-seismic tie, or persistence from UI controls. Those should be separate follow-up slices after the page is wired into the workbench shell.

## Tests

Add pytest-qt coverage for deterministic volume generation, task summary, `SeismicView` load path, control display, page assembly/delegation, AppShell index 3 replacement, and `PaleoWorkbenchWindow` wiring from `ProjectDocument.prediction_tasks`.
