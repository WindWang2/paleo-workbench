# SequenceFrameworkPage Design

> **Date:** 2026-07-05
> **Scope:** Phase 6 of the Paleogeography Workbench UI page implementation.

## Goal

Replace the Layer Sequence placeholder at AppShell index 4 with a real display/configuration page backed by `ProjectDocument.stratigraphy`.

## Design

The page follows the completed workbench page pattern: a light gray body, 16 px outer padding, card-style white panels, and display-first controls that do not mutate project state yet.

The page has three panels:

1. `SequenceTargetPanel` on the left shows the active target horizon, interpretation version, systems tract scheme selector, and applicable well/seismic counts.
2. `SequenceBoundaryTable` in the center lists sequence boundaries from `StratigraphicFramework.sequence_boundaries`. Empty projects show a clear `未配置层序界面` state.
3. `SequenceSchemeSummary` on the right shows the selected scheme, derived boundary count, default systems tract labels, and a primary `保存层序方案` action button.

## Data Flow

`PaleoWorkbenchWindow` passes `project.stratigraphy` into `AppShell.update_sequence_framework_page()`. `AppShell` delegates to page index 4. `SequenceFrameworkPage.update_state(stratigraphy)` passes the same model to its three child widgets.

The widgets accept either a `StratigraphicFramework` instance or a dict-like object in tests. Missing fields render conservative defaults:

- target horizon: `未设置`
- sequence scheme: `LST/TST/HST`
- interpretation version: `v1`
- sequence boundaries: empty list

## Out of Scope

This phase does not implement stratigraphic picking, calibration, persistence from UI controls, or geo-viz-engine rendering. Those belong to later prediction/visualization work.

## Tests

Add focused pytest-qt coverage for each child widget, page assembly/delegation, AppShell index 4 replacement, and `PaleoWorkbenchWindow` wiring from `ProjectDocument.stratigraphy`.
