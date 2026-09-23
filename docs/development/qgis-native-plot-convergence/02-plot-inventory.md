# 02 — In-house Plot / Chart Inventory @ `192422c60`

Exhaustive sweep of `apps/` + `libs/` (read + grep audit; well-log/geo-viz
submodules assessed separately in 09). **Verified negatives**: zero `QtCharts`/
`QChart`, zero existing `QgsPlot*`/`QgsPlotCanvas` consumers, zero `QRubberBand`
uses, zero `QQuickItem`/QML, no `libs/statistics` module, `QGraphicsScene` only
for map editing (`ui_pages_mapedit`), never for charts.

**Every 2-D plot in the native product is a hand-rolled `QWidget`+`QPainter`
surface.**

## A. Generic plotting library — `libs/viz_charts` (the primary retirement target)

| Class | Files | ~LOC | Generic? | Behavior |
|-------|-------|-----:|----------|----------|
| `qt::PlotWidget` | `viz_charts/qt/{include/.../plot_widget.hpp, src/plot_widget.cpp}` | 960 | **yes** | line/scatter: Heckbert ticks, wheel zoom@cursor, drag pan, autofit+5%, equal-aspect, hover snap+crosshair, selected/highlighted points, LTTB>2000, SVG/PDF export. Signals `point_hovered/_cleared/point_clicked/reset_requested/view_changed` — **no production consumers of the interaction API** (tests only) |
| `qt::CrossPlotWidget` | `cross_plot_widget.{hpp,cpp}` | 481 | mostly | scatter + viridis z-color + colorbar + convex-hull cluster + `apply_lasso_polygon`→`points_selected`; image-stamping >4000 pts. No product consumer (tests only) |
| `qt::SurfaceWidget` | `surface_widget.{hpp,cpp}` | 764 | generic-ish | filled contours + isolines + labels (marching squares), hover bubble, pan/zoom, export. Contour rendering has **no QgsPlot equivalent** → custom canvas item (Wave B) |
| `qt::ColorbarWidget` | `colorbar_widget.{hpp,cpp}` | 137 | generic | vertical ramp strip; absorbed into host panels, not a canvas |

Qt-free kernels (KEEP — domain math, not plot infra): `axes` (Heckbert),
`series` (LTTB), `colormaps`, `convex_hull`/point-in-polygon, `marching_squares`,
`fence`, `well_qc`.

## B. Domain-specific painted canvases

| Class | File | ~LOC | Verdict |
|-------|------|-----:|---------|
| `viz::WellLogHostWidget` | `visualization/src/well_log/` | 1172 | engine host over `welllog::WellLogView` (OpenGL) — keep specialized (09) |
| `cross_well::SectionCanvas` | `visualization/src/cross_well/qt/section_canvas.cpp` | 876 | multi-well correlation section — no QGIS analog; Wave C evaluate |
| `cross_well::FormationTopsPreview` | `formation_tops_preview.cpp` | 221 | domain preview; Wave C |
| `well_tie::WellTieCanvas` | `well_tie/qt/tie_canvas.cpp` | 340 | 7-track composite — Wave C |
| `seismic_viewer::SeismicSliceWidget` | `seismic_slice_widget.cpp` | 2200 | VD/wiggle raster viewer — **not a plot**; keep specialized |
| `seismic_viewer::SectionProfileWidget` | `section_profile_widget.cpp` | 233 | raster fence profile + overlays; Wave C candidate |
| `app::VizCTimeSliceMap` | `apps/.../viz_c_time_map.cpp` | 246 | raster+markers time-slice — map semantics; Prompt 2 adjacent, keep |
| `app::CompareCanvas` | `apps/.../comparison_view.cpp` | ~600 (canvas ~200) | **QC/diagnostic depth-band chart** — Wave A stats/QC representative |
| `ui_wellseis::WellMapCanvas` | `well_map_canvas.cpp` | 311 | QPainter well scatter — superseded by `WellMapQgisSurface` (QgsMapCanvas twin already exists); retire QPainter fallback path under Prompt 2 coordination, **not** this stream |

## C. Hand-painted preview pages — `libs/ui_pages_preview`

| Class | File | ~LOC | Verdict |
|-------|------|-----:|---------|
| `WellLogPreviewPage` | `well_log_preview_presenter.cpp` | 207 | per-curve column mini-charts → N `QgsLineChartPlot` items on one canvas (Wave A) |
| `TimeDepthPreviewPage` | `time_depth_preview_presenter.cpp` | 164 | MD/TWT polyline + probe points → single XY plot (Wave A, cheapest) |
| `ImagePreviewWidget`, `SeismicSlicePreviewWidget`, `PdfPreviewWidget` | — | — | image/doc viewers, not charts |

## D. App-level thin hosts — `apps/paleo_workbench_platform`

| Class | File | ~LOC | Consumes |
|-------|------|-----:|----------|
| `viz_e::XyScatterHost` | `viz_e_hosts.{hpp,cpp}` | ~150 | `PlotWidget` — well-head XY scatter w/ labels + equal aspect + export. **Wave A** |
| `viz_e::SurfaceHost` | same | ~170 | `SurfaceWidget`+`ColorbarWidget` — Wave B (needs contour item) |
| `viz_e_install.cpp` | — | 609 | registers `xy_scatter_chart`/`surface_chart` preview targets |
| `well_presenter_install.cpp` | — | ~255 | registers `WellLogPreviewPage`/`TimeDepthPreviewPage` presenters |

## E. Verified non-plot painted surfaces (excluded)

`ui_canvas/*`, `ui_map/display_map_canvas`, `ui_widgets/qgis/*` (already
`QgsMapCanvas`), `ui_pages_mapedit/*` (edit scene), `module_map_widget`
(dependency diagram), `stratigraphic_timeline_slider` (control),
`geo3d_viz` (OpenGL 3D), `dual_volume_overlay` (QA image compare),
`composition_panel` (SVG document preview — layout stream),
`layout_compose_panel` (layout furniture), `ui_seqviz/*` (shells/panels;
`SectionCursorBand` is a linkage strip, not a chart).

## F. Migration ranking (G=genericness, L=retirable LOC, R=risk; 5=max)

| # | Candidate | G | L | R |
|---|-----------|--:|--:|--:|
| 1 | `PlotWidget` (via `XyScatterHost`) | 5 | 960 | 2 |
| 2 | `TimeDepthPreviewPage` | 5 | 164 | 1 |
| 3 | `WellLogPreviewPage` | 3 | 207 | 2 |
| 4 | `CrossPlotWidget` | 4 | 481 | 3 |
| 5 | `CompareCanvas` | 3 | ~200 | 2 |
| 6 | `SurfaceWidget` (+`SurfaceHost`) | 4 | 764 | 4 — needs contour `QgsPlotCanvasItem` |
| 7 | `SectionProfileWidget` | 3 | 233 | 3 |
| 8 | `FormationTopsPreview`, `WellTieCanvas`, `SectionCanvas` | 2 | ~1400 | 4 — Wave C domain composites |
