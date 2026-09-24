# Findings — QGIS Native Plot Convergence

## QGIS 4.2.0 Plot API（已从 vendored 头文件确认）

### core/plot (`PwbQgis::Core`)
- `QgsPlot` — 抽象基类（type(), writeXml/readXml, DataDefinedProperty: margins/axis intervals/min/max）
- `Qgs2DPlot : QgsPlot` — size/margins/interiorPlotArea/render(context, plotContext, plotData)
- `Qgs2DXyPlot : Qgs2DPlot` — x/yMinimum/Maximum, xAxis()/yAxis() → QgsPlotAxis, chartBackgroundSymbol/chartBorderSymbol, flipAxes, calculateOptimisedIntervals()
- `QgsPlotAxis` — type (Interval/Categorical?), gridIntervalMajor/Minor, labelInterval, gridMajor/MinorSymbol (QgsLineSymbol), textFormat, numericFormat, labelSuffix
- `QgsPlotData` — QList<QgsAbstractPlotSeries*> + categories (QStringList)
- `QgsXyPlotSeries : QgsAbstractPlotSeries` — QList<pair<double,double>> data, setData/append/clear
- `QgsLineChartPlot`, `QgsBarChartPlot`, `QgsPieChartPlot` — 待读详细签名（subagent A）
- `QgsPlotRegistry` — plot type registry
- `QgsPlotDefaultSettings` — default symbols/formats factory
- `QgsVectorLayerPlotDataGatherer` — 从矢量层采集 plot 数据（数据驱动！）

### gui/plot (`PwbQgis::Gui`)
- `QgsPlotCanvas : QGraphicsView` — **框架基类**，管理 QGraphicsScene + QgsPlotTool 栈 + 事件分发；虚函数默认空实现：panContentsBy/centerPlotOn/scalePlot/zoomToRect/snapToPlot/wheelZoom/crs/toMapCoordinates/toCanvasCoordinates。信号：toolChanged/plotAreaChanged/contextMenuAboutToShow/willBeDeleted。内置 space/mid-mouse 临时 pan/zoom tool。
- `QgsPlotTool : QObject` — activate/deactivate, plot{Move,Press,Release,DoubleClick}Event(QgsPlotMouseEvent*), wheelEvent, keyEvent, gestureEvent, canvasToolTipEvent(QHelpEvent*), setAction(QAction*) → 与工具栏 checkable action 联动, populateContextMenuWithEvent
- `QgsPlotToolPan`, `QgsPlotToolZoom`, `QgsPlotToolXAxisZoom` — 现成
- `qgsplottransienttools.h` — TemporaryKeyPan/MousePan/KeyZoom
- `QgsPlotCanvasItem : QGraphicsItem` — 场景叠加项基类
- `QgsPlotRubberBand` — 矩形橡皮筋
- `QgsPlotMouseEvent` — plot 坐标事件
- `QgsPlotWidget` — 待确认（可能是 layout item 配置 widget，非显示 canvas）

### 参考实现
- `src/gui/elevation/qgselevationprofilecanvas.h` — QgsElevationProfileCanvas : QgsPlotCanvas，内含 QgsElevationProfilePlotItem(QgsPlotCanvasItem 渲染 Qgs2DXyPlot) + QgsElevationProfileCrossHairsItem + identify()/snapToPlot()/zoomFull()/canvasPointHovered 信号。PwbPlotCanvas 照此模式。

## 构建事实

- SDK 复用：`-DPALEO_QGIS_SDK_DIR=/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor/output` `-DPALEO_QGIS_BUILD_DIR=.../qgis-vendor` `-DPALEO_QGIS_SOURCE_DIR=<本worktree>/third_party/qgis` `-DPWB_QGIS_DEPS_PREFIX=/home/kevin/projects/paleo_project/main/build/qgis-deps-prefix` `-DPWB_QT_PREFIX=/usr`
- `PwbQgis::Sdk` INTERFACE target：核心 include 闭包 + Core/Gui/Analysis imported .so
- 本机 16 核；约束 -j4
- Preset 注意：`CMakePresets.json` 的 linux preset binaryDir 在 `build/presets/*`；main worktree 用 `build/native-product` 手工配置。沿用 `build/native-product` 保持一致。

## 已存在并行工作（overlap ledger 输入）

- PR #1483 open: `feat/qgis-native-layer-control`（Prompt 2）
- PR #1482 open: `feat/qgis-native-data-management`（Prompt 3）
- worktrees 无 PR：paleo-qgis-shell / paleo-qgis-processing / paleo-qgis-layout（均在 baseline，无 commit）
- main worktree 脏：94 项改动，含 `libs/visualization/src/{cross_well/qt/section_canvas,well_tie/qt/tie_canvas,cross_well/qt/formation_tops_preview}.cpp`、`ui_workstation` panels、`main_window.*`、`viz_c_time_map.cpp`、`factor_stats_dock.cpp` —— 与我方向重叠，需记 ledger（那些改动未进 origin/main，不在我 baseline）

## 实施结果摘要（Session 3-4）

- 新库 `libs/qgis_plot` → `Pwb::QgisPlot`：PwbPlotCanvas / PwbPlotItem /
  PwbScatterPlot / PwbRangeBandPlot / PwbIntervalStripPlot /
  PwbPlotTool{Identify,Lasso,XAxisZoom} / PwbDepthNumericFormat /
  SeriesBinding / PointHit / PwbPlotPanel。
- 迁移 4 面（≥3 达标）：XyScatterHost（散点）、ComparisonView（QC 对比，
  3 模式+深度游标联动）、TimeDepthPreviewPage、WellLogPreviewPage。
- 退役 generic 层：plot_widget/cross_plot_widget/qt-series.hpp 删除；
  SurfaceWidget/ColorbarWidget 保留（域专用）；Qt-free kernel 全保留。
- 关键 API 事实：`Qgs2DXyPlot` 在 `qgsplot.h`（无 qgs2dplot.h）；
  tool 构造单参 canvas；`flipAxes()` 原生轴翻转；
  `calculateOptimisedIntervals` 对 QPdfWriter painter 度量死循环 →
  scratch QImage 预计算；AUTOMOC 要求 Q_OBJECT 头文件列入 sources。
- 测试：qgis_plot.smoke 30/30 PASS（含 interval strip 显式 extent、
  hguide、lasso、PNG/SVG/PDF 导出、panel 生命周期）。

## Review 结论（Round 2，双轴）

- spec 轴：判定"真收敛、非 wrapper"——pan/zoom 实现在 QGIS 规定的虚
  函数 seam（同 QgsElevationProfileCanvas），无第二状态机；
  P0 = pa_flow_test 残留已删头文件（已修）。
- standards 轴：无架构违规；修正项全部落地（见 08-review-findings.md）。

## 待 subagent 回报

- A/B/C 均已回报并归档进 docs/development/qgis-native-plot-convergence/
