# Task Plan: Paleo Workbench 整体简化、重构与文档整理

## Goal

对 `paleo_workbench` 项目进行全面的系统性重构与代码简化（P1-P4），斩断反向依赖，清理死代码与重复样板，拆分上帝类，并整理项目文档与配置文件，确保测试 100% 保持全绿。

## Current Phase

Phase 5 — Complete & Verified

## Phases

### Phase 1: P1 — 低风险去重 + 死代码清理

- [x] 提取共享任务面板基类，合并 `prediction_task_panel.py` 与 `seismic_task_panel.py`
- [x] 合并 `seismic_prediction.py` 与 `well_log_prediction.py` 的公共预测工作流
- [x] 删除死代码：`adapters/` 包、`workflow/well_table.py` 无用函数及未使用的 UI 组件
- [x] 提取 `PAGE_INDEX_*` 到 `ui/navigation.py`，暴露 `workflow_controller` 公开 API
- **Status:** complete (Commit `933d769`)

### Phase 2: P2 — 分层架构修复

- [x] 斩断 `viz → ui` 依赖：下沉 `mapping_helpers`、`prediction_helpers`、`seismic_prediction_helpers`、`geoviz_preview_host` 到 `viz/`
- [x] 消除 `resources → workflow` 依赖：迁移 `record_export` 到 `project/artifacts.py` 并删除旧模块
- [x] 上移并清理 30+ 处函数内 import
- **Status:** complete (Commit `a7bcd59`)

### Phase 3: P3 — 预览子系统归位与控件拆分

- [x] 将格式解析下沉到 `resources/preview_parsers/`（含 table, well_log, seismic, office, document 解析器）
- [x] `_build_preview` 改用 `PreviewRegistry` 注册表模式
- [x] 将 `preview_widgets.py` 拆分为 12 个独立预览控件模块，保留 100% 兼容门面
- **Status:** complete (Commit `ac291e0`)

### Phase 4: P4 — 拆分 `map_edit_scene.py` (上帝类瘦身)

- [x] 抽取 `map_edit_factory.py`（图形项工厂纯函数）
- [x] 抽取 `map_edit_draft.py`（草图绘制状态机与预览控制）
- [x] 抽取 `map_edit_snap.py`（控制点吸附与候选点缓存管理）
- [x] 抽取 `map_edit_topology.py`（拓扑校验与几何合并/拆分编排）
- [x] `map_edit_scene.py` 代码行数从 1382 行降至 604 行（缩减 56%）
- **Status:** complete (Commit `8974bbe`)

### Phase 6: 3D 地震核心算法 C++ 原生加速 (TDD 范式)

- [x] 编写 TDD 先行测试 `tests/test_seismic_3d_api.py` (RED) 验证算法契约
- [x] 实现 `paleo_workbench/viz/seismic_3d_api.py` 纯 Python/NumPy 回退算法 (GREEN)
- [x] 构建 C++ pybind11 原生扩展 `native/seismic_3d_core`（含 `fast_slice_extract`, `compute_coherence_3d`, `marching_cubes_3d`）
- [x] 编写 C++ 契约与数值等价性测试 `tests/test_seismic_3d_cpp.py` (GREEN)
- [x] 将 `fast_slice_extract` 接入 `SeismicSlicePreviewWidget` 预览控件
- **Status:** complete

### Phase 7: 测井显示与计算 C++ 原生加速 (TDD 范式与模块化架构)

- [x] 编写 TDD 先行测试 `tests/test_well_log_api.py` (RED) 验证算法契约
- [x] 实现 `paleo_workbench/viz/well_log_api.py` 纯 Python/NumPy 保底算法 (GREEN)
- [x] 构建 C++ pybind11 跨平台原生扩展 `native/well_log_core`（含 `minmax_downsample`, `fast_las_parse_data`, `generate_crossover_fill`）
- [x] 编写 C++ 契约与数值等价性测试 `tests/test_well_log_cpp.py` (GREEN)
- [x] 将 `fast_las_parse_data` 接入 `well_log_parsers.py` 解析通道
- **Status:** complete

### Phase 8: 现代轻量化主题与 UI 交互增强

- [x] 实现 `paleo_workbench/ui/tokens.py` 设计系统与 `build_modern_qss` 动态样式引擎
- [x] 完成 1127/1127 全量回归测试，确认 UI 主题切换不影响逻辑状态
- **Status:** complete

### Phase 9: 地震预览与可视化 C++ / GPU 原生双重加速

- [x] C++ 拓展实现 `fast_slice_to_indexed8` 与 `fast_resample_volume_3d`
- [x] 重构 `SeismicSlicePreviewWidget` 切片实时渲染通道与 Colormap 预缓存
- [x] 重构 `seismic_load.py` 3D 数据加载下采样通道
- [x] 完成 1129/1129 全量回归测试 (含 C++ perf parity 测试)
- **Status:** complete

### Phase 10: 连井对比视图 `QScrollArea` 视口滚动隔离

