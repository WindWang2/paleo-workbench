# 10 — Final Verification

收尾验证清单（本地为准，不依赖线上 CI）。

## 构建

- [x] `ninja -j2` 全绿（~494 objects；期间 4 次 cc1plus 随机段错误为 GCC16 快照环境问题，重试即过，非本 diff）
- [x] `git diff --check` 无空白错误

## 测试矩阵

| 测试 | 覆盖 | 状态 |
|------|------|------|
|| `qgis_plot.smoke` | canvas/item/tool/导航/联动/导出/生命周期 30 项 | PASS 30/30 |
|| `viz_e.pa_flow` | XyScatterHost 端到端：viewBounds 数据域、SVG `<circle>`+#409cff、PDF | PASS |
|| `ui_pages_preview.{qt_widgets_smoke,oracle_replay,viz_d_cores,viz_d_presenter_smoke}` | presenter `data()`/`summary_line()`/`grab()` 回归 | PASS 4/4 |
|| `viz_charts.{oracle_replay,qt_widgets_smoke}` | 存活的 Surface/Colorbar 域专用 widget | PASS 2/2 |
|| `platform.*`（comparison_view/viz_e_hosts 编译入的 8 个） | ComparisonView 装配/联动门控 | PASS 8/8 |

## DoD 对照

1. 交互式 2D plot 基础设施 = `QgsPlotCanvas`（PwbPlotCanvas 子类）— ✅ Wave A 四个消费点全部在其上
2. ≥3 类代表页迁移：统计/QC = ComparisonView；交会/散点 = XyScatterHost；曲线 = TimeDepth + WellLog — ✅
3. plot toolbar/tool 无双轨：pan/zoom/identify 全走 QgsPlotTool — ✅（XyScatterHost/PwbPlotPanel）
4. map↔plot↔data 联动 seam：SeriesBinding domain id 回查 + PointHit 信号 — ✅（基础设施层；map 侧 seam 留给后续 wave）
5. generic plot canvas 数量下降：PlotWidget 生产消费点 1→0；CompareCanvas 自绘 1→0；两个 preview 页 QPainter 移除 — ✅
6. 绑定/style/导出统一：SeriesBinding + PwbPlotPanel export — ✅
7. 新页无第二套 infra：新代码全部 `Pwb::QgisPlot` — ✅
8. 生命周期：QObject 父子树 + scene item 所有权清晰；smoke 含 teardown 断言 — ✅
9. 性能/规模：LTTB 语义由 bucket min-max + NaN 断带保留；480 列预算不变 — ✅
10. -j<=6：全程 -j4 — ✅
11. 两轮 review：Round 1 内置自查 + Round 2 双轴 subagent（standards/spec）均完成，P0/P1 修复清零 — ✅
12. push + PR：待

## 已知限制

- QGIS Plot 无现成 legend item — Wave A 未启用 legend（原页面也无 legend）
- tooltip/hover 文本是 canvas 级 crosshair+label；无 per-point HTML tooltip
- SurfaceWidget（网格曲面）与 WLE OpenGL 轨保留为域专用渲染器
- `QgsPlotRegistry` 尚未需要扩展点（stock item + renderContent 子类已够）