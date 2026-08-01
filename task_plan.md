# Task Plan: Paleo Workbench 整体简化、重构与文档整理

## Goal

对 `paleo_workbench` 项目进行全面的系统性重构与代码简化（P1-P4），斩断反向依赖，清理死代码与重复样板，拆分上帝类，并整理项目文档与配置文件，确保测试 100% 保持全绿。

## Current Phase

Phase W5（WellLogEngine #162 /to-tickets 拆解）— Complete; 6 子工单 #196-#201 已发布，frontier = #196

> 本计划同时承载独立轨道 **WellLogEngine C++ 子系统**（`well-log-engine/`）的开发，见下方 Phase W1。

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

### Phase 16: P5 等值面与相干性 3D 接入

- [x] `marching_cubes_3d` 重写为 Marching Tetrahedra（水密，替换点汤实现），Python 保底去点汤改 skimage/ImportError
- [x] 引擎 `Renderer3D.set_isosurface` + `geoviz_seismic.isosurface` 注入钩子 + facade 导出
- [x] SeismicView 等值面工具栏控件（checkbox + 阈值 + 200ms 防抖）
- [x] workbench 启动注入 C++ 提取器（`render_accel`）
- [x] 相干性 C3 接入属性下拉（`attribute_pipeline`）
- **Status:** complete

### Phase W1: WellLogEngine #154 Phase B — 图形↔表格选择联动（ADR 0024）

独立 C++ 子系统轨道（`well-log-engine/`），与上述 Python 重构无依赖关系。分支 `agent/welllog-pdf-spike-185`，直接在此开发（非 submodule）。

#### W1.1: Commit 1 — WellLogSession 中的 Selection Set（ADR 0024）
- [x] `session.hpp` 新增类型：`SelectionDepthRange`、`SelectionState`、3 个 command struct
- [x] 新增 `ViewEventKind::selection_changed` / `selection_invalidated`
- [x] mapping helpers（depth-range↔row-span，increasing & decreasing 轴）
- [x] `execute(SetSelection/SetRowSelection/ClearSelectionCommand)` + `selection()` accessor
- [x] SetDocumentCommand 中安全 remap/invalidation
- [x] headless 测试 `welllog.session-selection`（12 用例）
- [x] 修复 Phase A 遗留打包 bug（`welllog_table` 未加入 install EXPORT）
- **Status:** complete（commit `bb12774`）

#### W1.2: Commit 2 — 图形↔表格双向联动
- [x] `TableModel`：selection 反射 + 行选择命令 + 轴隔离
- [x] `WellLogView`：slots + signal + Ctrl+drag 拖选手势
- [x] clipboard 内部 MIME identity（doc|rev|axis + curveId|unit）
- [x] Qt sync 测试 `welllog.qt-table-selection-sync`
- **Status:** complete（commit `119c091`）

#### W1.3: Commit 3 — 两轴自审（Standards + Spec）
- [x] qt-cpp-review lint（新代码聚焦）
- [x] 修复真实问题：`set_projection()` 未清除陈旧 selection source/反射
- [x] 回归测试 `set_projection_clears_stale_selection_source`（8 用例总计）
- **Status:** complete（commit `746bb7f`）

#### W1.4: Commit 4 — 正式 /code-review（两轴并行子代理）
- [x] 固定点 `1dea684`，diff `1dea684..HEAD`（Phase B 3 commit）
- [x] Standards 轴 + Spec 轴并行子代理审查
- [x] **Standards hard 修复**：selection 失败拆为 3 个 distinct 错误码（`document_not_found`/`missing_sampling_axis`/`invalid_viewport`），替代单一 `invalid_viewport`（Mysterious Name）
- [x] 测试断言各 distinct 错误码 + `one_selection_per_document_evicts_other_axis`（锁定 ADR 0024 单键意图）
- [x] 延后（用户决定）：GL band 高亮渲染、绝对容差、variant 重构
- **Status:** complete（commit `641a635`），session-selection 13 用例，31/31 green

#### W1.4: 交付与验证
- [x] 31/31 headless green（原 29；+2 新测试）
- [x] 工作树干净；core 边界检查通过
- [x] #154 全部 8 条验收标准满足
- **Status:** complete

### Phase W2: #155 XLSX/XML/CSV 表格导出

独立 C++ 轨道（`well-log-engine/`），`/implement` #155（被 #154 阻塞，现已解锁）。CSV → XML → XLSX，每后端独立 commit + TDD，最后两轴 `/code-review`。固定点 `641a635`。

