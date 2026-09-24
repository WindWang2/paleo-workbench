# 09 — Compatibility & Retirement Plan

## Retired in this PR (Wave A scope)

| Component | LOC | Fate |
|-----------|----:|------|
| `viz_charts::qt::PlotWidget` (`plot_widget.{hpp,cpp}`) | ~960 | **deleted** after `XyScatterHost` migration + test port; its public API had no production consumers outside the host (verified by grep) |
| `viz_charts::qt::CrossPlotWidget` (`cross_plot_widget.{hpp,cpp}`) | ~481 | **deleted** after `PwbCrossPlotCanvas` lands; no product consumer (tests only) |
| `WellLogPreviewPage::paintEvent` renderer | ~140 of 207 | replaced by `PwbPlotCanvas` multi-track composition; page contract (`set_data`/`summary_line`) kept |
| `TimeDepthPreviewPage::paintEvent` renderer | ~110 of 164 | replaced by `PwbPlotCanvas`; `set_probe` contract kept (probe = second overlay series) |
| `CompareCanvas::paintEvent` renderer | ~200 | replaced by `PwbBandColumnPlot` on `PwbPlotCanvas` (Wave A stretch — tracked in PR if deferred to Wave B) |

**Net**: ~1.6–1.9k LOC of hand-rolled generic plot machinery retired; replaced
by `libs/qgis_plot` (~1.3k LOC, but infrastructure — not per-page
duplication — and the delta is coverage of *more* surface types).

## Kept deliberately (with reasons)

| Component | Why |
|-----------|-----|
| `viz_charts` Qt-free kernels (`axes`, `series`/LTTB, `colormaps`, `convex_hull`, `marching_squares`, `fence`, `well_qc`) | domain math; consumed *by* the new adapters |
| `viz_charts::qt::SurfaceWidget` + `ColorbarWidget` (+`SurfaceHost`) | contour rendering has no `QgsPlot` primitive; Wave B adds `PwbContourPlotItem` then retires |
| `viz::WellLogHostWidget` (well-log-engine OpenGL) | specialized retained-scene engine; `QgsPlot` offers it nothing — see Phase-9 rationale below |
| `SectionCanvas`/`WellTieCanvas`/`FormationTopsPreview` | multi-well correlation composites; Wave C evaluation — NOT silently kept, explicitly scheduled |
| `SeismicSliceWidget`, `VizCTimeSliceMap`, `SectionProfileWidget` | raster/VD seismic domain viewers; not XY charts |
| `WellMapCanvas` QPainter fallback | its `WellMapQgisSurface` twin is Prompt-2 (map) scope — flagged in conflict matrix, not touched here |

## Phase 9 — submodule boundary verdicts (audited)

- **well-log-engine**: domain OpenGL SDK (depth-domain tracks, LOD, LAS/LIS/DLIS IO, PDF/CGM export); ~0 LOC of generic-plot code; opt-in `PWB_SCIENCE_BUILD_VIEWER=OFF` in default builds. **Keep as specialized adapter** (`Pwb::VisualizationWellLog`); the `SelectionEventV1` translation in `WellLogHostWidget` is the existing seam for map↔plot linkage. Migration would mean writing a new engine — out of scope, documented.
- **geo-viz-engine**: oracle/frozen-behavior source only (never CMake-linked). Its generic 2-D subset (~3k LOC Python) is already C++-ported as `libs/viz_charts` — that port is exactly what this convergence retires/absorbs. Domain packages stay oracle-only.

## Facade policy

No compatibility facade over deleted widgets — consumers are migrated in the
same commit (API surface was tiny and internal). `XyScatterHost::plot()`
returns the new `PwbPlotCanvas*` (renamed `canvas()`); the only external
caller is `pa_flow_test`, updated in lockstep. No silent fallbacks anywhere.