- [x] 限制连井对比 (`StratigraphyCorrelationPage` & `CompositeVisualizationPanel`) 画布控件尺寸扩张
- [x] 嵌入自适应 `QScrollArea` 视口与滚动条 (`ScrollBarAsNeeded`)
- [x] 确保多井连井 (5-20+ 口井) 加载时不会改变或拉伸主程序窗口大小
- [x] 完成 1130/1130 全量回归测试 (含视口滚动测试)
- **Status:** complete

### Phase 11: 连井对比 P1 性能优化

- [x] 引擎曲线渲染接入可注入 downsample 钩子，启动时注入 C++ `minmax_downsample`
- [x] 修复 `set_depth_range` 无操作导致的全井缓存级联失效
- [x] LAS 加载切换 C++ `fast_las_parse_data` 快速通道（保留引擎保底回退）
- [x] 离屏 canvas 跳过栅格化（QScrollArea 视口外延迟重绘）
- **Status:** complete

### Phase 12: 连井对比 P2 井分层接入 + 对比交互

- [x] 新增 SMI WellTops 解析器与工作流接入（`load_well_tops` / `match_tops_to_wells` / `tops_to_intervals`）
- [x] 引擎补 `set_well_spacing` / `set_tops_visible` / `set_track_visible_by_label` API 与 `FormationTop` facade 导出
- [x] 地层对比页工具条：浏览/拾取/连线模式、层位与吸附选择、DTW 传播、撤销/重做、自动连线、分层顶线开关、井间距滑杆、轨道显隐、分层顶 CSV 导出
- **Status:** complete

### Phase 13: 连井对比 P3 导出增强

- [x] 引擎 `export_composite` 增加仅关键字可选参数 `dpi` / `width_px` / `page_size`（默认行为不变，兼容 export_service 位置调用）
- [x] 新增 `CrossWellExportDialog`（格式 SVG/PNG/PDF、DPI 96/150/300、宽度、PDF 纸张 A4/Letter）
- [x] 地层对比页导出按钮改为对话框流程
- **Status:** complete

### Phase 14: 测井渲染通道性能加固（P4 阶段 A）

- [x] CurveTrack ndarray 化 + downsample 钩子协议升级（ndarray 进 ndarray 出）+ render_accel 迁移
- [x] 表头 min/max 预计算（修复 NaN `nan~nan` bug）+ path cache 量化键修复
- [x] LAS 表格预览去 lasio（C++ fast channel）
- [x] LAS C++ 解析器 GIL 释放 + from_chars/strtod + 去双重解析
- **Status:** complete

### Phase 15: 地震切片交互性能加固（P4 阶段 B）

- [x] 新增 SliceReadWorker（自有 loader、最新优先队列、±2 邻域预取、generation 失效）
- [x] SeismicView 异步接线（缓存未命中不再阻塞 GUI）+ `_pending_slice` 按轴字典修复 `_on_jump` 三面板一致
- [x] renderer_3d 按轴切片平面更新（`_update_slice_planes_for`）
- [x] 预览控件 80ms 防抖、resize 缓存缩放、NumPy 色表
- **Status:** complete

## Decisions Made

| Decision | Rationale |
|---|---|
| 保留旧模块 (如 `preview_widgets.py`, `fallback_preview.py`) 作为 re-export 兼容门面 | 维持 100% 向后兼容性，避免对依赖第三方或动态 monkeypatch 的测试造成破坏。 |
| 将 `resources/preview_parsers/` 下沉到 `resources/` | 保持 `resources` 作为基础资源/格式解析层，符合 `ui → viz/workflow/resources/mapping → project` 的分层依赖规则。 |
| 拆分 `map_edit_scene.py` 为 4 个高内聚辅助模块 | 将几何工厂、草图状态机、吸附管理器、拓扑算法与主 Scene 事件路由解耦，提高可维护性。 |
| 采用 pybind11 构建 `seismic_3d_core` 原生模块 | 在纯 Python / NumPy 算法保底的前提下，通过 C++ 多线程与内存连续性提供高效震相计算与切片提取。 |
| 采用 pybind11 构建 `well_log_core` 测井原生扩展 | 将视口 Min-Max LOD 抽稀、ASCII 解析与交叠填色下沉到 `viz/` 算法层与原生扩展，保障 60 FPS 渲染。 |

## Errors Encountered & Resolved

| Error | Attempt | Resolution |
|---|---:|---|
| `AttributeError: '_safe_stat'` during test monkeypatch | 1 | 在 `PreviewProvider` 重新暴露 `_safe_stat` 并注入 `safe_stat_fn` 参数。 |
| `setPageMode` failure on stub `QPdfView` | 1 | 统一通过 `preview_widgets.QPdfView` 动态反射获取 `PageMode` 枚举值。 |
| `NumPy 2.5 DeprecationWarning` in `document_parsers.py` | 1 | 将 `dataset.read(1, out_shape=(1, h, w))` 的 3D shape 改为标准的 2D shape `(h, w)`。 |
| `compute_coherence_3d` numerical parity discrepancy | 1 | 修正 C++ 相干性算法公式，使其与 Python 逐道均方根归一化一致。 |
| `fast_las_parse_data` return type discrepancy | 1 | 统一 C++ 原生扩展 headers 返回类型为 Python tuple 保持类型完全一致。 |
