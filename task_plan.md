# Task Plan — Prompt 6: QGIS Native Plot / Scientific 2D Visualization Convergence

## Goal (Oracle)

产品内交互式二维 Plot 基础设施收敛到 `QgsPlotCanvas` / `QgsPlot` / `QgsPlotTool` / `QgsPlotRegistry`（QGIS 4.2 vendored SDK）。Paleo 只保留领域语义、数据绑定、计算、provenance。

**Verifiable DoD（本 session 可达子集标记 ✓session）:**
1. ✓ 交互式 2D plot 统一走 `QgsPlotCanvas`（新 infra + 至少 3 类代表页面迁移）
2. ✓ ≥3 类代表页面迁移：统计/QC 图 + 交会/散点图 + 测井/曲线页
3. ✓ 通用 plot toolbar/tool 走 QGIS PlotTool，不自研双轨
4. map ↔ plot ↔ data selection 联动 seam 建立
5. 自研 generic plot canvas/chart engine 数量显著下降（有替代矩阵数字）
6. plot 数据绑定/domain id 回查/style/export 路径统一
7. 架构 gate：新页面不得新增第二套 plot 基础设施（lint 脚本或文档 gate）
8. 生命周期：开关项目/面板无 UAF（测试覆盖）
9. 性能测试：大样本散点/多序列无 O(N²) 重绘路径
10. build/test `-j <= 6`（常态 -j4）
11. 两轮 review，P0/P1 = 0
12. branch push + PR 创建（不 merge）

## Baseline

- origin/main SHA: `192422c60c4eb99ee78a6a410676293ca09053cc`
- Worktree: `/home/kevin/projects/paleo-qgis-plot`
- Branch: `feat/qgis-native-plot-scientific-visualization`
- QGIS: vendored 4.2.0 source `third_party/qgis`; prebuilt SDK 复用自 main worktree `native/qgis_render_bridge/build/qgis-vendor/output`（只读）
- Qt: system Qt6 (`/usr`), Ninja, Release
- Build dir: `build/native-product`（本 worktree 独立）
- deps prefix: `/home/kevin/projects/paleo_project/main/build/qgis-deps-prefix`

## Phases

| Phase | 内容 | 状态 |
|-------|------|------|
| 0 | 审计 + 11 份文档 (`docs/development/qgis-native-plot-convergence/`) | done |
| 1 | `libs/qgis_plot` infra: `PwbPlotCanvas`(QgsPlotCanvas 子类) + plot item + tool 装配 | done |
| 2 | Wave A 迁移：XyScatterHost(散点) + ComparisonView(QC) + TimeDepth/WellLog(曲线) | done |
| 3 | 统一 plot toolbar/actions（QGIS tool + QAction 绑定） | done (PwbPlotPanel) |
| 4 | domain binding 约定（series_id → domain_object_id 回查） | done (SeriesBinding) |
| 5 | map ↔ plot selection seam（不抢 Prompt 2 的 map truth） | deferred → Wave B（无现役 map↔plot 消费点） |
| 7 | 退役被替代的 generic plot widget（wave A 范围） | done (plot_widget/cross_plot_widget/qt series.hpp) |
| 8 | 测试：unit + integration + interaction + scale | done (smoke 30/30)；pa_flow/preview 回归进行中 |
| - | review 2 轮 + 修复 + PR | R1 内置自查+R2 双轴 subagent 完成、修复完；全量构建+回归进行中 |

## 边界（与其他 5 条 worktree）

- 拥有：`QgsPlotCanvas` 派生、scientific 2D plots、plot tools、map↔plot 联动 seam
- 不碰：main_window 装配（Prompt 1）、QgsMapCanvas/layer tree（Prompt 2）、project/data core（Prompt 3）、Processing/Task core（Prompt 4）、QgsLayout core（Prompt 5）
- 跨边界只允许具名 seam，PR 中标注

## 风险 / 待决

- `QgsPlotCanvas` 是框架基类（虚函数默认空实现），需 `PwbPlotCanvas` 子类实现 plot-space↔canvas 映射 —— 官方模式（QgsElevationProfileCanvas）
- QgsPlot 体系无 histogram/scatter/legend 专用 item —— 需 Paleo-specific thin adapter（允许）
- well-log-engine 子模块边界待审计（subagent 进行中）
- main worktree 有 ~94 个未提交改动（另一 session 在飞），可能与本方向文件重叠 —— 记录于 overlap ledger
