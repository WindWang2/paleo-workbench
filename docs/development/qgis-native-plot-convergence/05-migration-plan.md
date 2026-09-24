# 05 — Migration Plan

## Wave A (this PR)

| Step | Target | Mechanism | Retires |
|------|--------|-----------|---------|
| A1 | `libs/qgis_plot` infra | `PwbPlotCanvas`/`PwbPlotItem`/tools/`PwbPlotPanel`/bindings/export | — (new) |
| A2 | `XyScatterHost` (well-head scatter) | `PwbPlotPanel` + marker-only `QgsLineChartPlot` + per-point label overlay + equal-aspect lock + autofit+5% | `PlotWidget` consumer #1 |
| A3 | `TimeDepthPreviewPage` | single `PwbPlotItem`(`QgsLineChartPlot`) + probe overlay item | 164 LOC painter |
| A4 | `WellLogPreviewPage` | N column `PwbPlotItem`s (per-curve value range, X-shared bucket axis) + header/range text + `+N` overflow note | 207 LOC painter |
| A5 | `CrossPlotWidget` → `PwbCrossPlotCanvas`-backed impl | scatter + z-ramp fill + `PwbPlotToolLasso` → `points_selected`; public API kept | 481 LOC painter |
| A6 | `CompareCanvas` (validation QC bands) | `PwbBandColumnPlot` (`Qgs2DXyPlot::renderContent` draws depth bands) + linked cursor seam | ~200 LOC painter |
| A7 | Retire `plot_widget.cpp`/`cross_plot_widget.cpp` from `pwb_viz_charts_qt`; port their smoke tests to `libs/qgis_plot` tests | delete after A2/A5 | ~1440 LOC generic engine |

### Deferred inside Wave A (documented, not hidden)
- `SurfaceWidget`/`SurfaceHost` — needs contour `QgsPlotCanvasItem`; Wave B.
- `ColorbarWidget` — stays a thin strip widget; revisited when legend/ramp items land.
- `QgsPlotToolXAxisZoom` upstream is `QgsElevationProfileCanvas`-bound → `PwbPlotToolXAxisZoom` re-implements via `QgsPlotToolZoom::constrain*` overrides (C++-only API, ~60 LOC, no upstream code copied — constraint semantics only).

## Wave B (follow-up PRs)

- `SurfaceWidget` → contour item (`renderContent` draws marching-squares polylines; kernel reused from `viz_charts`)
- Histogram adapter + wire into a real QC surface (product currently shows QC as text — see 02)
- Legend item, per-series visibility toggles
- `SectionProfileWidget` raster+overlay evaluation

## Wave C

- `SectionCanvas`, `WellTieCanvas`, `FormationTopsPreview` — domain multi-track composites; likely `PwbPlotCanvas` + custom items, or documented keep-specialized after a written evaluation per Phase 9.
- `VizCTimeSliceMap` — coordinate with Prompt-2 (map-adjacent).

## Wave D — cleanup

- `pwb_viz_charts_qt` shrinks to nothing or to `ColorbarWidget` only; decide then.
- Remove deprecated facades; final gate: grep-based CI lint (see 06 §gates).

## Ordering inside this branch

`infra → TimeDepth (smallest real consumer) → XyScatter → WellLog → CrossPlot → Compare → retire → gates`. Each step builds independently.
