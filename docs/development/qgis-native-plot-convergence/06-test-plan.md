# 06 — Test Plan

Test home: `libs/qgis_plot/qgis_plot_tests/` (unit+interaction, Qt Widgets +
`PwbQgis::Sdk`) plus updates to existing consumers' tests. All runnable
offscreen (`QT_QPA_PLATFORM=offscreen`) per repo convention.

## Unit tests (new)

| Area | Assertions |
|------|-----------|
| `PwbPlotItem` | hosts each stock plot type (line/bar/pie); `plotArea` non-empty after resize; image cache invalidated on data/range change |
| coordinate map | `canvasPointToPlotPoint`∘`plotPointToCanvasPoint` round-trip; y-axis flip orientation |
| axis share | XShared items pan together, YFree items untouched |
| bindings | `pointAt(seriesIdx, pointIdx)` → binding + optional per-point domain id |
| snap | `snapToPlot` returns nearest point ≤ radius, empty outside |
| autofit | bounds = finite data extent ±5% pad; equal-aspect makes square-in-data view |
| export | svg/pdf/png write non-empty files; svg contains vector text (grep `<text`) |
| numeric format | `PwbDepthValueFormat` renders `|-depth|` labels |

## Interaction tests (new, QTest mouse/wheel)

| Scenario | Expected |
|----------|----------|
| `QgsPlotToolPan` drag | x/y ranges shift; `viewChanged` emitted |
| `QgsPlotToolZoom` marquee | `zoomToRect` → ranges shrink to dragged rect |
| wheel | `wheelZoom` scales about cursor |
| `zoomFull` | restores autofit bounds |
| identify click | `pointClicked(series_id, index, x, y)` on nearest point |
| identify drag-rect | `identifyFinished` covers hits inside rect |
| lasso | `lassoFinished(polygon)`; consumer-side PIP marks indices |
| crosshair ambient | `pointHovered` fires on move over point; clears on leave |

## Integration tests (updated consumers)

| Existing test | Change |
|---------------|--------|
| `tests/cpp/viz_e/pa_flow_test.cpp` | `xy_host()->plot()->view_bounds()` → `canvas()->viewBounds()`; `export_svg_to` unchanged at host level |
| `tests/cpp/well_crosswell/well_presenter_flow_test.cpp` | preview page contract unchanged (`set_data`/`summary_line`); add canvas non-null assertion |
| `viz_charts_tests/qt_widgets_smoke_test.cpp` | PlotWidget/CrossPlotWidget cases ported to `libs/qgis_plot` equivalents before widget deletion |
| `ui_pages_preview` tests | summary/degradation contract preserved |

## Scale / performance

- Scatter 50k pts: feed `QgsXyPlotSeries` — render time recorded; assert < threshold AND that LTTB downsampling (viz_charts kernel, Qt-free) is applied upstream of the series by the consumer where the old widget applied it (PlotWidget parity: threshold 2000 for labels only — points still drawn; measure before deciding on decimation).
- Multi-track: 8 tracks × 10k samples — single `update()` path, no per-sample item churn.
- Open/close page 20×, project switch — no UAF (ASAN where available; at minimum no crash under offscreen stress test).

## Architecture gates (scripted, `scripts/` or ctest)

- `grep -rn "paintEvent" libs apps --include=*.cpp` on migrated files → 0 hits in migrated classes.
- New-code gate: no `QPainter` in new files except inside `renderContent`/`paint(QPainter*)` overrides of `QgsPlotCanvasItem`/`Qgs2DPlot` derivatives (lint whitelist = the item/tool files themselves).
- No second `QGraphicsScene`/`QGraphicsView` subclass for plots outside `libs/qgis_plot` + existing map-edit/map canvases (list-pinned).
- `-j <= 6` enforced via `CMAKE_BUILD_PARALLEL_LEVEL=4` env on every build invocation.
