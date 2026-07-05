# MappingPage Design

> **Date:** 2026-07-05
> **Scope:** Phase 7 of the Paleogeography Workbench UI page implementation.

## Goal

Replace the `编图` placeholder at AppShell index 7 with a real paleogeographic map page that embeds `geo-viz-engine`'s `PaleoMapCanvas` and renders project map documents.

## Design

This phase is an MVP integration, not the full cartographic editor. The page is display-first and uses the latest `PaleoMapDocument` passed from the project.

The page has three zones:

1. `MapDocumentPanel` on the left shows the active map name, linked target horizon, polygon count, well overlay count, and selected document list.
2. `MapCanvasPanel` in the center embeds `PaleoMapCanvas`. It calls `load_features(facies_polygons, period_name=linked_target_horizon, wells=well_overlays)` and relies on the engine canvas for facies polygons, region labels, well overlay, title, legend, north arrow, and scale bar.
3. `MapChromePanel` on the right summarizes map chrome options from `PaleoMapDocument.map_chrome`, displays default enabled chrome elements, and exposes non-functional `保存编图草稿` / `发送成图审核` buttons.

## Data Flow

`PaleoWorkbenchWindow` passes `project.paleomap_documents` into `AppShell.update_mapping_page()`. `AppShell` delegates to page index 7. `MappingPage.update_state(map_documents)` selects the last document as active and passes the full list or active document to child widgets.

Missing data renders conservative defaults:

- no active map: `未选择古地理图`
- target horizon: `未设置`
- polygon count: `0 个相带`
- well count: `0 口井`

## Out of Scope

This phase does not implement polygon editing tools, topology validation, cartographic layout export, undo/redo, or artifact recording. Those should be separate follow-up slices after the canvas is wired into the workbench shell.

## Tests

Add pytest-qt coverage for the three child widgets, page assembly/delegation, AppShell index 7 replacement, and `PaleoWorkbenchWindow` wiring from `ProjectDocument.paleomap_documents`. Use `QT_QPA_PLATFORM=offscreen` for PySide tests in headless verification.
