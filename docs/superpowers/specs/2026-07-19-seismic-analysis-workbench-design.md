# Seismic Analysis Workbench Visual Redesign

## Goal

Restructure the existing desktop **地震预测** page into the dark, data-dense seismic-analysis workbench shown in the supplied reference, while preserving all current prediction, viewing, attribute-selection, Auto-Tie, and mapping behavior.

## Scope

- Visual and layout redesign only; no new seismic interpretation, prediction, or data-processing algorithms.
- Remove the standalone task-list dock from the main page.
- Preserve existing empty, loading, ready, and error behavior in the embedded `SeismicView`.
- Preserve task selection semantics by using the active prediction task; task identity and status become compact context instead of a selectable list.

## Information Architecture

### Top context toolbar

The page gains a compact top bar containing the active task name, target horizon, current seismic attribute, display mode, and the existing primary action to run a prediction. It provides context without taking workspace width from the seismic view.

### Left attribute dock

The former task-list dock is replaced with a fixed-width, hierarchical **地震属性** panel.  It groups the existing selectable labels into `振幅属性`, `频率属性`, `连续性属性`, and `结构属性`.  Selecting a leaf updates the existing `SeismicView` attribute selector through the current `attribute_changed` signal path.  The tree is a presentation and selection surface only: it does not calculate new attributes or mutate the model.

### Center visual workspace

The center remains the source of truth for volume rendering and loading state:

1. A single `SeismicView` instance continues to render the seismic data.
2. A header labels the active volume and target horizon.
3. A four-card attribute strip sits above the renderer as compact visual context.  Cards show existing attribute group labels and deterministic qualitative status; they do not create secondary seismic renders or query a new model.
4. Existing in-view profile, VD/wiggle, and Auto-Tie facilities remain reachable through the embedded engine.

### Right analysis-results dock

The control dock becomes **智能分析结果**. It presents existing result data: task status, target horizon, volume dimensions, output type, selected attribute, and display mode.  It includes the existing Auto-Tie toggle and send-to-mapping action.  The run-prediction action lives in the top toolbar to make it the page's primary operation.

## Component Boundaries

- `SeismicPredictionPage` owns layout composition and bridges page-level actions.
- A new/updated context toolbar owns the task-context display and run/send actions; it emits existing page signals rather than creating workflow logic.
- `SeismicAttributePanel` owns only category display and selected-label signals.
- `SeismicViewPanel` remains responsible for loading, empty states, readiness, and the embedded engine surface; its public bridge methods remain compatible.
- `SeismicControlPanel` becomes the analysis-results presentation and retains the display-mode, Auto-Tie, and send signals. It no longer owns the primary run button.

## Data Flow

`SeismicPredictionPage.update_state()` resolves the active task, then passes it to the context toolbar, attribute dock, view panel, and results dock. Attribute selection follows `SeismicAttributePanel.attribute_changed` → `SeismicPredictionPage._on_attribute()` → `SeismicViewPanel.set_attribute_label()`. Display mode and Auto-Tie continue to flow through the existing control-panel signals to `SeismicViewPanel`. Run prediction remains `run_requested` → `_on_run()`; sending to mapping remains `send_requested` → `send_to_mapping_requested`.

## Visual Rules

- Continue using shared values in `paleo_workbench.ui.tokens`; do not introduce a parallel color system.
- Maintain the application dark theme, compact professional density, rounded dock chrome, and existing accessibility/disabled styling.
- The center workspace must receive the largest horizontal stretch. Left and right docks remain stable, narrow inspection panels.
- Chinese labels follow the reference vocabulary where it does not misrepresent existing behavior: `地震属性`, `智能分析结果`, `当前地震体`, and `运行预测`.

## Failure and Empty States

- When no active task exists, the context and results surfaces show placeholders, the view continues to show `未选择预测任务`, and dependent controls stay disabled.
- When seismic data cannot be resolved, `SeismicViewPanel` continues to expose its existing, specific failure message.
- During asynchronous SEG-Y loading, the engine surface remains visible and interaction controls are disabled until the ready signal arrives.

## Verification

- Add widget tests for the new dock composition, attribute grouping, active-task context, and signals that bridge selection/actions to existing behavior.
- Update presentation tests to assert that the task-list dock is absent and the new attribute/results surfaces are present.
- Run the focused seismic test group and the full offscreen pytest suite.

## Explicit Non-goals

- No new AI analysis output, confidence scoring, horizon interpretation, or seismic attribute computation.
- No change to `geoviz` engine APIs, SEG-Y loading, or prediction workflow schemas.
- No task-history browser in this redesign.
