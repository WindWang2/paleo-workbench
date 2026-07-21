# 连井对比优化设计

日期：2026-07-21
状态：已确认（头脑风暴后用户批准）
关联：`2026-07-20-multiwell-correlation-workbench-design.md`（前置工作）

## 背景与现状

`paleo_workbench` 的连井对比由 `ui/pages/stratigraphy_correlation_page.py`（三栏：井选择 / CrossWell 视图 / 操作）承载，底层复用 `geo-viz-engine` 的 `CrossWellCanvas`/`CrossWellWidget` 引擎。`CompositeVisualizationPanel` 的"连井"标签页使用同一引擎。

引擎能力调研结论（优化切入点）：

- 引擎已支持 DTW 自动对齐（`propagate_pick_via_dtw`）、可撤销的分层拾取（`HorizonPicksModel` 命令栈）、分层顶线渲染（`FormationTopsModel`）、手动/自动对比连线（`toggle_manual_link` / `auto_link` + `set_formation_data`）——但 workbench UI **全部未暴露**。
- 渲染通道为纯 Python/NumPy + QPainter：任一井深度变化经 `QPainterSyncManager` 使**所有**井的整幅 `QPixmap` 缓存失效并重绘；C++ `well_log_core`（`minmax_downsample`、`fast_las_parse_data`）已存在且测试验证，但连井路径未使用。
- 井间距硬编码 150px；`export_composite` 支持 svg/pdf/png 但无 DPI/尺寸选项。
- 工程已有 `well_stratification`（井分层）资源类型（`resources/io_registry.py`），但只路由到 engine_preview，未进入连井视图；连井视图目前只有预测相数据。

## 目标

用户确认的四个优化方向：对比交互功能、界面布局与体验、渲染性能、数据与导出。其中性能已是实际痛点（多井缩放/平移明显卡顿），井分层数据确认接入。

## 总体架构

改动横跨两个仓库：

- **`geo-viz-engine/`（引擎层）**：渲染性能优化、少量公共 API 补强（井间距、导出参数、可注入 downsample 钩子）。
- **`paleo_workbench/`（应用层）**：数据接入（井分层→tops model/formation data）、UI 暴露（工具条、轨道控制、导出对话框）、工作流编排、C++ 能力注入。

约束：不制造 geoviz → paleo_workbench 反向依赖；引擎改动保持默认行为向后兼容。

三个阶段独立交付、独立回归（基线：全量 pytest 1130+ 全绿；geo-viz-engine 自带测试套件一并回归）：

| 阶段 | 目标 | 主要落点 |
|---|---|---|
| P1 性能 | 消除多井缩放/平移卡顿，加速 LAS 加载 | geo-viz-engine 渲染通道 + workbench LAS 加载 |
| P2 数据+交互 | 井分层接入、同名层自动连线、DTW/拾取 UI、轨道/间距控制 | workbench 工作流 + 页面 UI，少量引擎 API |
| P3 导出 | PNG/PDF/SVG 格式 + DPI/尺寸选项 | 引擎 `export_composite` 扩展 + workbench 导出对话框 |

## P1 性能优化

1. **C++ LOD 接入曲线渲染**：引擎 `CurveTrack._downsample`（`geoviz_well_log/renderer/curve_track.py`）当前为纯 NumPy min-max 抽稀。在引擎侧增加可注入的 downsample 钩子（模块级 setter，默认内置 NumPy 实现，行为不变）；workbench 启动时注入 `viz/well_log_api.minmax_downsample`（C++ `well_log_core`，含 Python 保底）。
2. **修复缓存级联失效**：`QPainterSyncManager` 对任一井深度变化向所有 canvas 调 `set_depth_range`，导致每口井整幅 `_static_cache` QPixmap 作废、全部轨道重绘。优化：深度范围未实际变化的 canvas 跳过缓存失效；缩放/平移同步经 16ms 节流合并（复用引擎已有 `_coalesce_timer` 模式）。
3. **LAS 加载走 C++ 解析**：`viz/well_log_load.py` 从 `geoviz.load_las_preview`（纯 Python ASCII 解析）切换到 `well_log_api.fast_las_parse_data` 通道（已有数值等价测试）。
4. **视口裁剪**：`CrossWellWidget` 位于 `QScrollArea` 内，滚动时屏外 canvas 仍全量绘制；为绘制路径增加可见区域裁剪。

测试：性能项沿用项目 TDD 惯例，加 perf parity 测试（参照 Phase 9 地震加速的做法）；回归全量 pytest。

## P2 数据接入 + 对比交互

### 数据通道（井分层 → 连井视图）

- 新增 `workflow/stratigraphy_correlation.load_well_tops()`：读取工程中 `well_stratification` 资源，按井名匹配已加载对比井，解析为分层顶（名称 + 深度）列表。
- 分层文件解析器放在 `resources/preview_parsers` 同层，遵循现有注册表模式；实施前先调研 `data/井分层/` 实际文件格式。
- 双路注入引擎：
  - `CrossWellCanvas.tops_model.add_top` / `load_csv` —— 每井显示虚线分层顶线（引擎已支持渲染）；
  - `CrossWellWidget.set_formation_data(well_name, intervals)` —— 供 `auto_link()` 按同名分层自动绘制井间对比连线（引擎已支持）。

### UI 交互暴露（`StratigraphyCorrelationPage` 中栏顶部新增工具条）

- 模式切换：浏览 / 手动拾取（`pick_mode` + `active_formation` 选择 + 吸附类型）/ 手动连线（`toggle_manual_link`）。
- DTW 按钮：对参考井参考深度执行 `propagate_pick_via_dtw`；ghost pick 点击确认、右键拒绝（引擎原生交互）。
- 撤销/重做按钮（引擎 picks model 自带命令栈）。
- "自动连线"按钮调 `auto_link()`；分层顶线显隐开关。
- 每井轨道显隐（`set_track_visible`）；井间距滑杆——引擎侧把硬编码 150px 提为 `set_well_spacing()` API，`export_composite` 使用同一值。
- "导出分层顶 CSV"按钮（`FormationTopsModel.save_csv` 已存在），便于对比结果回存。

`CompositeVisualizationPanel` 的"连井"标签页共享同一 host，按需同步受益，不做单独 UI 扩展。

## P3 导出增强

- 引擎 `CrossWellWidget.export_composite(path, fmt)` 增加可选参数：`dpi`（PNG）、`page_size`（PDF）、`width_px`（重采样宽度）；默认参数保持现有行为（向后兼容现有测试）。
- workbench"导出连井 SVG"按钮改为导出对话框：格式（SVG/PNG/PDF）、PNG DPI（96/150/300）、文件名；默认目录沿用 `default_export_dir`。

## 测试策略

- P1：perf parity 测试 + 全量 pytest 回归。
- P2：分层解析器单元测试、`load_well_tops` 工作流测试、tops/formation 注入测试、工具条 UI smoke 测试（Qt）。
- P3：导出参数测试（三种格式、DPI 生效）。
- 每阶段结束跑全量 pytest 保持全绿；geo-viz-engine 测试套件同步回归。

## 非目标（YAGNI）

- 不做 WellSectionCanvas 与 CrossWellWidget 两套多井实现的合并（引擎层大重构，超出本次范围）。
- 不做深度域压平（datum flatten）——依赖无人填充的 `stratigraphy` 属性，后续单独立项。
- 不做井震标定（WellTie）相关改动。
- 不引入新的第三方依赖。
