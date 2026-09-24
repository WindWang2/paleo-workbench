# 04 — Target Architecture

```
QgsPlotCanvas (QGIS framework base: scene + tool dispatch + transient tools)
└── PwbPlotCanvas  (libs/qgis_plot — THIS stream's single 2D-plot canvas)
      │  implements: panContentsBy / scalePlot / zoomToRect / centerPlotOn /
      │              wheelZoom / snapToPlot / refresh / zoomFull / export
      │  owns:       N × PwbPlotItem (scene items, fractional layout)
      │             PwbCrosshairItem (ambient hover overlay)
      │             PwbSeriesBinding table (series→domain ids)
      │  signals:    pointHovered / pointClicked / selectionFinished /
      │             lassoFinished / viewChanged / canvasPointHovered
      │
      ├── PwbPlotItem : QgsPlotCanvasItem
      │     owns Qgs2DPlot (LineChart/BarChart/PieChart/Pwb domain plot)
      │       + QgsPlotData + axis titles + scene-rect fraction
      │     paint() = image-cached QgsRenderContext render (upstream pattern)
      │
      ├── Tools (QgsPlotTool):  QgsPlotToolPan · QgsPlotToolZoom ·
      │     PwbPlotToolXAxisZoom (genericized constrain-subclass of Zoom) ·
      │     PwbPlotToolIdentify (click pick + rect identify) ·
      │     PwbPlotToolLasso (polygon rubber band → domain selection)
      │
      └── PwbPlotPanel : QWidget — page chrome
            title/provenance label + QToolBar(checkable tool actions,
            zoom-full, export) + PwbPlotCanvas + honest-unavailable label
```

## Design rules

1. **One canvas.** All interactive 2-D scientific surfaces derive from
   `PwbPlotCanvas`/`QgsPlotCanvas`. No second generic plot canvas.
2. **Plots are renderers, items are hosts.** `Qgs2DPlot`+`QgsPlotData` do the
   drawing; `PwbPlotItem` positions them in the scene and feeds data. Domain
   plots subclass `Qgs2DXyPlot` and override `renderContent` only.
3. **Domain semantics live in bindings, not rendering.** `PwbSeriesBinding`
   carries `series_id`/`well_id`/`curve_id`/`layer_id`/`version_id`/`run_id`/
   `track_id`/`unit`/`axis_role`/`style_role` + optional per-point ids.
   Any rendered point resolves back to a domain object via the binding table.
4. **Navigation = plot-range mutation.** Pan/zoom mutate each linked item's
   `set{X,Y}{Minimum,Maximum}`; per-item `axisLink` flags (`XShared`,`YShared`,
   `None`) decide which axes participate (multi-track depth linking).
5. **Thin adapters only where QGIS lacks the primitive** (see 03 gap table):
   axis titles, per-point labels, crosshair, lasso polygon, histogram
   (= interval-axis bar or thin `renderContent`), depth-axis inversion
   (= negated-Y series + `QgsNumericFormat` rendering absolute value).
6. **No second scene.** Selection/hover/annotation draw as `QgsPlotCanvasItem`
   overlays inside the same scene — never a parallel paint pass on a QWidget.
7. **Export is vectorial.** `QSvgGenerator`/`QPdfWriter`/`QImage` →
   `QgsRenderContext::fromQPainter` → each item's `Qgs2DPlot::render` into its
   fractional rect (same path as `QgsLayoutItemChart::draw`).
8. **Data-driven series** (layer-derived) use `QgsVectorLayerXyPlotDataGatherer`
   on `QgsTaskManager` — consume, don't re-implement (Prompt 4 seam).

## Layer placement (repo invariants honored)

- `libs/qgis_plot` is Qt/QGIS-coupled host-side infra (like `libs/qgis`,
  `libs/ui_map`) — it is *allowed* to be Qtful; it is the visualization seam,
  not domain logic. Domain math stays Qt-free in `libs/viz_charts` etc.
- App wiring stays in `apps/`; page contracts (`set_data`, `summary_line`,
  honest-degradation messages) unchanged.

## Depth-axis convention

Depth/elevation "increases downward" semantics are expressed as **negated Y**
(`y = -depth`) inside the series data + a `PwbDepthValueFormat`
(`QgsNumericFormat` subclass emitting absolute values) on the axis. Rationale:
`Qgs2DXyPlot` assumes `min < max`; reversed ranges are untested upstream.
This keeps rendering stock and confines domain semantics to the adapter.
