# VIZ-E — 图表绘制与数据预览主程序集成（计划 V6 净剩余 + P-A 接线）

分支：`codex/viz-e-charts-preview`，基线 `origin/main` @ `7bf29aae`（2026-09-19）。
计划来源：`docs/development/cpp-geoviz-completion-plan.md` V6 + P-A（§1.2/§3-V6）；独占修复 #1382/#1383。

## 独占落点（并行写入协议）

- `libs/viz_charts`（新库：Qt-free 核 + Qt widget 层）
- `libs/ui_pages_preview` 的 chart/surface 预览装配（dispatcher/总装侧）
- `libs/ui_pages_data` 消费接线（`preview_dispatch` 模式词表扩展）
- `libs/ui_data_core` 的 #1382/#1383 最小修复（独立提交，先行）
- `apps/paleo_workbench_platform/viz_e_*`（install/adapter）
- `tests/cpp/viz_e`、`tools/oracle/generate_viz_e_*.py`、`docs/development/cpp-viz-e/`
- 主 CMakeLists / apps CMake：仅 `BEGIN/END VIZ-E` 独立增量块

不触碰：A 的 LAS registry（`libs/ingest/preview/las_*`）、D 的 seismic widget、B 的报告内核（`libs/visualization/{cross_well,well_tie}`）、C 的 store 并发修复（`libs/data_suite` 等）。

## 复用 / 排除（开工前查证结论）

- **复用**：`DataReaderPanel::register_target/register_render_hook`、`LazyVisualizationTabs::set_host_factory`（main 上现成注册 seam，不自造 presenter 架构）；`ui_workers::{contour_draft,factor_prepare}` 的 JobSpec/JobCenter 闭环；`FactorTaskSlice::engine_contours`/`ContourDraftSlice` 呈现数据；`mapping_kernel::FactorGrid`/`FactorGridEnvelope`；viz-a 确立的 `viz_x_install(window, jobs)` + 根 CMake `BEGIN VIZ-X` 块接线范式。
- **排除**（prompt 明示）：通用图像/PDF/媒体/JSON/切片预览组件、数据/home 页面组件本体、mapping 计算核、factor/contour worker 计算半、科学 service、QGIS composer/layout/export（CONV-29 已做）。
- **兄弟线状态**（2026-09-19 查证）：viz-a 本地 11 commits（ingest LAS 桥 + `viz_a_install`）；viz-b PR #1400、viz-c PR #1402 OPEN（dock 路线，未碰 ui_pages_*）；viz-d 未开工。B/C/A 均未注册预览 presenter——本线先把注册约定立好即成模板。

## V6 绘制半差距表（R7，扣除已迁移计算/布局/页面）

| Python 源（geoviz_plots @ 0885195） | 行数 | C++ 现状 | 去向 |
|---|---|---|---|
| `chart/plot_widget.py`（PlotWidget：系列/轴/网格/hover/选中/导出） | 1132 | 无 | `libs/viz_charts` Qt 层 |
| `chart/series.py`（Line/ScatterSeries、LTTB 降采样） | 145 | 无 | 核 + Qt |
| `chart/axes.py`（Heckbert nice ticks、格式化） | 99 | 无 | Qt-free 核 |
| `chart/colorbar.py`（连续渐变/离散色块） | 88 | 无 | Qt 层 |
| `chart/convex_hull.py`（点在多边形/凸包） | 65 | 无 | Qt-free 核 |
| `chart/cross_plot_widget.py`（散点+z 着色+套索掩码） | 320 | 无 | Qt 层 |
| `surface/surface_widget.py`（等值线/带填充/控制点/断层线） | 611 | 无 | Qt 层 |
| `surface/marching_squares.py`（contourpy 提取线/带） | 206 | 无（contourpy 无 C++ 对应） | Qt-free 核自实现（行进方块） |
| `surface/colormaps.py`（viridis/cnpc_strat/cnpc_fluid/thermal） | 80 | seismic_viewer 有 color_maps（地震色标，非同集） | Qt-free 核（按停靠点精确转录） |
| `fence/fence_generator.py`（井栅栏网格/地震切片） | 119 | 无 | Qt-free 核 |
| `analytics/well_qc.py`（MAD/z-score/sand ratio） | 66 | 无 | Qt-free 核 |
| `factor/__init__.py` 呈现产物（interpolate_factor_grid dict） | ~130 | `mapping_kernel::FactorGrid` 已有计算半 | 适配层（grid→surface widget） |

**已迁移不重复**：plots 计算半（contour_draft/interpolation/crs/factor 计算）→ `libs/mapping_kernel`/`factor_host` + `ui_workers`（冻结案例全过）；页面壳 → `libs/ui_pages_preview`/`ui_pages_data`（UI-06/07 lib-ready）；`map_edit/`、`geomodel/`、`interpolation/` 计算半不在 R7。

