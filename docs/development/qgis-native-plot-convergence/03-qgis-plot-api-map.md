# 03 — QGIS Plot API Map (vendored 4.2.0, verified from headers)

Provenance: `third_party/qgis/UPSTREAM.md` → `final-4_2_0` tag, upstream commit `ca5812c8`.
All signatures below read from the vendored tree — no reliance on external docs.

## Architectural invariant

`QgsPlot` objects are **pure renderers** — they hold no data. Data arrives at render
time as `const QgsPlotData&`. `QgsPlotCanvas` is a `QGraphicsView` + tool dispatcher
with **no `setPlot()`**; plots reach the screen through `QgsPlotCanvasItem`
subclasses. The only in-tree consumer is the elevation profile:
`QgsElevationProfileCanvas` (`src/gui/elevation/`) is the reference implementation
this work follows.

## Core (`qgis_core`, `src/core/plot/`)

| Class | Key API | Notes |
|-------|---------|-------|
| `QgsPlot` | `type()`, `writeXml/readXml`, `DataDefinedProperty` (margins, axis intervals, axis min/max), `initFromPlot` | abstract base |
| `QgsPlotRenderContext` | empty context struct | render-time context |
| `QgsAbstractPlotSeries` | `name()/setName()`, `clone()` | |
| `QgsXyPlotSeries` | `data()/setData(QList<pair<double,double>>)`, `append(x,y)`, `clear()` | the only concrete series type |
| `QgsPlotData` | `series()/addSeries(SIP_TRANSFER)/clearSeries()`, `categories()/setCategories(QStringList)` | owns series (deep copy via clone) |
| `QgsPlotAxis` | `type` (`Qgis::PlotAxisType::{Interval,Categorical}`), `gridIntervalMajor/Minor`, `labelInterval`, `gridMajor/MinorSymbol` (QgsLineSymbol), `textFormat`, `numericFormat` (QgsNumericFormat), `labelSuffix` + `PlotAxisSuffixPlacement` | **no axis-title API** |
| `Qgs2DPlot : QgsPlot` | `render(rc, plotCtx, plotData)`, `renderContent(rc, plotCtx, plotArea, plotData)` extension point, `size()/setSize` (mm), `margins`, `interiorPlotArea()` | base render draws nothing but content area calc |
| `Qgs2DXyPlot : Qgs2DPlot` | `x/yMinimum/Maximum`, `xAxis()/yAxis()`, `chartBackgroundSymbol/chartBorderSymbol` (QgsFillSymbol), `flipAxes()`, `calculateOptimisedIntervals()` (1-2-5×10ⁿ rounding, ~40% label coverage) | renders grid+axes+border, then `renderContent` |
| `QgsLineChartPlot : Qgs2DXyPlot` | `setMarkerSymbolAt(i)`, `setLineSymbolAt(i)`, `create()`, `createDataGatherer()` | **marker-only = scatter** (empty line symbols → points render only, `qgslinechartplot.cpp:100,159-209`); NaN-Y breaks polylines |
| `QgsBarChartPlot : Qgs2DXyPlot` | `setFillSymbolAt(i)`, `create()`, `createDataGatherer()` | grouped bars from y=0 baseline; categorical or interval X; honors `flipAxes` |
| `QgsPieChartPlot : Qgs2DPlot` | `setFillSymbolAt(i)`, `setColorRampAt(i)`, `labelType` (`NoLabels/Categories/Values`), `textFormat`, `numericFormat` | NOT XY (no axes); one pie per series |
| `QgsPlotRegistry` | `populate()` registers `bar`/`line`/`pie`; `createPlot(type)`, `plotMetadata(type)`, `plotTypes()` | via `QgsApplication::plotRegistry()` |
| `QgsPlotAbstractMetadata` / `QgsPlotMetadata` | `createPlot`, `createPlotDataGatherer`, `createPlotWidget` | domain plot types registrable |
| `QgsVectorLayerXyPlotDataGatherer : QgsTask` | `XySeriesDetails{name,xExpression,yExpression,filterExpression}`, `setFeatureIterator`, `data() → QgsPlotData` | **Prompt-4 seam**: series harvested from vector layers on `QgsTaskManager` |
| `QgsPlotDefaultSettings` | `axisLabelNumericFormat()`, `axisGridMajor/MinorSymbol()`, `chartBackground/BorderSymbol()`, `lineChartMarker/LineSymbol()`, `barChartFillSymbol()`, `pieChart*()` | default factories |

## GUI (`qgis_gui`, `src/gui/plot/`)