#### W2.1: Commit 1 — table-export 组件 + CSV
- [x] G1 TableColumn 加 ScalarType；G3 `depth_domain_name/parse_depth_domain` 提升为 public core；G2 `format.hpp`；G5 `atomic_write.hpp`（§10）；G4 新组件 + 修 install EXPORT（含遗留 welllog_export_pdf）
- [x] CSV writer（§7）+ CsvPackageExporter（目录+manifest.json）；4 用例
- **Status:** complete（commit `b871af0`）

#### W2.2: Commit 2 — 版本化 XML（§6）
- [x] `<wellLogTables schemaVersion>` + 流式 `<row>`（原始 buffer，非 LOD）
- [x] 禁 DTD/外部实体/网络；XML 转义；§6 往返测试；5 用例
- **Status:** complete（commit `75dcbf7`）

#### W2.3: Commit 3 — 自包含 XLSX（§5）
- [x] 手写 ZipWriter（ZLIB deflate + CRC32）+ OOXML parts
- [x] 数值为数值、null 为空；>1,048,576 行 `_01/_02` 分表 + metadata global start row
- [x] 测试用 ZLIB inflate 读回验证；4 用例
- **Status:** complete（commit `147516c`）

#### W2.4: Commit 4 — 两轴 /code-review 修复
- [x] Standards：I/O 错误码改 `internal_error`（不再误用 `invalid_manifest`）；删 dead `stage` 参
- [x] Spec：XML referenceDepth 共识派生（不再 over-fit axes().front()）；新增 `TableProjection::slice()` 选择导出路径（满足 "支持 Selection Set"）
- [x] 记录 XLSX 内存上限为已知限制（§5.2 流式 follow-up）
- **Status:** complete（commit `e663fdc`），34/34 green

### Phase W3: #183 Manifest round-trip for ImageSource + CustomLayerSource

`/implement` #183（ManifestCodec 对 ImageSource/CustomLayerSource 零代码 → 无法往返）。单 commit + 两轴 `/code-review` 修复。固定点 `8ebd35e`。

#### W3.1: Commit 1 — manifest round-trip 补全
- [x] write 补 imageSources（id/dims/pixelFormat/depths/dpi/source）+ customSources（id/contentRevision/4 primitive + clip），仅非空时输出
- [x] read 补 optional_field + schema gate 放宽 + 重建两类实体
- [x] `manifest_schema_version` 1→2；ADR 0042 限制在 manifest 层强制
- [x] manifest-local helper（pixel_format_name/symbol_kind_name/number/boolean）+ `manifest_error(msg,code)` overload
- **Status:** complete（commit `f52c257`）

#### W3.2: Commit 2 — 两轴 /code-review 修复
- [x] Standards：`primitive_vertex_count` 改镜像 scene 的 tessellated 计数（tri=3/quad=6/sym=24）；补 per-polyline(≥2,≤8192) + per-clip(≥3,≤8192) 点上限
- [x] Spec：version gate 改接受 {1,2}（真前向兼容）；测试加固（triangle 全坐标 + symbol color + over-pixel/zero-dpi 负例 + version_gate 双向）
- **Status:** complete（commit `3ed8ca6`），34/34 green

### Phase W4: #184 Thread ImagePyramidMap through the session frame path

`/implement` #184（session 异步帧路径只穿 CurveLodMap → 图像层经 session 不可达）。单 commit + 两轴 `/code-review` 修复。固定点 `f75e4c7`。

#### W4.1: Commit 1 — session 接入 ImagePyramidMap
- [x] PerformanceBudgets 加 `image_pyramid_options`；LOD worker 为 ImageSource 建 pyramid（ImagePyramid::build，仅元数据 ADR 0045）
- [x] CurvePreparation 携带 image_pyramids；make_frame_task 加 image 参调 image-aware prepare（3 调用点 + pixel_height double 转换）
- [x] WellLogView `set_image_pyramid_options` + session `set_performance_budgets`；parity 测试
- **Status:** complete（commit `f0a1191`）

#### W4.2: Commit 2 — 两轴 /code-review 修复
- [x] Standards：image derived bytes 折入聚合 derived_bytes（ADR 0034）；图像失败发 `image_pyramid_unavailable` Diagnostic 后降级（qsp §7）
- [x] Spec：parity 测试从 tile COUNT 强化到 tile SET 相等 + session viewport 断言
- **Status:** complete（commit `cf6d774`），34/34 green

### Phase W5: #162 /to-tickets 拆解（append-batch 多工单化）

`/implement` #162 调研后发现需全新基础设施（CompositeBufferView + 增量 LOD），超单切片 → 走 `/to-tickets` 拆为 6 个 tracer-bullet 子工单。