## 承载选型决策（V6 决策门，先决记录）

**采用 Qt6 QPainter 自绘**，理由：
1. Python 参考实现本身就是纯 QPainter（plot/surface/crossplot/colorbar 零 matplotlib 依赖；`QPolygonF` 断线、`OddEvenFill`、`QSvgGenerator`/`QPrinter` 导出都是 Qt 特有语义）——自绘是对参考行为的 1:1 冻结路径。
2. 无新第三方依赖与许可评审（Qwt（LGPL，需动态链接约束）/QCharts（GPL/商业）均引入依赖面）。
3. 3D surface 场景用既有 `geo3d_viz` viewport（本线不造 GL 引擎，2D surface 即 `SurfaceWidget` 等值线呈现）。

**matplotlib 特性冻结口径（重要修正）**：计划文档 V6 验收提到"对数轴/双轴/图例"，经逐行核验 Python 参考实现（plot_widget.py/surface_widget.py/cross_plot_widget.py）**不存在**对数轴、双轴与 legend 绘制——轴全部线性笛卡尔（`set_view_bounds` 显式校验 xmin<xmax/ymin<ymax 禁止反转），"图例"由 `ColorbarWidget` 承担（连续 20px 渐变条 + 5 刻度，或离散色块）。因此本线按**实际参考行为**冻结：线性轴、Colorbar 图例语义、NaN 断线/跳过；对数轴/双轴按"参考实现即无此行为"记录，不虚构实现。字体/抗锯齿差异容差见 oracle 章。

## 验收门（本线硬性 Oracle）

1. 真实工程资产在主程序数据页选中→图表/surface 预览→导出闭环（P-A 装配 + E2E 测试）。
2. factor/contour 真实结果进入画面，抽查点值/轴/颜色/CRS/单位/provenance。
3. #1382/#1383 复现测试先失败后通过；视图重建、资源删除/刷新、空 shared_ptr、全部 variant 分支安全。
4. 图表几何/spec oracle + 渲染/导出验证齐全；旧测试回归、关键两遍、ON/OFF、主程序测试有效。
5. 外部 presenter 注册契约明确；本线 chart/P-A 独立 E2E 不因他线止步。

## 资源约束

`invoke-resource-gate.sh`（Linux，flock 于 `.bare` 共同目录），jobs=2 强制，`CMAKE_BUILD_PARALLEL_LEVEL=2`、`CTEST_PARALLEL_LEVEL=2`、OMP/BLAS=1；build 目录 `build/viz-e`（Configure/Build/Test 子命令，重型命令 Exec 包装）；入场 ≥8GiB；不绕锁编译、不嵌套门禁。

## 轮账（每轮追加）

| 轮 | 改动 | 验证 | 结果 | 下一步 |
|---|---|---|---|---|
| 1 | worktree 创建、三路侦察、差距表、选型决策 | 门禁 Probe RESOURCE_READY 46.6GiB；子模块 SHA 核对（geoviz 0885195 = gitlink） | 通过 | #1382/#1383 失败复现测试 |

| 2 | #1382/#1383 修复 + 复现测试（asset_view_guard，44 检查） | 修复前 SIGSEGV（gdb: metadata.value 读已释放内存）→修复后 44/44 ×2 遍 + MALLOC_CHECK_=3；ui_data_core.smoke 31/31 | 通过 | 提交 3644d562 |
| 3 | libs/viz_charts Qt-free 核（axes/series/colormaps/convex_hull/marching_squares/fence/well_qc）+ oracle 生成器 + 回放测试 | 生成器跑真 geoviz venv（SHA=gitlink 校验，8 族篡改负检）；回放 792 检查 ×2 遍 + ctest + MALLOC | 通过 | 提交本轮；Qt widget 层 |

## 容差与算法差异声明（oracle 契约）

- **精确族**：ticks/nice_number/format_tick/lttb/bounds/colormaps/pip/fence/fence_slice/qc（1e-12~1e-4，fence 为 float32 语义）。
- **凸包**：与 SciPy CCW 顶点环按"旋转等价"比较——qhull 起始顶点无稳定文档约定（三点实验证实起始点不定）；消费方（point_in_polygon）旋转无关。
- **等值线（线）**：与 contourpy serial 相同的 QUAD 拓扑（边上插值公式逐边定向一致、鞍点中心均值配对、角点恰等于层值时弦端点落在角上）；NaN 角格元按 contourpy 实测语义处理（3 有效角→有效角三角形；≤2 有效角→无贡献）。计数 ±1、总长 2% 容差。鞍点 mini-grid 实测总长精确一致（4.472）。
- **带填充**：三角剖分（双线性中心）+ 半平面裁剪（z 插值修复后）；面积 2% 容差、颜色/label 精确。study_area_clip 仅实现 Python 的无 shapely 回退（不裁剪），已在头文件声明。