| Class | Key API | Notes |
|-------|---------|-------|
| `QgsPlotCanvas : QGraphicsView` | `setTool/unsetTool/tool`, `scene()`, `refresh()`; virtuals (all default no-op): `panContentsBy`, `centerPlotOn`, `scalePlot(factor)`, `zoomToRect(QRectF)`, `snapToPlot(QPoint)→QgsPointXY`, `wheelZoom`, `crs`, `toMapCoordinates/toCanvasCoordinates`; signals `toolChanged`, `plotAreaChanged`, `contextMenuAboutToShow`, `willBeDeleted` | auto-creates transient Space/middle-mouse pan + Ctrl+Space zoom tools; wheel→`tool->wheelEvent` then `wheelZoom`; `QEvent::ToolTip`→`tool->canvasToolTipEvent`; unaccepted right-click→context menu iff tool `ShowContextMenu` flag. **Destructor does NOT delete scene items** |
| `QgsPlotTool : QObject` | protected ctor `(canvas, name)`; `plot{Move,Press,Release,DoubleClick}Event(QgsPlotMouseEvent*)`, `wheelEvent`, `keyPress/ReleaseEvent`, `gestureEvent`, `canvasToolTipEvent(QHelpEvent*)→bool`; `activate/deactivate`, `setAction(QAction*)` (checkable sync), `flags()` (`ShowContextMenu`), `populateContextMenuWithEvent` | parented to canvas; helpers `isClickAndDrag`, `constrainPointToRect` |
| `QgsPlotToolPan` | drag→`panContentsBy`, middle-click→`centerPlotOn` | ready-made |
| `QgsPlotToolZoom` | marquee zoom via owned `QgsPlotRectangularRubberBand`; click→zoom-in ×2, Alt+click→×0.5; **C++-only virtuals**: `constrainStartPoint/constrainMovePoint/constrainBounds`, `zoomIn/OutClickOn` | axis-locked zoom = subclass + constrain override |
| `QgsPlotToolXAxisZoom` | ctor hard-binds `QgsElevationProfileCanvas*` (`SIP_NO_FILE`, unstable) | not reusable → thin `Pwb` equivalent subclassing `QgsPlotToolZoom` |
| `QgsPlotToolTemporary{KeyPan,MousePan,KeyZoom}` | auto-created by canvas | free |
| `QgsPlotCanvasItem : QGraphicsItem` | protected ctor `(canvas)` auto-adds to `canvas->scene()`; pure `paint(QPainter*)`; implement `boundingRect()` | the display hook |
| `QgsPlotRubberBand` / `QgsPlotRectangularRubberBand` | `start/update/finish→QRectF`, pen/brush; Shift=square, Alt=from-center | base is abstract → polygon lasso = small subclass |
| `QgsPlotMouseEvent : QMouseEvent` | `mapPoint()` via `canvas->toMapCoordinates`; `snappedPoint()/isSnapped()` via `canvas->snapToPlot` (lazy cached) | |
| `QgsPlotWidget : QgsPanelWidget` | `setPlot/createPlot`, data-defined override buttons | config panel for layout item editor; needs `QgsGui::initPlotWidgets()` — not a display canvas |

## Reference wiring (upstream, `src/app/elevation/qgselevationprofilewidget.cpp:182-331`)

```
canvas = new QgsElevationProfileCanvas
tools = {Pan, Zoom, XAxisZoom, Identify, Measure}  // each: tool->setAction(checkable QAction)
action->triggered → canvas->setTool(tool); canvas->setTool(default)
export: QgsRenderContext::fromQPainter(QImage|QPdfWriter painter) → canvas->render(rc,w,h,plotSettings)
```

Item mechanics (`QgsElevationProfilePlotItem : Qgs2DXyPlot, QgsPlotCanvasItem`):
`updateRect()` → `mRect = canvas->rect()`, `setSize(mRect.size())` (px as plot size),
`setPos(mRect.topLeft())`; `paint()` → cached `QImage` @ devicePixelRatio,
`QgsRenderContext::fromQPainter`, `setMapToPixel`, `calculateOptimisedIntervals`,
`render(rc, plotCtx)`; `plotArea()` = cached `interiorPlotArea`; linear
canvas↔plot mapping (y flipped at `area.bottom()`).

## Gaps → Paleo thin adapters (sanctioned, minimal)

| Need | Status | Adapter |
|------|--------|---------|
| Histogram | absent | interval-axis `QgsBarChartPlot`, or thin `Qgs2DXyPlot` subclass |
| Scatter | no class | `QgsLineChartPlot` + marker symbol only |
| Per-point labels, crosshair, selection markers | absent | `QgsPlotCanvasItem` overlay |
| Hover/identify | hooks only (`canvasToolTipEvent`, `snapToPlot`) | ambient crosshair in canvas `mouseMoveEvent` + thin identify tool |
| Rect/lasso selection | rect rubber band exists; polygon absent | `QgsPlotRubberBand` subclass (polygon) + `QgsPlotTool` |
| Export image/SVG/PDF | not on canvas | `Qgs2DPlot::render` onto `QImage/QSvgGenerator/QPdfWriter` painter |
| Axis titles | absent | thin item-side margin text |
| Multi-track linked panels | absent | N plot items on one canvas, axis-share flags on canvas nav |
| Legend | absent | deferred — series `name()` exists; thin overlay later |

## Layout / processing seams (already in-tree)

- `QgsLayoutItemChart` (`src/core/layout/`): owns `Qgs2DPlot`, runs `QgsVectorLayerXyPlotDataGatherer` as `QgsTask`, `draw()` → `plot->render(rc, plotCtx, mPlotData)` — **the Prompt-5 bridge is upstream-native**.
- `QgsGui::initPlotWidgets()` (`qgsgui.cpp:456-483`): binds GUI widget factories into the registry — call once before `createPlotWidget`.