#### W5.1: 调研 + 拆解 + 发布
- [x] 调研：BufferView 单连续（无复合类型）、LOD 全量重建、SetDocumentCommand 盲替换+清 viewport
- [x] /to-tickets 拆 6 子工单（composite-buffer expand/contract + append + incr-LOD + viewport + coalescing）
- [x] 发布 GitHub #196-#201（parent #162，ready-for-agent，原生 blocking），#162 body 加 sub-tickets 注释
- **Status:** complete。子工单链：#196（frontier）→ #197 → #198 → {#199, #200} → #201

## Decisions Made

| Decision | Rationale |
|---|---|
| 保留旧模块 (如 `preview_widgets.py`, `fallback_preview.py`) 作为 re-export 兼容门面 | 维持 100% 向后兼容性，避免对依赖第三方或动态 monkeypatch 的测试造成破坏。 |
| 将 `resources/preview_parsers/` 下沉到 `resources/` | 保持 `resources` 作为基础资源/格式解析层，符合 `ui → viz/workflow/resources/mapping → project` 的分层依赖规则。 |
| 拆分 `map_edit_scene.py` 为 4 个高内聚辅助模块 | 将几何工厂、草图状态机、吸附管理器、拓扑算法与主 Scene 事件路由解耦，提高可维护性。 |
| 采用 pybind11 构建 `seismic_3d_core` 原生模块 | 在纯 Python / NumPy 算法保底的前提下，通过 C++ 单线程计算（释放 GIL）与内存连续性提供高效震相计算与切片提取。 |
| 采用 pybind11 构建 `well_log_core` 测井原生扩展 | 将视口 Min-Max LOD 抽稀、ASCII 解析与交叠填色下沉到 `viz/` 算法层与原生扩展，保障 60 FPS 渲染。 |
| **[W1]** Selection 状态唯一存于 WellLogSession | ADR 0024 单一真相源；view/table 都是 adapter（与 viewport/crosshair 一致） |
| **[W1]** 选择基于身份（EntityId + Reference Depth + sample index + DocumentRevision） | 不存屏幕坐标/Display Depth/LOD 点（ADR 0024） |
| **[W1]** 跳过 GL band 高亮渲染 | 标准是关于选择 sync，可 headless 测试；绘制是后续 ticket |
| **[W1]** 图形输入 = Both（API + Ctrl+drag） | 用户明确选择；既暴露 API 供宿主，又内置手势 |
| **[W1]** mapping 用线性扫描（非二分） | 选择时（非每帧）触发；轴长度典型规模下可接受；简化正确性 |
| **[W1]** `apply_selection` 为私有成员函数 | 需访问 `WellLogSession::Impl`（私有嵌套结构），自由函数无法命名 |

## Errors Encountered & Resolved

| Error | Attempt | Resolution |
|---|---:|---|
| `AttributeError: '_safe_stat'` during test monkeypatch | 1 | 在 `PreviewProvider` 重新暴露 `_safe_stat` 并注入 `safe_stat_fn` 参数。 |
| `setPageMode` failure on stub `QPdfView` | 1 | 统一通过 `preview_widgets.QPdfView` 动态反射获取 `PageMode` 枚举值。 |
| `NumPy 2.5 DeprecationWarning` in `document_parsers.py` | 1 | 将 `dataset.read(1, out_shape=(1, h, w))` 的 3D shape 改为标准的 2D shape `(h, w)`。 |
| `compute_coherence_3d` numerical parity discrepancy | 1 | 修正 C++ 相干性算法公式，使其与 Python 逐道均方根归一化一致。 |
| `fast_las_parse_data` return type discrepancy | 1 | 统一 C++ 原生扩展 headers 返回类型为 Python tuple 保持类型完全一致。 |
| **[W1]** `range_for_rows` 返回匿名 struct 类型非法 | 1 | 改为命名 `RowSpan` struct |
| **[W1]** `apply_selection` 自由函数无法访问 `Impl` | 1 | 改为私有成员函数（header 声明） |
| **[W1]** `RowSelection` 在类后定义导致 MOC 报错 | 1 | 移到类前定义，删除重复 |
| **[W1]** cmake reconfigure 报 "welllog_table not in export set" | 1 | Phase A 遗留打包 bug；加入 install EXPORT（非本会话引入） |
| **[W1]** `qt-table-model` 旧测试断言旧 MIME 格式失败 | 1 | 更新断言匹配新 identity 格式 |
| **[W1]** `set_projection` 未清除陈旧 selection 反射（自审发现） | 1 | 清除 source + 反射 span + 回归测试 |
