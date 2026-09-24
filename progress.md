# Progress — QGIS Native Plot Convergence

## Session 1 — 2026-09-23

| 时间 | 动作 | 结果 |
|------|------|------|
| 启动 | fetch --all --prune; baseline=192422c60 | ✓ |
| 启动 | gh pr/issue 审计：open PR #1482(data) #1483(layer)；open issue #1472 #1429 | ✓ |
| 启动 | worktree 创建 /home/kevin/projects/paleo-qgis-plot @ feat/qgis-native-plot-scientific-visualization | ✓ |
| 审计 | QGIS 4.2.0 vendored; plot API 面确认（core+gui plot 目录） | ✓ |
| 审计 | QgsPlotCanvas=框架基类; QgsElevationProfileCanvas=官方参考实现 | ✓ |
| 审计 | SDK 复用路径+deps prefix+Qt 前缀确认 | ✓ |
| 审计 | 3 个 background subagent 启动：API map / 产品清单 / 子模块边界 | 进行中 |

## 遇到的错误

| 错误 | 尝试次数 | 解决方案 |
|------|---------|---------|
| - | - | - |

## Session 2 — libs/qgis_plot landed, smoke green

- New library `libs/qgis_plot` -> `Pwb::QgisPlot`, wired after libs/qgis.
  - PwbPlotCanvas (QgsPlotCanvas subclass): column layout of PwbPlotItems,
    pan/zoom/x-zoom/wheel zoom/marquee zoom via STOCK QGIS tools, linked
    shareX/shareY axes (uniform data-space translation — fixes track drift),
    equal-aspect option, hover->nearestPoint->PointHit(domain id) with
    crosshair overlay, identifyRect, PNG/SVG/PDF vector export, autofit.
  - PwbPlotItem (QgsPlotCanvasItem): holds Qgs2DPlot + QgsPlotData, image
    cache, axis titles in margins (upstream axes have none), canvas<->data
    mapping incl. flipAxes, nearestSeriesPoint/pointsInRect.
  - Tools: PwbPlotToolXAxisZoom (QgsPlotToolZoom + full-height constraint),
    PwbPlotToolIdentify (click pick + rect identify), PwbPlotToolLasso
    (freehand polygon, canvas coords).
  - Domain plots: PwbScatterPlot (per-point z-ramp colours + labels),
    PwbColumnPlot (numeric-x column bands for QC strips).
  - PwbDepthNumericFormat: |depth| labels for negated-depth axes.
  - PwbPlotPanel: toolbar + actions -> QGIS plot tools (single state machine).
- Gotchas found: qgs2dplot.h does not exist (Qgs2DXyPlot lives in qgsplot.h);
  QgsPlotToolZoom ctor takes canvas only; AUTOMOC needs headers in sources;
  QPdfWriter painter breaks calculateOptimisedIntervals (infinite loop on
  label metrics) -> intervals computed on a scratch-image context; wheel-zoom
  factor is 1.25^(delta/120) (positive delta = zoom in).
- Test: qgis_plot.smoke — 26/26 PASS offscreen (render, mapping, real tool
  drags, hover, identify, lasso, multi-track link, flipAxes, exports, teardown).

## Session 3 — Wave A migrations landed (compile-clean)

- XyScatterHost (viz_e_hosts.*): PlotWidget -> PwbPlotCanvas + PwbScatterPlot;
  toolbar = stock QgsPlotToolPan/Zoom + PwbPlotToolIdentify; oracle colour
  #409cff + size 6.0 preserved (SVG `<circle>` assertions still valid —
  same QPainter drawEllipse primitive). viewBounds()/export_svg_to/
  export_pdf_to test contract kept.
- TimeDepthPreviewPage + WellLogPreviewPage -> PwbPlotPanel; well-log =
  N x PwbRangeBandPlot columns, shareX linked buckets, per-column y-range.
- ComparisonView (QC 对比页): CompareCanvas QPainter -> PwbPlotPanel +
  N x PwbIntervalStripPlot (new domain item: labelled depth bands,
  y=-depth + PwbDepthNumericFormat). 3 modes preserved (并排3列/叠加2列/
  差异1列); unlocated verdict rows keep the even-split fallback; link
  cursor -> canvas->setHorizontalGuide (new PwbHGuideItem); honest empty
  state now actually visible via panel->showUnavailable (old code painted
  the reason on a hidden canvas — dead code).
- CMake: Pwb::QgisPlot added to all 8 targets compiling
  comparison_view.cpp + viz_e_hosts.cpp closures (pwb-platform shell
  block, app_shell, three_stage_flow, constraint_authoring,
  closure_review_install, closure_mapping, ribbon_visual,
  closure_preview, viz_e test).
- TU-level compile verified out-of-ninja (build dir busy with full dep
  build): comparison_view.cpp / well_log_preview_presenter.cpp /
  time_depth_preview_presenter.cpp / viz_e_hosts.cpp all EXIT:0.
- Fixed: marker colour must be oracle #409cff (was matplotlib #1f77b4);
  hpp `canvas()` moved out-of-line (incomplete PwbPlotPanel);
  namespace-shadowed forward decls in viz_e_hosts.hpp.

## Session 4 — 退役 + Round-2 review 修复

- Generic 层退役完成：`plot_widget.*`、`cross_plot_widget.*`、`qt/series.hpp`
  已从 libs/viz_charts 删除；qt_widgets_smoke 收敛到 Surface/Colorbar。
- PwbPlotItem::setFullExtent —— 无 QgsPlotData 序列的域内容项
  （PwbIntervalStripPlot）声明显式全幅；zoomFull/resize 首 autofit 走
  item->extent()。ComparisonView Fit 从此可用。
- 双轴 subagent review（standards+spec）完成；P0 一个
  （pa_flow_test 残留已删头文件 include）+ ~15 项 P1/P2 全部修复：
  深度格式千分位、padRange 退化语义对齐旧版、resize 等比重锁定、
  clearPlots 复位 has_view_、guide 死参数、verdict alpha 透传、
  PDF 回 A4 整页、viz_e/preview CMake 链接、smoke 测试 runtime env、
  面板 chrome 中文化、PwbColumnPlot/setColumnWeights 零消费删除、
  文档 heredoc 垃圾清理、三处过时注释。
- qgis_plot.smoke 30/30 PASS（新增 interval-strip/hguide 断言）。

## Still open

- Full `ninja` build finishing（重启后进行中）。
- viz_e.pa_flow SVG export assertions（`<circle` count、#409cff）。
- Preview presenter tests；platform_closure_* link check。
- `git diff --check` → commit → push → PR。
