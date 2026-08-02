# Task Plan: Paleo Workbench 整体简化、重构与文档整理

## Goal

对 `paleo_workbench` 项目进行全面的系统性重构与代码简化（P1-P4），斩断反向依赖，清理死代码与重复样板，拆分上帝类，并整理项目文档与配置文件，确保测试 100% 保持全绿。

## Current Phase

Phase W21 (#171 container security hardening) complete.  
**Open frontier (examples):** #174 (100M gate), #172–#173.

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

### Phase W6: #196 CompositeBufferView（#162 append 基础，expand）

`/implement` #196（#162 拆解后 frontier）。单 commit + 两轴 `/code-review`（0 发现）。固定点 `baee494`。

#### W6.1: core 新增 CompositeBufferView + 测试
- [x] core 新增 `CompositeBufferView`（from_segments/length/value_as_double 跨段拼接/segments 迭代）；PIMPL 不可变，每段 SharedOwner 独立保活，无连续拷贝
- [x] value_as_double 委派段 BufferView（复用 bounds/capacity/scalar 检查，无重复 switch）
- [x] 测试 5 用例（单段等价/两段跨边界/owner 保活/OOB/异构拒绝）
- [x] 两轴 /code-review：Standards 0 hard（2 judgement call follow 先例）、Spec 0 发现——无需修复 commit
- **Status:** complete（commit `c5c9e81`），35/35 green。frontier 现 #197

### Phase W7: #198 AppendBatchCommand（原子曲线尾追加，ADR 0031）

`/implement` #198（#162 链 frontier）。expand（坐标 BufferView→CurveBuffer）+ AppendBatchCommand 实现，两 commit + 两轴 `/code-review`。固定点 `43a0790`。

#### W7.1: Expand — SamplingAxis.coordinates BufferView → CurveBuffer
- [x] header 类型扩；隐式 `CurveBuffer(BufferView)` 构造使 84+ `SamplingAxis{...}` 字面量不变
- [x] BufferView-specific 站点迁移：manifest write 拒复合 + `as_single()`、curve_lod `validate_curve_buffer`、session `axis_is_ordered`（复合分支 `value_as_double`，单块类型精确模板保留整数精度）、4 个 selection row/range mapper 改 `CurveBuffer`、curve_lod_test `as_single()`
- [x] 整数精度回归修复（`session_compares_integer_sampling_axes_without_precision_loss` 重新通过——单块路径保留类型精确 memcpy 比较）
- **Status:** complete（合入 commit `1873a3b`）

#### W7.2: AppendBatchCommand 实现 + 测试
- [x] `CurveTailBlock`/`AppendBatchCommand` 类型（session.hpp）；`execute(AppendBatchCommand)`（session.cpp）
- [x] 整批校验先行（曲线/轴存在、方向、长度、owner、尾连续性、scalar 匹配）→ 任一失败返错且不动状态（原子，无半批）
- [x] 无拷贝组合：`existing_segments` + `CompositeBufferView::from_segments`（旧段 SharedOwner 原地保活）
- [x] 单调 revision 门（`target_revision > current`，否则拒）；乱序/历史回补拒为 Append
- [x] 委托 `SetDocumentCommand` 提交（复用 validate/LOD/selection 重映射/事件）
- [x] 测试 10 用例（成功端到端跨段读、no-copy 旧块地址保活、整批失败不变、乱序拒、回补拒、非单调 revision 拒、链式重复追加、缺文档/缺曲线/缺轴 distinct 码）
- **Status:** complete（commit `1873a3b`）

#### W7.3: 两轴 /code-review 修复
- [x] Spec 6/6 PASS 0 发现；Standards 1 hard：`append_curve_missing` 返 `missing_sampling_axis` 码却用于缺曲线（Mysterious Name + Result/Error 契约不符）→ 拆 `append_curve_missing`(`invalid_document`) + `append_axis_missing`(`missing_sampling_axis`) + 2 测试锁定 distinct 码
- [x] Standards judgement 应用：staging map `count()+at()` 双查改 `find()` 单查无拷贝
- [x] judgement 保留（行内文档）：重复 double 单调遍历（两路径载荷不同）、`version_conflict` 复用 `invalid_document`（无 enum 项，跨模块改动延后）
- **Status:** complete（commit `dacf025`），36/36 green。frontier 现 #199

### Phase W8: #199 增量 LOD 尾扩展（append 不全量重建，ADR 0031）

`/implement` #199（#162 链）。extend_tail + session 接线，两 commit + 两轴 `/code-review`。固定点 `dacf025`。

#### W8.1: CurveLodPyramid::extend_tail + 共享 build_run_levels
- [x] 提取 `build_run_levels`（per-run 层级派生）供 build 与 extend_tail 复用（结构性 parity 基础）
- [x] `extend_tail`：重用除最后 run 外全部 SourceRun；从最后 run begin 到扩展末端两遍扫描（先发现 run 边界预充 SourceRun 开销，再派生），envelope + derived_bytes + level_count + budget_limited 逐字节等于全量 build
- [x] 前置：id 匹配、扩展更长、前缀数值相等（append 非编辑）、algorithm/base_bucket/budget 全匹配（否则拒 → 调方全量 build）
- **Status:** complete（合入 commit `cebc56a`）

#### W8.2: Session LOD worker 增量接线 + 测试
- [x] AppendBatchCommand 在前次 preparation ready 时暂存每曲线旧 pyramid 到 `pending_append_reuse` 提示
- [x] SetDocumentCommand LOD worker 读提示：每曲线先试 extend_tail，结构拒绝/无旧 pyramid 回退全量 build；未变曲线直接复用
- [x] 测试：incremental-lod（7 用例：parity/链式/编辑拒/非增长拒/null-gap/tight-budget parity/mismatched-budget 拒）+ append-incremental-session（2 用例：incremental 路径 ready / 无前次 ready 回退）
- **Status:** complete（commit `cebc56a`）

#### W8.3: 两轴 /code-review 修复
- [x] **两轴收敛同一根因**：parity 在 binding/auto-growing budget 下破裂（无测试覆盖）。3 hard 全修：derived-byte 预充分歧（两遍扫描预充）、默认预算复用（改预算不一致即拒）、`pending_append_reuse` 同步路径泄漏（消费提到分支前）
- [x] 新增 2 测试（tight-budget parity 锁定预充修复、mismatched-budget 拒锁定预算前置）；既有改用显式常量预算
- [x] judgement 应用：J4 注释对齐代码；保留 J2/J1/J3（行内文档）
- **Status:** complete（commit `196a72d`），38/38 green。frontier 现 #200

### Phase W9: #200 Append 视口策略（Fixed vs Follow-Latest，ADR 0031）

`/implement` #200（#162 链）。AppendViewportMode + 每文档 session 状态 + AppendBatchCommand 捕获/恢复，两 commit + 两轴 `/code-review`。固定点 `196a72d`。

#### W9.1: AppendViewportMode + session/view 访问器 + append 捕获恢复
- [x] `AppendViewportMode`（fixed | follow_latest）；Impl 每文档 map；`append_viewport_mode`/`set_append_viewport_mode` session 访问器；`WellLogView::set_append_viewport_mode`/`append_viewport_mode` view 转发
- [x] AppendBatchCommand 在委托 `SetDocumentCommand`（清 viewport/presentation/defaults）前捕获 viewport/pixel_height/presentation/viewport_default + mode，委托后按 mode 恢复：Fixed→原窗口；Follow-Latest→底/顶推进到尾最新深度保 span；恢复 presentation+default 使 LOD-完成帧任务按所选 viewport 重建 scene；发布 viewport_changed
- [x] 测试 6 用例（Fixed 保持、Follow-Latest 递增推进、mode 可观测默认 fixed、Follow-Latest 发事件、无前次 viewport 保持清除、Follow-Latest 递减轴推进）
- **Status:** complete（commit `e90ff34`）

#### W9.2: 两轴 /code-review 修复
- [x] **两轴收敛同一 hard**：Follow-Latest 方向无关，递减轴错误（DepthViewport 恒 top<bottom，但尾最新样点递增轴最深/递减轴最浅）。按 `axis.direction` 分支修复 + 新增递减轴测试（qsp §2.1 强制）
- [x] judgement 应用：J1 补 `events.reserve(size+1)`（同文件其余单事件发布先例）
- [x] 保留（文档化）：直接 map 重插（follow #199 先例）、front() 多轴主轴、view setter 无 doc no-op
- **Status:** complete（commit `3348646`），39/39 green。frontier 现 #201

### Phase W10: #201 高频 append 合并 + 压力（#162 收尾，ADR 0031）

`/implement` #201（#162 链最后一块）。合并 + 压力覆盖，两 commit + 两轴 `/code-review`。固定点 `3348646`。

#### W10.1: 高频合并（configurable refresh cap）+ 压力覆盖
- [x] `PerformanceBudgets.append_refresh_rate_hz`（默认 0=禁用/立即，向后兼容；host 流式设 10）；execute 合并门（暂存→flush）；`commit_append_batch` 提取；`flush_append_coalesce`；poll_async flush 过期合并器
- [x] 压力覆盖 7 用例：合并封顶+flush、禁用立即、**poll_async flush 过期**、external owner 保活（weak_ptr+地址）、append-LOD 取消（cancelled_tasks>=1）、selection 跨 append 存活、单线程快速 append+poll 压力
- **Status:** complete（commit `5e743a8`）

#### W10.2: 两轴 /code-review 修复
- [x] **headline hard**：合并批次校验失败静默丢弃 + `.value_or` 伪造成功 receipt（数据丢失不可见）→ `flush_append_coalesce` 改返 `Result<CommandReceipt>`（成功 receipt / 校验失败 Error / 无暂存成功 receipt），execute 去掉伪造直传 Result
- [x] hard 3：重复间隔数学 → 提取 `coalesce_interval(rate_hz)` helper（execute/poll_async 共用，1000Hz clamp 文档化）
- [x] hard 5：poll_async 合并器 flush 分支零覆盖 → 新增 `poll_async_flushes_overdue_coalescer`
- [x] spec 3：取消测试补 `cancelled_tasks >= 1` 断言（operation_cancelled 经计数器显现）
- [x] 保留（文档化）：ADR「默认十次」实现为引擎默认 0（向后兼容 + 库更安全）、invalidate-selection 分支 append 不可达、压力测试单线程（session 单线程契约）
- **Status:** complete（commit `4e3944e`），40/40 green。**#162 epic 全部 6 子工单完成**

#### #162 Epic 交付总结
原子分块追加实时曲线并可跟随最新深度，按 /to-tickets 拆为 6 子工单全部交付：
- #196 CompositeBufferView（append 基础，expand）→ #197 消费者迁移（contract）→ #198 AppendBatchCommand（原子尾追加 + 单调 revision 门）→ #199 增量 LOD 尾扩展（parity）→ #200 Append 视口策略（Fixed/Follow-Latest，方向感知）→ #201 高频合并 + 压力健壮性
- 旧数组不复制（CompositeBufferView 跨段无拷贝）、LOD 只增量更新受影响尾块（extend_tail parity）、同批整体可见/失败、乱序/回补转显式 Patch、视口可固定/跟随、高频 C++ 内合并（≤N 可见刷新/秒）—— ADR 0031 全部条款满足。

### Phase W11: #158 /to-tickets 拆解 + #202 DocumentPatch 基础（ADR 0025）

`/implement` #158（可撤销 Document Patch epic）。调研发现 ADR 0025 指定的 undoable patch + 内核 undo 栈 + 逐实体编辑全无。**走 /to-tickets 拆 5 子工单**（#202-#206），本会话实现 foundation #202。固定点 `4e3944e`。

#### W11.0: /to-tickets 拆解 + 发布
- [x] 拆 5 子工单（#202 foundation -> #203 undo/redo -> {#204 layout coverage, #205 interpretation coverage} -> #206 seam validation）；GitHub 发布，blocking 链 + #158 body 注释
- **Status:** complete

#### W11.1: #202 DocumentPatch + ApplyPatchCommand + PatchConflict
- [x] `PatchableEntity` variant（文档 Interval/Marker/Symbol/Annotation + 布局 Track/Scale/CurveLayer）；`UpsertEntity`/`RemoveEntity`/`EntityEdit`；`DocumentPatch{base_revision, edits}`；`ApplyPatchCommand`
- [x] execute：patch_conflict 门（base != current -> 新稳定码 `ErrorCode::patch_conflict`）；整批校验（nil id/重复 id/remove 须存在）；原子 apply（builder 重建，patched id 跳过拷贝->upsert 替换/remove 删）；委托 SetDocumentCommand 提交 + 恢复 patched presentation + 保留 viewport；selection 重映射
- [x] 测试 12 用例（upsert 替换/创建、remove 文档/布局、整批拒、重复 id、patch_conflict、selection 存活、空 noop、保 untouched 集合、无 presentation 时布局 upsert 拒）
- **Status:** complete（commit `ba458ce`）

#### W11.2: 两轴 /code-review 修复
- [x] **hard**：patch 不暂存 `pending_append_reuse` -> 仅编辑解释实体的 patch 仍全量重建每曲线 LOD（违 architecture §7 最小闭包）-> patch 委托前暂存旧 pyramid（曲线 immutable，原样复用）
- [x] judgement 应用：#6 remove-of-missing 消息键 `presentation_document_missing`（误导）-> `document_structure_invalid`
- [x] 新增 2 测试（保 untouched 集合、无 presentation 时布局 upsert 拒）
- [x] 保留（文档化）：capture/restore 与 append 重复（共享 commit helper 待重构）、repeated-switch variant 分发（static_assert 可加固）
- **Status:** complete（commit `b1d1090`），41/41 green。frontier 现 #203

#### #158 Epic 子工单状态
#202 ✅（foundation）-> #203 ✅（undo/redo 栈）-> {#204 layout coverage, #205 interpretation coverage}（next）-> #206 seam validation（blocked，closes #158）。ADR 0025 的 QC Mask/Derived Curve/cross-well/depth-transform 编辑非 #158 AC，延后。


### Phase W12: #203 内核 Undo/Redo stack（ADR 0025）

`/implement` #203。以 #202 的 `ApplyPatchCommand` 为基础，新增每 document 的历史记录、Undo/Redo commands、可观察 history 状态，并保持既有 `SetDocumentCommand` 的 revision / selection / LOD 失效路径。

#### W12.1: 调研与设计
- [x] 已读取 #203、#158、ADR 0025 与 #202 交接记录；固定点 `b1d1090`
- [x] 确认 patch / append 经 `SetDocumentCommand` 提交、revision 可由 snapshot 恢复、Selection 由替换路径 remap；history entry 以 document/presentation/selection 前后快照为权威，patch 另存逆向 edit 列表，append 用不可变 buffer snapshot 反转
- **Status:** complete

#### W12.2: 实现与测试
- [x] 每 document undo/redo 栈；UndoCommand / RedoCommand；can_undo / can_redo；history_changed event；empty direction 返回稳定 `history_empty` Error
- [x] patch 与可见 append 成功后进入 history；新成功 commit 清 redo；undo/redo 走 `SetDocumentCommand` 的失效路径并恢复 document / presentation / selection 的语义 snapshot
- [x] 新增 `welllog.undo-redo` headless integration coverage（3 patch round trip、patch/append redo clear、selection/revision semantic restore、observer coherence、history observability、append round trip）
- **Status:** complete（局部 build + `welllog.apply-patch` / `welllog.undo-redo` 2/2 green）

#### W12.3: 验证、两轴 review、提交与交接
- [x] 完整 build；headless CTest 42/42 green（排除既有 4 项 Qt/Python 环境依赖测试）
- [x] 以 `b1d1090` 为固定点执行 Standards + Spec 两轴 review：Spec 0；Standards 2 hard 修复（稳定 ErrorCode 枚举值、history restore 先于 observer notification）
- [x] commit `59fa229`（feature）+ `78aa746`（review fix）；GitHub #203 已关闭
- **Status:** complete

### Phase W13: #204 Presentation patch 的 prepared-scene 覆盖（ADR 0025）

`/implement` #204。固定点 `78aa746`。采用 TDD；公开测试 seam 为 `WellLogSession::execute(ApplyPatchCommand)` 与 prepared-scene 输出，绝不检视 session 内部 presentation map。已完成：Track z-order/width、Scale mode/range/direction/unit、CurveLayer style/visibility/remove-readd 的 headless 断言；新增无几何预检以保证失败补丁原子拒绝并保留 ready LOD cache。

#### W13.1: Red — 端到端 layout / scale / style / visibility 覆盖
- [x] 建立多 Track/Scale/CurveLayer fixture，并以 prepared-scene assertions 覆盖 z_order、width、scale mode/range/direction/unit、style、visible/remove-readd。
- [x] 实现 Track 的 z-order prepared-scene 排序，使 patch 后水平布局与渲染顺序一致。
- **Status:** complete

#### W13.2: Green — 单测、完整 headless suite 与两轴 /code-review
- [x] 目标测试、完整 C++ build、headless CTest 均通过（43/43，排除 4 项 Qt/Python 环境依赖测试）。
- [x] 以 `7fb4399` 为固定点执行 Standards + Spec 审查；修复原子预检、LOD 最小闭包与缓存来源校验。提交 `5eea446` + `ae72b05` 并关闭 #204。
- **Status:** complete

### Phase W14: #205 + #206 收口 #158（解释对象 patch + session seam）

- [x] #205 Interval/Marker/Annotation create/move/modify/delete via patch — `a4d2570`
- [x] #206 graphic/table/SVG/event seam validation — `541ac7b`（`session_seam_validation_test.cpp`）
- [x] GitHub: #202–#206 + epic #158 已关闭（2026-08-02 tracker hygiene）
- **Status:** complete — **#158 epic 完成**

### Phase W15: 源适配 LAS / DLIS / LIS79（#164–#166）

- [x] #164 LAS source adapter — `2435277`
- [x] #165 DLIS source adapter — `097287b`
- [x] #166 LIS79 source adapter + identity/normalization hardening — `b5ffb9f`…`aab9217`
- [x] GitHub: #164–#166 已关闭（2026-08-02 tracker hygiene）
- **Status:** complete。下一源适配 frontier：#167（716）

### Phase WL: 数据页井位平面预览 PRD #136（#133–#142）

Workbench + `geo-viz-engine` 双入口 Well Location Preview：全量 RenderableWellLocation、ActiveWell 点选/列表双向、固定倍率聚焦、SourceXY/SourceCRS 可信呈现、按资产会话状态恢复、50k 规模验收。

- [x] 领域词写入 `CONTEXT.md`（ActiveWell、WellLocationPreviewState、SourceXY/SourceCRS 等）
- [x] 深模块 `viz/hosts/well_location_preview.py` + 测试 `tests/test_well_location_preview.py`
- [x] `1060c3e` feat: complete well location preview workflow
- [x] `3c311b3` fix: keep well preview state and trust context current（缓存 CRS、旧版本状态回写、阻断错误重载、滚动恢复、EPSG 别名）
- [x] 引擎子模块 `geo-viz-engine@43178a04`
- [x] 验证：工作台相关 144 passed；引擎 DAT/编解码 59 passed；Wayland Qt 冒烟 passed
- [x] GitHub: #133–#142（含 PRD #136）已关闭（2026-08-02 tracker hygiene；#137 先前已关）
- **Status:** complete

### 同步关闭（tracker hygiene，代码此前已交付）

- [x] #154 虚拟化表格 + 图形↔表格选择联动
- [x] #155 XLSX / 版本化 XML / CSV 表格导出

### Phase W16: #167 Format716 Source Adapter（welllog-716-disk-v1）

- [x] `include/welllog/io/format716.hpp` + `src/io/format716.cpp`
- [x] Integration tests: table / SVG / CSV path on representative fixture
- [x] CMake: `welllog_io` + `welllog.format716-adapter`
- [x] Review: overflow-checked size math; curve/sample limits → `resource_exhausted`
- **Status:** complete

### Phase W17: #161 Marker 对齐多井 + Cross-Well Overlay（ADR 0013）

- [x] `DepthTransform` + validate / map / align helpers（scene API）
- [x] Prepare path: Reference→Display；cull markers/intervals/symbols/annotations in display space
- [x] Session: `SetDepthTransformCommand`, `AlignWellsToMarkersCommand`, `SetCrossWellOverlaysCommand`
- [x] `append_surface_overlay_geometry` + surface SVG entity-id overlays
- [x] Tests: `welllog.depth-transform-overlay` (+ multi-well regression)
- **Status:** complete

### Phase W18: #163 Arrow C Data / mmap / IPC 零拷贝（ADR 0027）

- [x] Optional `WellLog::Arrow` library (`WELLLOG_BUILD_ARROW`)
- [x] Vendored C Data ABI + `import_arrow_array` (zero-copy primitives, explicit convert policy)
- [x] `import_mmap_scalar_column` + SharedOwner unmap
- [x] Optional IPC via Arrow C++ (`import_arrow_ipc_file_column`)
- [x] Tests: `welllog.arrow-adapter` (null polarity, offset, LOD, session, budget)
- [x] Core boundary: no Arrow in public core headers
- **Status:** complete

### Phase W19: #170 迁移多井地层对比（Feature Flag dual-path）

- [x] `welllog_multi_well_adapter`：稳定 ID、datum shift、overlays、parity
- [x] Python `submit_multi_well_section` / `clear_multi_well_section`
- [x] WellLogView paints multi-well surface when layout active
- [x] StratigraphyCorrelationPage backend combo；Legacy 不删除
- [x] Tests: multi-well adapter + dual-path page
- **Status:** complete

### Phase W20: #168 Profiler Overlay + Chrome Trace（ADR 0043）

- [x] `FrameStatsAggregator` + `ChromeTraceRecorder` + overlay formatter
- [x] WellLogView paintGL phase timing; toggleable overlay; trace export
- [x] Tests: `welllog.observability`
- [x] Tracker: close #183/#184 (already shipped)
- **Status:** complete

### Phase W21: #171 Manifest/XML/ZIP/列式输入加固（ADR 0042）

- [x] `checked_math` + `container_security` (XML scan, ZIP inspect, buffer extent)
- [x] Manifest JSON size/nesting/array/object/string limits
- [x] ZipWriter path + entry size gates; Arrow mmap bounds
- [x] Tests: `welllog.container-security` + export regressions
- **Status:** complete

### Phase W22: #172 模糊测试图纹、字体、图像及二进制测井源（ADR 0042）

- [x] `asset_security`：URI 方案/脚本/Shader 拒绝；ImageSource / CustomLayer / Pattern 上限
- [x] Manifest `parse_source` 拒绝不安全 URI
- [x] 确定性 corpus + mutation harness（无 libFuzzer CI 依赖）
- [x] CTest：`welllog.fuzz-binary-sources`（DLIS/LIS/716）、`welllog.fuzz-assets`
- [x] 持久种子：`tests/fuzz/corpus/{binary,assets}/`；Error.arguments 空断言
- **Status:** complete

### Phase W23: #173 压力验证 Qt Context、Python GC 与异步取消恢复

- [x] Headless：`welllog.async-lrw-stress`（LRW、session 销毁、export cancel、table/SVG 无 GL）
- [x] Qt：`welllog.qt-context-lifecycle-stress`（create/hide/reparent/destroy、multi-view 隔离、Trace 开关）
- [x] Python：`welllog.python.qt-lifecycle-stress`（churn、worker-thread GC、GUI-thread 契约）
- [x] 文档：`tests/qt/README.md`（sanitizer / 3.12–3.13 复跑说明）
- **Status:** complete

### Phase W24: #174 一亿点发布门禁 + 默认启用 WellLogEngine

- [x] Workbench：`PALEO_USE_WELLLOG_ENGINE` 默认 ON；`0`/`legacy` 回退；Legacy 保留
- [x] `welllog.release-gate-scenario`：CI 多井 LOD/内存/GPU 计划；`WELLLOG_GATE_SCALE=full` → 20×10×500k=1e8
- [x] CTest label `release-gate` + `scripts/run_release_gate.sh`
- [x] 文档：`docs/release-gate.md`、`docs/sbom-and-licenses.md`
- **Status:** complete

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
| **[W7]** `SamplingAxis.coordinates` 扩为 `CurveBuffer`（而非仅曲线值） | ADR 0031「旧数组不复制」是普遍的；append 必须无拷贝扩展轴坐标，否则坐标被迫重建（拷贝）。镜像 #196/#197 expand-contract。 |
| **[W7]** 整数精度轴序检查走类型精确模板（单块），复合走 `value_as_double` | `session_compares_integer_sampling_axes_without_precision_loss` 要求 uint64 值 `2^53+1` vs `2^53` 区分；double 转换会掩盖。append 坐标是深度（浮点），复合边界走 double 可接受。 |
| **[W7]** append 委托 `SetDocumentCommand` 提交 | 复用 validate/LOD/selection 重映射/事件发布，避免复制 ~300 行失效逻辑；append 专有校验（单调门、尾连续性）在前置阶段完成 |
| **[W7]** `version_conflict` 复用 `invalid_document`（非新 enum） | `ErrorCode` 无 `version_conflict` 项；新增是跨模块改动。follow `selection_*` 先例复用最接近稳定码，行内文档说明 |
| **[W7]** 空批为 no-op 成功（当前 revision） | 规格未覆盖；成功不产新 revision/事件，避免无意义状态变更 |
| **[W8]** extend_tail 重用除最后 run 外全部 SourceRun，仅重派生末尾区 | 旧 run 样点范围未被 append 触及，level summary 不变；末尾 run 的 begin 重派生是规格允许的「join 边界 bucket」 |
| **[W8]** extend_tail 预算不一致即拒（非复用旧预算） | parity 仅在匹配预算下成立；auto-budget 随曲线增长会变，故拒绝强制全量 build。现实契约是 host/session 跨 append 用常量预算 |
| **[W8]** run-scan 两遍（先发现边界预充 SourceRun 开销，再派生） | 必须匹配 build 的 `run_count*sizeof` 预充，否则 extend_tail 见更大预算包络 → 发出 build 会截断的 level，破坏 parity（review hard 发现） |
| **[W8]** session 用 `pending_append_reuse` 提示暂存旧 pyramid（非重构 SetDocumentCommand） | 最小侵入接线；hint 在 async/sync 两路径消费，worker 先试 extend_tail 再回退 build，始终正确 |
| **[W9]** append 视口策略用捕获/恢复（委托前捕获 viewport/presentation/defaults，委托后按 mode 重插），非重构 SetDocumentCommand | 委托 SetDocumentCommand 复用 validate/LOD/selection 重映射；捕获恢复最小侵入且正确——委托的 LOD-完成路径按恢复 viewport 重建 scene。follow #199 pending_append_reuse 直接 map 操作先例 |
| **[W9]** Follow-Latest 按 `axis.direction` 分支（递增→bottom、递减→top） | DepthViewport 恒归一 top<bottom；尾最新样点递增轴最深/递减轴最浅。方向无关会递减轴产出低于数据范围的错误窗口（review hard） |
| **[W9]** 多轴文档用 `sampling_axes().front()` 作主轴 | 单轴单井是常见情况；front() 是 builder 插入序的首轴。注释 hedge 多轴限制 |
| **[W10]** 合并 `append_refresh_rate_hz` 引擎默认 0（非 ADR 字面「默认十次」） | 向后兼容 #198/#199/#200（测试留 0）；库不知调用方是否流式，0（立即）更安全。ADR「默认十次」是 host 流式应用默认，经 budget 旋钮设。文档化此解释 |
| **[W10]** 合并批次校验失败丢弃（atomic）但 Error 经 `Result` 返回（非静默） | 批次拒绝不重试原样（atomic）；但 host 须能检测被拒批次（非数据丢失）。`flush_append_coalesce` 返 `Result` 传播 Error（review hard 修复） |
| **[W10]** 压力测试单线程（非真并发线程） | session 单线程契约：execute+poll 须同（事件循环）线程。真并发线程测的是库不提供的契约。单线程快速 append+poll 交错是现实 host 模式 + 正确的压力测试 |
| **[W12]** HistoryEntry 同时保存语义快照与 patch inverse edits | snapshot 精确恢复 DocumentRevision、presentation、Selection，以及不可变 curve buffer 的 append；inverse edits 满足 #203 对 patch 反转记录的显式要求。 |
| **[W12]** Undo/redo 在 SetDocumentCommand 通知前暂存 semantic restore | 复用既有 revision / task cancellation 路径，同时确保 observers 不会看到已清除 presentation 或临时 remap 的 Selection；历史转换对 host 是原子的。 |

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
| **[W7]** `axis_is_ordered` 重写走 `value_as_double` 破坏整数精度测试 | 1 | 恢复类型精确模板（单块 memcpy 比较），仅复合分支走 `value_as_double` |
| **[W7]** 本沙箱 GCC 更严暴露多处潜伏 `-Werror`（manifest nodiscard / xlsx sheet_index / well_log_view switch / 测试 checksum 初始化）阻塞编译 | 各 1 | drive-by 修：`(void)field()`、删未用变量、补 switch case、补字段初始化（均潜伏 bug，非本会话引入） |
| **[W8]** extend_tail 测试用 auto-budget（默认 0）失败 | 1 | H2 修复后 auto-budget 随曲线增长变化 → extend_tail 正确拒绝；测试改用显式常量预算（现实契约） |
| **[W8]** extend_tail 在 binding/auto-growing budget 下 parity 破裂（review 两轴收敛发现） | 1 | 两处修复：derived-byte 预充分歧（两遍扫描预充 SourceRun）、默认预算复用（预算不一致即拒）；新增 tight-budget parity 测试锁定 |
| **[W8]** session append 测试异步帧管线 headless 下 scene 不稳定（state=ready 但 scene=null） | 1 | 不驱动脆弱的帧管线；测试改为断言 preparation 达 ready + 无 diagnostic（incremental 路径完成），parity 由单元测试权威证明 |
| **[W9]** 测试 SetViewportCommand 在无 presentation 时失败（首次 viewport 须由 SetPresentationCommand 建立） | 1 | fixture 先建 presentation（建立初始 viewport+pixel_height），再 SetViewportCommand 调整 |
| **[W9]** Follow-Latest 递减轴产出错误窗口（review 两轴收敛发现） | 1 | 方向无关数学改按 `axis.direction` 分支；新增递减轴测试锁定 |
| **[W10]** `flush_append_coalesce` 校验失败静默丢弃 + execute `.value_or` 伪造成功 receipt（review hard，数据丢失不可见） | 1 | `flush_append_coalesce` 改返 `Result<CommandReceipt>` 传播 Error；execute 去掉伪造直传 Result |
| **[W10]** poll_async 合并器 flush 分支零覆盖（review hard，headline 路径未测） | 1 | 新增 `poll_async_flushes_overdue_coalescer`（hz=5，间隔内合并，sleep 过间隔后 poll 推进 revision） |
| **[W12]** 全量 build 因新 `history_changed` 在 WellLogView 穷尽 switch 失败 | 1 | 将 history event 纳入 adapter refresh 分支；随后完整 build 通过。 |
| **[W12]** Standards review：插入 ErrorCode 改变既有 `diagnostic_warning` 数值 | 1 | 新 `history_empty` 改为追加；测试锁定 `patch_conflict` / `diagnostic_warning` 数值。 |
| **[W12]** Standards review：undo 暂态在 observer 通知后才恢复 | 1 | `execute_history` 暂存 semantic restore，SetDocumentCommand 在 event 前恢复并发布对应 presentation/selection 事件。 |
