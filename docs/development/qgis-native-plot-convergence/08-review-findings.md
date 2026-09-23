# 08 — Review Findings

审查基线：`feat/qgis-native-plot-scientific-visualization`（baseline `192422c60`）。
两轮 review：Round 1 = 迁移正确性/契约保真自查；Round 2 = 独立 code-review 子代理。

## Round 1 — 自查发现（已修复）

| # | 严重度 | 发现 | 处置 |
|---|--------|------|------|
| R1-1 | P1 | `XyScatterHost` 散点色误用 matplotlib `#1f77b4`；oracle 默认 "sleek blue" 是 `QColor(64,156,255)`=`#409cff`，SVG 测试断言该色 | 改回 `#409cff` + marker 6.0px |
| R1-2 | P1 | 联动 pan/zoom 用各自 `plotArea()` 像素宽反推数据位移 → 各轨 plotArea 宽不同（y 轴标签宽不同）→ shareX 漂移 | `panContentsBy`/`scalePlot`/`centerPlotOn`/`zoomToRect` 全部改为**统一数据空间位移**（以首个 shareX item 为 pivot） |
| R1-3 | P1 | `QPdfWriter` painter 上 `calculateOptimisedIntervals` 文本度量返回 0 → `while(true)` 死循环，PDF 导出挂死 | interval 先在 scratch `QImage` 上下文中算好（持久存于 axis），再在真实 painter 上 render |
| R1-4 | P2 | wheel zoom 因子符号反（`pow(1.25,-delta/120)`）→ 滚轮方向相反 | `1.25^(+delta/120)` |
| R1-5 | P2 | `PwbDepthNumericFormat` 受 locale 千分位影响输出 "1 500" | 固定 `QLocale::c()` / 去分隔符 |
| R1-6 | P2 | `PwbRangeBandPlot` 首版把 NaN 段连成带 → 缺测不诚实 | 连续有限段分段成带，NaN 断带 |
| R1-7 | P2 | `well_log` bucket 轴用 `labelInterval(0)` 企图隐藏——`<=0` 实为 auto 重算 | `Qgis::PlotAxisType::Categorical` + 空 categories（0 次循环，完全隐藏） |
| R1-8 | P2 | 工具 action 每次点击 `new` 工具对象 → 子对象堆积 | 惰性单例成员 |
| R1-9 | P2 | `ComparisonView` 旧代码把 empty reason 画在被 `setVisible(false)` 的 canvas 上 → 理由永不可见（潜在 bug） | `PwbPlotPanel::showUnavailable(reason)` 真正显示 |
| R1-10 | P2 | 头文件内命名空间作用域 `class QgsPlotToolPan*` 前置声明遮蔽全局 QGIS 类型（两处：qgis_plot 头 + viz_e_hosts.hpp） | 前置声明移全局/正确命名空间；cpp 直接 include 真实头 |

## Round 1 — 保留项（诚实边界，非缺陷）

| # | 项 | 理由 |
|---|----|------|
| K-1 | `SurfaceWidget`/`ColorbarWidget` 仍在 `SurfaceHost` | 网格曲面+contour 渲染是域专用渲染器；QGIS Plot 无 contour-surface item。等值线提取核（viz_charts marching-squares）是 Qt-free 数学，正确保留 |
| K-2 | WLE OpenGL 多轨渲染器 | 领域高性能专用渲染；不作为 generic plot 迁移目标（见 02-plot-inventory 边界节） |
| K-3 | `PwbIntervalStripPlot`/`PwbRangeBandPlot`/`PwbScatterPlot` 自绘内容 | QGIS `Qgs2DXyPlot::renderContent` 的合法扩展点（upstream 同款模式）；轴/网格/坐标映射/导出仍归 QGIS |

## Round 2 — 双轴 subagent 评审（已完成）

两轴并行 review（standards + spec），修复结果：

### 已修复（P0/P1）

- **P0**：`tests/cpp/viz_e/pa_flow_test.cpp` 残留 `#include <pwb/viz_charts/qt/plot_widget.hpp>`（已删头文件，编译会断）→ 改为 `pwb/qgis_plot/plot_canvas.hpp`。
- `PwbDepthNumericFormat` 未真正禁用千分位（locale "1 500"）→ 构造时 `setShowThousandsSeparator(false)`。
- `padRange` 退化区间 padding 比旧 PlotWidget 大 20×（单点散点 ±50000）→ 对齐旧式 `0.05·(0.1·|v| or 1)`。
- `resizeEvent` 未维持 equal-aspect → resize 后按当前中心重等比（对齐旧 `PlotWidget::resizeEvent` 语义）。
- `clearPlots` 不复位 `has_view_` → 已复位。
- `setHorizontalGuide` 死参数 `label` → 删除形参。
- `depth_at_canvas_pos` 在 plotArea 外返回 -1（旧 `depth_at_y` 是 clamp）→ 恢复 clamp 行为。
- verdict 条带 alpha：`verdict_color` 内嵌 alpha 被 `band.alpha` 覆盖，不可比条带丢透明度 → band.alpha 取自 `verdict_color().alpha()`；死三元 `?140:140` 删除。
- PDF 导出页尺寸从 widget 像素改回 **A4 整页**（与旧 `PlotWidget::export_pdf` / Python oracle 对齐）。
- `libs/ui_pages_preview/CMakeLists.txt` `if(TARGET Pwb::QgisPlot)` 假可选（cpp 无条件 include）→ 改硬链接。
- `tests/cpp/viz_e` 缺 `Pwb::QgisPlot` 链接 → 已补。
- `qgis_plot.smoke` 缺 QGIS runtime `ENVIRONMENT_MODIFICATION`/`PROJ_*` → 已补（与兄弟测试同 boilerplate）。
- `PwbPlotPanel` 工具栏英文 chrome → 中文（选点/平移/框选缩放/横向缩放/套索/适应）。
- 零消费的 `PwbColumnPlot` 删除；`setColumnWeights`/`column_weights_` 删除（布局等分）。
- 文档 08/10 残留 heredoc 命令文本 → 清除；三处过时注释修正（viz_e_hosts 导出契约、viz_charts_tests “four ported”、series_binding “non-Qt”）。
- `axis_role` 词表与实现对齐（"xy"|"time-depth"|"value"|"depth"）。

### 保留（有理由，记录在案）

- `PwbPlotToolLasso`/`setSeriesZValues`/hover-identify 信号族：任务书明确要求 selection/brush/hover 交互面；CrossPlotWidget 无生产消费点（纯移植件）已删，z-ramp 是 Wave B 交会图迁移的既定接口且有 smoke 覆盖。
- `XyScatterHost` 不复用 `PwbPlotPanel`：host 需要 `export_requested` 信号、标题行、`show_unavailable` 隐藏语义，面板 chrome 不兼容该契约——保留自管工具栏是有意分歧。
- `toCanvasCoordinates` 多轨歧义：约定首个 shareX item 映射，已注释。
