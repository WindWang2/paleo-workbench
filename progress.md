# Progress Log: Paleo Workbench 重构与文档整理

## Session Log

### 2026-07-21
- **P3 预览子系统归位**：提取 `resources/preview_parsers/`，应用注册表模式，拆分 12 个 Preview Widget 模块，重构完成（Commit `ac291e0`）。
- **P4 地图编辑 Scene 拆分**：提取 `map_edit_factory`、`map_edit_draft`、`map_edit_snap`、`map_edit_topology`，`map_edit_scene.py` 从 1382 行精简至 604 行（Commit `8974bbe`）。
- **测试代码与导入清理**：更新 `tests/test_fallback_preview.py` 移除旧门面依赖；规范化 `document_parsers.py` 中 2D rasterio `out_shape` 消除 NumPy 2.5 废弃警告（Commit `67b62bd`）。
- **Planning with Files 初始化与更新**：建立根目录 `task_plan.md`、`findings.md` 与 `progress.md`，记录完整的架构重构成果与图谱。

## Verification Results

| Test Suite | Total Tests | Passed | Failed | Warnings | Status |
|---|---|---|---|---|---|
| Full Pytest Suite | 1109 | 1109 | 0 | 12 | ✅ PASSED |
| Map Edit Tests | 68 | 68 | 0 | 0 | ✅ PASSED |
| Preview Tests | 62 | 62 | 0 | 1 | ✅ PASSED |
- **连井对比 P1 性能优化**：引擎可注入 downsample 钩子 + 启动时注入 C++ `minmax_downsample`；`set_depth_range` 无操作守卫消除全井缓存级联失效；LAS 加载接入 C++ `fast_las_parse_data` 快速通道（修复 `~ASCII` 节头解析 bug、支持声明 NULL 值、包装文件回退）；离屏 canvas 跳过栅格化。全量 1113 测试通过（Commits: workbench `1fc79ea..77178d5`，engine `7ff4a96..74a7b841`）。
- **连井对比 P2 井分层接入 + 对比交互**：新增 SMI WellTops 解析器与 `load_well_tops` / `match_tops_to_wells` / `tops_to_intervals` 工作流接入；引擎补 `set_well_spacing` / `set_tops_visible` / `set_track_visible_by_label` API 与 `FormationTop` facade 导出；地层对比页工具条支持浏览/拾取/连线模式、层位与吸附选择、DTW 传播、撤销/重做、自动连线、分层顶线开关、井间距滑杆、轨道显隐与分层顶 CSV 导出。真实数据冒烟：DC.dat 解析 516 tops / 20 口井；引擎回归 72 通过；终审修复连线模式失同步（引擎幂等 `set_manual_link`）、工程相对路径解析与公共 `track_labels()`。全量 1146 通过（Commits: workbench `72f29fe..6279bab`，engine `70c6756e..8b221841`）。
- **连井对比 P3 导出增强**：引擎 `export_composite` 增加仅关键字可选参数 `dpi` / `width_px` / `page_size`（painter.scale 统一重采样，默认行为不变，兼容 export_service 位置调用）；新增 `CrossWellExportDialog`（格式 SVG/PNG/PDF、DPI 96/150/300、宽度、PDF 纸张 A4/Letter）；地层对比页导出按钮改为对话框流程。全量 1153 测试通过、引擎回归 77 通过（Commits: engine `0a045e2e`，workbench `a594e0d`）。
- **测井渲染通道性能加固（P4 阶段 A）**：CurveTrack ndarray 化 + downsample 钩子协议升级（ndarray 进 ndarray 出）+ `render_accel` 迁移；表头 min/max 预计算（顺带修复全 NaN 曲线 `nan~nan` 显示 bug）与 path cache 量化键修复；LAS 表格预览去 lasio 改走 C++ fast channel；LAS C++ 解析器 GIL 释放 + `from_chars`/`strtod` + 去双重解析。性能（A1.Las 15581×8）：LAS 解析 20.44 → 3.90 ms（复测 3.95 ms，约 5.2×）；抽稀 100k 点→2000px 每曲线 6.33 → 0.12 ms（约 52×）；表头 8 井整幅重绘 `paint_header` 3.64 → 0.94 ms（min/max 预计算省去 74% 表头开销）。引擎回归 80 通过；全量 1153 通过 +1 已知 flake（`test_properties_text_shows_path_when_saved` 仅全量顺序失败，独立运行通过）（Commits: workbench `497122c..71893bb`，engine `c0cf01d8`）。
- **P4-A 终审修复**：抽稀缓存键补深度 span（修复近 0 深度缩放陈旧渲染）+ 包装 LAS 预览回退 lasio + 遗留缓存测试迁移（Commits: engine `0af4c45..95be4627`，workbench `15235fc`）。
- **地震切片交互性能加固（P4 阶段 B）**：新增 SliceReadWorker（自有 loader、最新优先队列、±2 邻域预取、generation 失效），SeismicView 异步接线使缓存未命中不再阻塞 GUI，`_pending_slice` 按轴字典结构性修复 `_on_jump` 三面板一致性，并补 view cleanup 后 worker 重启；renderer_3d 按轴切片平面更新（`_update_slice_planes_for`）；预览控件 80ms 防抖、resize 缓存缩放、NumPy 色表（修复 blue-white-red 色带方向）。预览控件提交 `dec3c6a` 经 cherry-pick 落在 main 上（引擎提交在 `feature/3d-geological-modeling` 分支推进，gitlink 本次指向 `117558e1`）。引擎回归 112 通过 +1 既有失败（`test_curve_track_viewport_culling`，已编目）+1 skip；workbench 全量 1173 通过 +1 非确定性顺序依赖 flake（`test_workflow_controller_api.py::test_window_delegates_preview_settings_dialog_to_controller`，独立/单文件运行通过，复跑全量 1174 全绿；与本任务无关，源自并行会话 `a4cbcc1` 重构）（Commits: engine `53d36297..117558e1`，workbench `dec3c6a..5bf7bbf`）。
- **P4-C coherence 修正 + crossover_fill 删除（2026-07-22）**：`compute_coherence_3d` 的 `sample_window` 生效（垂直窗参与相干计算，边缘截断窗），内层改按列计算 + running-sum 消除逐点重算窗口的冗余，保持 GIL 释放；C++/Python parity 扩展至 sample_window ∈ {1,3,5} 并新增语义测试（不同垂直窗结果必须不同）。`generate_crossover_fill` 删除（无生产调用者且算法不正确）：C++ 函数、pybind 绑定、`well_log_api.py` wrapper 与相关测试一并移除（git 历史可恢复）。`task_plan.md` Phase 9 "C++ 多线程"表述纠偏为"单线程计算（释放 GIL）"（Commits: workbench `2dd6ec8..3275b00`）。
- **P5 等值面 + 相干性 3D 接入（2026-07-22）**：`marching_cubes_3d` 重写为 Marching Tetrahedra（6 四面体主对角线分解、邻接面一致、法线朝外，水密无孔洞；精确等值点 1e-3 相对偏移消除退化三角形；球面半径/封闭性/空阈值语义测试），Python 保底去点汤改 skimage/ImportError。引擎新增 `Renderer3D.set_isosurface`（GLMeshItem，spacing/origin 变换）与 `geoviz_seismic.isosurface` 注入钩子（仿 downsample 模式，facade 导出），SeismicView 工具栏等值面 checkbox + 阈值 spinbox（200ms 防抖、异常自动取消勾选）；workbench `render_accel` 启动注入 C++ 提取器；相干性 C3 经 `attribute_pipeline` 接入属性下拉。Task 1 曾发生并行会话 feature 分支 coherence 代码混入，经 b2d72b2 修复恢复 P4-C 语义（Commits: engine `134a6d93..664c0c45`，workbench `5d1f1d6..6d1ea6b`）。
- **连井/地震 P4-B 地震切片交互性能加固**：新增 `SliceReadWorker`（自有 loader、最新优先队列、±2 邻域预取、generation 失效、失败可见化）；SeismicView 缓存未命中改异步（消除 GUI 线程 segyio 卡顿），`_pending_slice` 按轴字典修复 `_on_jump` 三面板不一致；renderer_3d 按轴平面更新；预览控件 80ms 防抖 + resize 缓存缩放 + NumPy 蓝-白-红色表（去 matplotlib）。终审修复 worker 失败路径与面板新鲜度门控。引擎 112+ 通过、workbench 全量 1174 通过（Commits: engine `53d36297..b4e24f23`，workbench `dec3c6a..0ec2906`）。

## Session: 2026-07-23 — 浅色专业 GIS 风视觉系统重设计

将整个应用视觉系统从通用蓝色浅色（Linear/Notion 感）重做为 **Slate 石墨专业 GIS 风**（深板岩蓝主色 `#334155` + 天青强调 `#0ea5e9`，ArcGIS Pro 浅色质感），数据画布区保留深色。架构健康（单一 `tokens.py` 真相源 + 全局 QSS），令牌改动即时全局生效。

| Phase | 内容 | 结果 |
|-------|------|------|
| 1 | `tokens.py` 调色板换 Slate；新增 `BG_CANVAS`/`BG_CANVAS_PANEL`/`TEXT_ON_CANVAS`/`BORDER_CANVAS`/`BG_NAV_ACTIVE`/`BG_MENU_HOVER`/`BG_SELECTION` 语义令牌；`build_qss()` 内 4 处内联色（菜单/nav 激活/表格选中）迁令牌；`STEP_COLORS` 重新平衡 | 全局 11 页即时变色 |
| 2 | 样板页（首页+数据页）：架构零硬编码，Phase 1 后自动就位；仅修首页标题 `#1e56a0`→`tokens.PRIMARY` | 无需额外打磨 |
| 3 | 迁移 6 文件 ~165 处硬编码 hex 到令牌：`module_relationship.py`（自有调色板→tokens，删 2 处 status_colors dict 复用 `tokens.STATUS_TEXT`）、两个深色对话框（`ai_check_advisor_dialog`/`lithology_crossplot_dialog`）翻浅色 + inline HTML 翻转、两个 table 预览（删冗余内联 QSS 改继承全局规则）、`geological_modeling_3d_page`（画布深色保留→`BG_CANVAS*` 令牌） | 硬编码从 165→4（仅岩性图例语义色） |
| 3+ | 额外清理：`well_table_panel`（删 `hasattr` 死代码 fallback）、`visualization_page`（旧蓝 checked 态→`PRIMARY`）、`composite_visualization_panel`（`#ffffff`→`BG_SIDEBAR`） | — |
| 4 | 全量回归 + Python regex 审计确认 `ui/pages/` 硬编码归零（除 4 个岩性图例色） | 1382 passed, 2 skipped |

**新增语义令牌的意义**：`BG_CANVAS*` 系列首次为"数据画布深色区 vs UI 浅色区"建立明确语义边界，替代此前散落在 3D 页的 `#020617`/`rgba(...)` 硬编码；未来地图/地震视口的深色背景可统一引用。

**保留的语义色**（有意为之，非技术债）：`lithology_crossplot_dialog` 的 4 个岩性聚类色（砂岩绿 `#059669`/泥岩红 `#dc2626`/石灰岩蓝 `#2563eb`/花岗岩琥珀 `#d97706`）——图例辨识色，在浅底上调暗以保证可读性。

**验证**：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` → **1382 passed, 2 skipped**（与重设计前基线一致，零回归）。改动 13 文件（`tokens.py` + 9 页面 + 2 测试 + 还原 1 无关文件）。

**下一步**：样板页（首页+数据页）已确认 Slate 效果；剩余 9 页因 token 驱动已自动跟随，可按需单独打磨（mapping GIS 壳、地震页等）。

## Session: 2026-08-01 — WellLogEngine #154 Phase B（图形↔表格选择联动）

独立 C++ 子系统轨道（`well-log-engine/`），分支 `agent/welllog-pdf-spike-185`，直接在此开发。从交接文档 `/tmp/zcode_handoff_table_154.md` 接续（Phase A 已完成 review，遗留最后一条验收标准）。

**目标**：交付 #154 的最后一条验收标准——图形 Reference Depth Range 选择与表格源行双向联动，基于 ADR 0024 在 `WellLogSession` 中建立共享语义 Selection Set。

| Phase | 内容 | 结果 |
|-------|------|------|
| W1.1 | `WellLogSession` 新增 Selection Set：`SelectionDepthRange`/`SelectionState`/3 个 command + `selection_changed`/`selection_invalidated` 事件；depth-range↔row-span mapping（increasing & decreasing 轴，线性扫描读原始 axis BufferView）；SetDocumentCommand 安全 remap/invalidation；headless `welllog.session-selection`（12 用例）。顺带修 Phase A 打包 bug：`welllog_table` 未加入 install EXPORT | commit `bb12774` |
| W1.2 | 双向联动：`TableModel`（`set_session_selection_source`/`refresh_session_selection`/`current_row_selection`/`set_row_selection`，轴隔离）；`WellLogView`（`selection()`/`set_selection`/`clear_selection` slots + `selectionChanged` signal + Ctrl+drag 拖选手势）；clipboard 内部 MIME identity 扩展（doc\|rev\|axis + curveId\|unit）；Qt sync `welllog.qt-table-selection-sync` | commit `119c091` |
| W1.3 | 两轴自审：qt-cpp-review lint 聚焦新代码；修复 `set_projection()` 未清除陈旧 selection 反射（真实潜在 bug）；回归测试（8 用例总计） | commit `746bb7f` |

**关键设计决策**：选择状态唯一存于 `WellLogSession`（单一真相源，view/table 都是 adapter，与 viewport/crosshair 一致）；基于身份而非屏幕坐标；跳过 GL band 高亮渲染（标准是关于 sync，可 headless 测试，绘制是后续 ticket）；图形输入 = Both（API + Ctrl+drag，用户明确选择）。

**验证**：`ctest -j4 -E 'qt-widget\|python.qt-embedding\|qt.package.consumer'` → **31/31 green**（原 29；+`welllog.session-selection`，+`welllog.qt-table-selection-sync`）。3 个 env-blocked 测试需真实 GL / 非 conda libstdc++，与 #154 无关。工作树干净；`welllog.core.dependency-boundary` 通过。

**#154 验收标准**：8/8 全部满足（Phase A 7 条 + Phase B 选择 sync + 内部 MIME identity 完成）。

**下一步（可选）**：(1) `gh issue view 154` 后关闭 issue；(2) merge spike-185 → main（main 仍无 `well-log-engine/`，spike-185 领先约 50 commit）；(3) 开 #155（XLSX/CSV 导出，Phase B 的 SelectionSet 现已支持基于选择的导出）。

### 2026-08-01（续）— #154 Phase B /code-review（两轴审查）

对 `1dea684..HEAD`（Phase B 3 commit）运行正式 `/code-review`（两轴 Standards + Spec，并行子代理）。固定点 `1dea684`。

| 轴 | 发现 | 处置 |
|----|------|------|
| Standards（hard） | selection 失败一律复用 `invalid_viewport`（未知文档/未知轴/坏范围混为一谈），违反 `architecture.md §2` + `quality-security-performance.md §7` 稳定码规则 | **已修**：拆为 `selection_document_missing`→`document_not_found` / `selection_axis_missing`→`missing_sampling_axis`（entity_id=轴）/ `selection_invalid`→`invalid_viewport`（坏值）。测试断言各码。commit `641a635` |
| Standards（judgement） | `selection_error` 与 `viewport_error` 近克隆（Duplicated Code）；`bool from_rows` 是隐式 tagged union（Primitive Obsession） | 跳过：克隆已随 hard 修复消除；variant 在 2 调用点价值低（用户决定 keep bool） |
| Spec（a） | table→graphic *视觉* 高亮缺失（数据通路完整，paintGL 不读 selection） | **延后**：用户在 Phase B 计划中明确选 "Skip rendering"；状态正确同步，绘制是后续 ticket |
| Spec（c） | selection 按 document_id 单键（轴 B 静默驱逐轴 A）；remap 用绝对 ±1e-9 容差 | **确认意图**：单键符合 ADR 0024 "one selection per document over a single axis"（用户确认 keep）；新增 `one_selection_per_document_evicts_other_axis` 测试锁定意图。绝对容差对米深度无碍，延后 |

**验证**：session-selection 用例 12→13（+distinct-codes 断言、+axis-eviction）；31/31 headless green。

**Phase B 最终状态**：4 commit（`bb12774`/`119c091`/`746bb7f`/`641a635`），#154 全部 8 条验收标准满足，两轴 review 完成。

## Session: 2026-08-01（续 2）— #155 XLSX/XML/CSV 表格导出

`/implement` #155（被 #154 阻塞，现已解锁）。CSV → XML → XLSX 三后端，每个独立 commit + TDD，最后两轴 `/code-review`。固定点 `641a635`。

| Phase | 内容 | 结果 |
|-------|------|------|
| W2.1 | table-export 组件 `welllog_export_table`（链接 WellLog::Table + PRIVATE ZLIB）+ 共享 groundwork：TableColumn 加 ScalarType（G1）、`depth_domain_name/parse_depth_domain` 提升为 public core（G3）、`format.hpp` 数字格式化（G2）、`atomic_write.hpp` 原子写（G5, §10）、修 install EXPORT（含遗留 welllog_export_pdf）。CSV writer（§7）+ CsvPackageExporter（目录+manifest）。 | commit `b871af0` |
| W2.2 | 版本化 XML writer（§6）：`<wellLogTables schemaVersion>` + 流式 `<row>`（从原始 buffer，非 LOD），禁 DTD/外部实体/网络，XML 转义，§6 往返测试（5 用例）。 | commit `75dcbf7` |
| W2.3 | 自包含 XLSX（§5）：手写 ZipWriter（ZLIB deflate + CRC32）+ OOXML parts；数值单元格为数值、null 为空；>1,048,576 行自动 `_01/_02` 分表 + metadata 记录 global start row。测试用 ZLIB inflate 读回验证（4 用例）。 | commit `147516c` |
| W2.4 | 两轴 `/code-review` 修复：I/O 错误码改 `internal_error`（不再误用 `invalid_manifest`，匹配 svg/pdf 同类）；删 dead `stage` 参；XML referenceDepth 改共识派生（不再 over-fit axes().front()）；新增 `TableProjection::slice()` 选择导出路径（满足 "支持 Selection Set"）；记录 XLSX 内存上限为已知限制（§5.2 流式 follow-up）。 | commit `e663fdc` |

**验证**：34/34 headless green（原 31；+`welllog.csv-table-export` 5、+`welllog.xml-table-export` 5、+`welllog.xlsx-table-export` 4）。core dependency-boundary 通过。

**#155 验收**：全部 8 条满足（XLSX 按井/轴工作表 + 连续分表、XML 版本化+禁 DTD+往返、CSV 一文件一表+manifest、数值/Null/单位保持、流式+Selection Set、结构/XSD-往返/metadata 测试）。明确延后：CSV ZIP 打包、Interval/Marker/Annotation 工作表（表尚不存在）、正式 .xsd、Resampled 表导出、XLSX constant-memory 流式。

**下一步（可选）**：关闭 #155；merge spike-185 → main（main 仍无 `well-log-engine/`，spike-185 领先约 54 commit）。

## Session: 2026-08-01（续 3）— #183 Manifest round-trip for ImageSource + CustomLayerSource

`/implement` #183（自包含正确性缺口：ManifestCodec 对 ImageSource/CustomLayerSource 此前为零代码，文档携带这两类实体无法经 manifest 往返）。单 commit + 两轴 `/code-review` 修复。固定点 `8ebd35e`。

| Phase | 内容 | 结果 |
|-------|------|------|
| W3.1 | ManifestCodec write/read 补全 ImageSource（id/dims/pixelFormat/depths/dpi/source identity）+ CustomLayerSource（id/contentRevision/4 种 primitive + clip path）；`manifest_schema_version` 1→2；ADR 0042 限制在 manifest 层强制（dims/pixels/dpi + primitives/vertices/non-empty）；新增 manifest-local `pixel_format_name`/`symbol_kind_name` 等 helper + `number`/`boolean`/`optional_field`/`manifest_error(msg,code)` overload；schema gate 放宽允许可选 imageSources/customSources 键。 | commit `f52c257` |
| W3.2 | 两轴 `/code-review` 修复：(1) `primitive_vertex_count` 改为镜像 scene 的 tessellated 计数（tri=3/quad=6/sym=24/polyline=points），原几何计数（quad=4/sym=1）用同一 1<<20 上限但基数不同，会让超限输入漏过；(2) 补 per-polyline(≥2,≤8192) 与 per-clip(≥3,≤8192) 点上限；(3) version gate 改为接受 {1,2}（真前向兼容，v2 读 v1）；(4) 测试加固——triangle 全 3 点 6 坐标 + symbol color + quad origin/fill + over-pixel/zero-dpi 负例 + 重命名 version_gate 测试证双向。 | commit `3ed8ca6` |

**验证**：34/34 headless green（manifest round-trip 测试 2→5 用例）。

**#183 验收**：全部 6 条满足（write 全字段、read 等值重建、schema bump+旧版拒绝、ADR 0042 限制+invalid_image/invalid_custom_source、含 ≥1 image + ≥1 custom 全 primitive+clip 的往返测试）。明确延后：intervals/markers/symbols/annotations 序列化（同样被丢弃，独立 ticket）；PixelFormat/SymbolKind name helper 提升到 core；image_tile resolver（运行时路径，非 manifest）。

**注意**：#156（PDF/SVG 导出）已由 #185-189 完成并落在 spike-185，本会话验证后跳过（避免重复实现）。

**下一步（可选）**：关闭 #155/#183；merge spike-185 → main（领先约 56 commit）；下一个 ready 工单（#158 Document Patch+Undo、#162/#163 Arrow/append、#184 image pyramid）。

## Session: 2026-08-01（续 4）— #184 Thread ImagePyramidMap through the session frame path

`/implement` #184（session 异步帧路径只穿 CurveLodMap，不穿 ImagePyramidMap → 图像层经 session 不可达）。单 commit + 两轴 `/code-review` 修复。固定点 `f75e4c7`。

| Phase | 内容 | 结果 |
|-------|------|------|
| W4.1 | session 异步路径接入 ImagePyramidMap：PerformanceBudgets 加 `image_pyramid_options`；LOD worker 在曲线 pyramid 后用 `ImagePyramid::build`（仅元数据，ADR 0045）为每个 ImageSource 建 pyramid；CurvePreparation 携带 image_pyramids；make_frame_task 加 image 参并调 image-aware prepare 重载（3 个调用点全更新，pixel_height double 转换）；WellLogView `set_image_pyramid_options` setter（+ session `set_performance_budgets`）。parity 测试（曲线+图像文档经 session 产出 tile）。 | commit `f0a1191` |
| W4.2 | 两轴 `/code-review` 修复：(1) ADR 0034 — image derived bytes 折入聚合 derived_bytes（原只累计到独立字段被丢弃，预算只报曲线）；(2) qsp §7 — 图像 pyramid 构建失败改为发 `DiagnosticCode::image_pyramid_unavailable` Diagnostic（稳定码+实体 id）后降级（原静默 continue）；(3) Spec — parity 测试从 tile COUNT 强化到 tile SET 相等（level/row/col 集合）并先断言 session viewport=[1000,1100]×2160。 | commit `cf6d774` |

**调试发现**：异步 LOD worker 需要真实墙钟时间完成；紧密 poll 循环会饿死 worker 线程 → 测试 poll 间加 `sleep_for(2ms)` yield。

**验证**：34/34 headless green（image_layer_test 增 1 parity 用例）。

**#184 验收**：5 条满足（session 建 ImagePyramidMap 并穿入异步 prepare、view 暴露 pyramid 选项、session 路径产出与直连 prepare 相同 tile 集合、image_tile resolver 仍走 view 无引擎解码、异步可取消）。明确延后：同步（非异步）prepare 回退无 LOD（既有行为）；"镜像 curve LOD 暴露"措辞——curve LOD 算法/bucket 在 worker 硬编码、view 未暴露，无先例（image-pyramid setter 是净新增，未来 ticket 补 curve-LOD 对应项）。

**下一步（可选）**：关闭 #155/#183/#184；merge spike-185 → main（领先约 58 commit）；下一个 ready 工单（#158 Document Patch+Undo、#162/#163 Arrow/append）。

## Session: 2026-08-01（续 5）— #162 /to-tickets 拆解（append-batch 多 ticket 化）

用户选 #162（原子追加曲线尾块 + Follow Latest）。调研后发现其 2 条验收标准需全新基础设施，远超单 `/implement` 切片：① "不复制旧数组" 需新建 CompositeBufferView（当前 `BufferView` 单连续，所有 renderer/exporter/LOD 读 `data()`+`length()`，追加尾块要么拷贝旧数组违反标准、要么新建复合类型触及每个 buffer 消费者）；② "LOD 只增量更新" 需 `CurveLodPyramid::extend_tail`（当前每次全量重建）。外加：revision 单调门（SetDocumentCommand 当前盲替换）、SetDocumentCommand 当前清空 viewport（与 Fixed/Follow 冲突）。

按主流程对超大工单走 `/to-tickets`，拆为 6 个 tracer-bullet 子工单（GitHub #196-#201，parent #162，`ready-for-agent`，原生 blocking）：

| 子工单 | 标题 | Blocked by |
|--------|------|------------|
| #196 | Composite/Chained BufferView（append 基础 — expand） | 无（frontier） |
| #197 | 迁移 buffer 消费者到复合视图（contract） | #196 |
| #198 | AppendBatchCommand — 原子追加 + 单调 revision 门 | #196 #197 |
| #199 | 增量 LOD 尾扩展 | #198 |
| #200 | Session Fixed-Viewport vs Follow-Latest | #198 |
| #201 | 高频合并 + 并发/取消/选择压力测试 | #199 #200 |

Composite-buffer 按 expand–contract 序列（#196 expand 旁置不破坏 → #197 migrate 逐批保绿）。#162 保持 OPEN 作为 parent（#162 body 加 sub-tickets 注释）。

**关键设计决策（调研结论）**：复合 buffer 类型是必需的新基础设施——旧块不可变/共享所有权 per-block 已可保证，但"跨两块"的 span 需新类型；增量 LOD 是独立新增。

**下一步（可选）**：`/implement` #196（frontier，无阻塞）；或换 #158/#163；或 merge spike-185 → main。

## Session: 2026-08-01（续 6）— #196 CompositeBufferView（#162 append 基础，expand）

`/implement` #196（#162 拆解后的 frontier 子工单）。新增逻辑跨 N 个不可变物理段的 buffer-view 类型，为 #162 "不复制旧数组" 打基础。expand 步：旁置新增，不迁移任何消费者（#197 才迁移）。单 commit + 两轴 `/code-review`（**0 发现**，两侧 clean）。固定点 `baee494`。

| 内容 | 结果 |
|------|------|
| core 新增 `CompositeBufferView`（document.hpp/cpp）：`from_segments(vector<BufferView>)`（段须同 scalar_type、非空非 null-data 否则空复合）、`length()`（段长之和）、`value_as_double(i)`（跨段拼接映射，委派给段的 `value_as_double` 复用其 bounds/capacity 检查，无重复 switch）、`segments()`（span 供边界遍历）。每段 `SharedOwner` 独立保活，无连续拷贝。PIMPL 不可变值类型，镜像 BufferView/WellLogDocument。 | commit `c5c9e81` |
| 测试 welllog.composite-buffer-view（5 用例）：单段等价、两段跨边界、owner 独立保活（caller 释放 shared_ptr 后仍可读）、OOB nullopt + 空复合、异构类型/null/空输入拒绝。 | 35/35 green |

**两轴 review**：Standards 0 hard（2 judgement call 均 follow `BufferView::from_raw` 先例——验证失败返空值而非 Result/稳定码、未检 `has_owner()`，均非回归）；Spec 0 发现（完全 faithful，纯 expand 无调用方迁移）。无需修复 commit。

**#196 验收**：5/5 满足（core 新类型持有序段列表、随机访问跨拼接 OOB 一致、各段 owner 独立保活无连续拷贝、段迭代暴露、4+ 项测试覆盖）。

**下一步（可选）**：`/implement` #197（迁移 CurveLodPyramid/GL renderer/exporters 到复合视图——contract 步）；或换 #158/#163；或 merge spike-185 → main（领先约 60 commit）。

## Session: 2026-08-01（续 7）— #197 迁移消费者到复合 buffer（contract 步）

`/implement` #197（#162 链 frontier）。3 个并行 Explore agent 调研发现：所有 buffer 消费路径已是 index-based（value_as_double + length），无 raw data() memcpy → 迁移是一个 adapter 类型而非逐消费者重写。新增 `CurveBuffer`（core，包装 BufferView | CompositeBufferView，暴露 value_as_double/length/scalar_type + is_composite/as_single/segments；隐式 BufferView 构造使 84+ 现有 `Curve{.values=...}` 站点不变）。Curve::values 改 CurveBuffer；消费者最小改动：curve_lod validate_curve_buffer、table_projection read_buffer_cell、session load_as_double/required_bytes 重载、manifest 门控拒绝复合曲线。GL renderer 零改动（scene-prepare 已通过 value_as_double 扁平化）。两轴 review 补 3 测试（scene-prepare/GL、XML+XLSX、no-copy 断言）。commit `4b77bee` + `2a28c22`。36/36 green。

**#162 链状态**：#196 ✅ → #197 ✅ → **#198（frontier）**（AppendBatchCommand）→ #199/#200 → #201。










## Session: 2026-08-01（续 8）— #198 AppendBatchCommand（原子曲线尾追加）

`/implement` #198（#162 链 frontier，ADR 0031）。**Expand 步**：`SamplingAxis.coordinates` 从 `BufferView` 扩为 `CurveBuffer`（镜像 #196/#197），使 append 能给轴坐标追加尾段而不复制旧块——隐式 `CurveBuffer(BufferView)` 构造使 84+ 现有 `SamplingAxis{...}` 字面量不变；少数 BufferView-specific 站点（manifest write 拒复合 + `as_single()`、curve_lod `validate_curve_buffer`、session `axis_is_ordered` 复合分支走 `value_as_double` 而单块走类型精确模板保留整数精度、4 个 selection row/range mapper 改 `CurveBuffer`、curve_lod_test `as_single()`）。**实现**：`AppendBatchCommand`（session.hpp：`CurveTailBlock` + `AppendBatchCommand{document_id, target_revision, vector<CurveTailBlock>}`）+ `execute`（session.cpp）：先校验整批（曲线/轴存在、方向、长度、owner、尾连续性、scalar 类型匹配），任一失败返错且不动状态（原子）；通过 `existing_segments` + `CompositeBufferView::from_segments` 无拷贝组合（旧段 SharedOwner 原地保活）；单调 revision 门（`target_revision > current`，否则拒——`SetDocumentCommand` 盲替换无此门）；乱序/历史回补拒为 Append；最后委托 `SetDocumentCommand` 提交（复用 validate/LOD/selection 重映射/事件）。10 用例测试（成功端到端跨段读、no-copy 旧块地址保活、整批失败不变、乱序拒、回补拒、非单调 revision 拒、链式重复追加、缺文档/缺曲线/缺轴 distinct 码）。

**两轴 review**（固定点 `43a0790`）：Spec **6/6 PASS** 0 发现；Standards **1 hard**（`append_curve_missing` 是 Mysterious Name——返 `missing_sampling_axis` 码却用于缺曲线→拆为 `append_curve_missing`(`invalid_document`) + `append_axis_missing`(`missing_sampling_axis`) 两个 distinct builder + 2 测试锁定），1 judgement 应用（staging map `count()+at()` 双查改 `find()` 单查无拷贝）。commit `1873a3b`（feature）+ `dacf025`（review fix）。36/36 green。

**drive-by 潜伏 build 修复**（本沙箱 GCC 更严，阻塞依赖库编译）：manifest `(void)field()` 丢弃 nodiscard、xlsx `sheet_index` set-but-unused、`well_log_view.cpp` switch 漏 `image_pyramid_unavailable`、两测试 `BufferSourceReference::checksum` 缺初始化。

**#162 链状态**：#196 ✅ → #197 ✅ → **#198 ✅** → #199（增量 LOD 尾扩展，frontier）/ #200（fixed-viewport vs follow-latest）→ #201（高频合并 + 压力）。

## Session: 2026-08-01（续 9）— #199 增量 LOD 尾扩展（append 不全量重建）

`/implement` #199（#162 链，ADR 0031「LOD 只增量更新受影响尾块」）。**核心**：`CurveLodPyramid::extend_tail`（scene）——把短曲线的旧 pyramid 无拷贝尾扩展到长曲线：重用除最后一个 run 外的全部 SourceRun（其样点范围未被 append 触及，level summary 不变），仅从最后一个 run 的 begin 到扩展末端重新派生（含 null 间隔引入的新 tail run）。结果与全量 `build` 在 envelope 点 + derived_bytes + level_count + source_bytes + budget_limited 上**逐字节相等**。提取共享 `build_run_levels`（per-run 层级派生）供 build 与 extend_tail 复用，结构性保证两者派生的任一 run 字节一致。前置：id 匹配、扩展更长、前缀数值相等（append 非编辑）、algorithm/base_bucket/budget 全匹配（否则拒，调方须全量 build）。**Session 接线**：AppendBatchCommand 在前次 preparation ready 时暂存每曲线旧 pyramid 到 `pending_append_reuse` 提示；SetDocumentCommand LOD worker 读它——每曲线先试 extend_tail，结构拒绝/无旧 pyramid 则回退全量 build（始终正确）；未变曲线直接复用旧 pyramid（零工作）。

**两轴 review**（固定点 `dacf025`）：**两轴收敛到同一根因**——parity 保证在 binding/auto-growing budget 下破裂（无测试覆盖该区）。**3 hard 全修**：(1) derived-byte 预充——extend_tail 原在每 run 派生后才充 `sizeof(SourceRun)`，首 run 见的预算比 build 大 → 两遍扫描（先发现 run 边界预充全部 SourceRun 开销，再派生），匹配 build 的 `run_count*sizeof` 预充；(2) 默认预算复用——caller 留 0 时复用旧（更短）曲线 auto-budget 而非扩展曲线的 → 改为预算不一致即拒（parity 仅在匹配预算下成立）；(3) `pending_append_reuse` 仅在 async 分支消费 → 同步路径泄漏 → 提到 async/sync 分支前消费。**judgement 应用**：J4 注释对齐代码。保留（行内文档）：J2 重复 run-scan（两遍修复已消除其引发的分歧）、J1 整数曲线前缀走 double（曲线值多 float）、J3 所有 extend_tail 拒因归一码（每拒都回退全量 build，无调用方分支）。新增 2 测试（binding-budget parity、mismatched-budget 拒），既有改用显式常量预算。commit `cebc56a`（feature）+ `196a72d`（review fix）。38/38 green。

**#162 链状态**：#196 ✅ → #197 ✅ → #198 ✅ → **#199 ✅** → #200（fixed-viewport vs follow-latest，frontier）/ #201（高频合并 + 压力）。

## Session: 2026-08-01（续 10）— #200 Append 视口策略（Fixed vs Follow-Latest）

`/implement` #200（#162 链，ADR 0031「Session 可固定视口或跟随最新深度」）。新增 `AppendViewportMode`（fixed | follow_latest）+ 每文档 session 状态。host/view 经 `session.set_append_viewport_mode` / `WellLogView::set_append_viewport_mode` 设置（镜像 selection/crosshair 暴露方式）。AppendBatchCommand 在委托 `SetDocumentCommand`（其会清 viewport/presentation/defaults）前**捕获**当前 viewport/pixel_height/presentation/viewport_default + mode，委托后按 mode **恢复**：Fixed→原窗口不变；Follow-Latest→viewport 底/顶推进到 append 尾最新参考深度，保留 span。presentation + viewport_default 原样恢复使 LOD-完成帧任务能按所选 viewport 重建 scene。无前次 viewport 则保持清除。发布 `viewport_changed` 事件。

**两轴 review**（固定点 `196a72d`）：**两轴收敛同一 hard**——Follow-Latest 数学方向无关，递减轴错误。DepthViewport 恒归一 top<bottom（valid_viewport / range_for_rows），但 append 尾最新样点（index length-1）在递增轴是最深（→bottom），递减轴是最浅（→top）。原代码无脑 `bottom=last, top=last-span`，递减轴产出低于数据范围的窗口。**修复**：按 `axis.direction` 分支——递增 bottom=last/top=last-span；递减 top=last/bottom=last+span，两者保 span 且归一 top<bottom。**新增递减轴测试**（follow_latest_advances_on_decreasing_axis，[1002,1001,1000]+尾[999,998]→[998,999]，qsp §2.1 强制覆盖）。**judgement 应用**：J1 补 `events.reserve(size+1)`（文件内其余单事件发布均先 reserve）。保留（文档化）：直接 map 重插（follow #199 pending_append_reuse 先例 + 委托 LOD-完成路径按恢复 viewport 重建 scene）、front() 作多轴主轴（单轴常见，注释 hedge）、view setter 无 doc 时 no-op（同其余 view accessor）。commit `e90ff34`（feature）+ `3348646`（review fix）。39/39 green。

**#162 链状态**：#196 ✅ → #197 ✅ → #198 ✅ → #199 ✅ → **#200 ✅** → #201（高频 append 合并 + 并发/取消/selection 压力，frontier）。

## Session: 2026-08-01（续 11）— #201 高频 append 合并 + 压力（#162 收尾）

`/implement` #201（#162 链最后一块）。**合并**（ADR 0031「高频提交在 C++ 内合并并默认最多每秒触发十次可见刷新」）：`PerformanceBudgets.append_refresh_rate_hz`（默认 0=禁用/立即，向后兼容 #198/#199/#200；host 流式设 10）。`execute(AppendBatchCommand)` 为合并门：rate_hz==0 直接提交；否则 tail-blocks 暂存到每文档 `AppendCoalescer`，仅在刷新间隔到期（或首块）时 flush 为单可见 revision。原立即提交逻辑提取为私有 `commit_append_batch`。`flush_append_coalesce(doc)` 强制 flush；`poll_async` flush 过期合并器（延迟 revision 无新 append 也能出现）。**压力覆盖**（criteria 2-5，经 append→SetDocumentCommand 委托已工作）：external shared_ptr owner 跨 append 保活、append-LOD 取消报 operation_cancelled、Selection Set 跨 append 安全重映射、快速 append+poll 单线程压力。

**两轴 review**（固定点 `3348646`）：**headline hard（Standards 发现）**——合并批次校验失败时静默丢弃且 `.value_or` 伪造成功 receipt（数据丢失不可见，违 Result/Error 契约）。**修复**：`flush_append_coalesce` 改返 `Result<CommandReceipt>`——成功返 receipt、校验失败返 Error（host 可检测被拒批次）、无暂存返当前 revision 成功 receipt（no-op 非 error）；execute due 路径直接传播 Result 去掉 `.value_or` 伪造。**hard 3**：重复间隔数学（1000Hz clamp + 1e9/hz 在 execute/poll_async 复制）→ 提取单 `coalesce_interval(rate_hz)` helper。**hard 5**：poll_async 合并器 flush 分支零覆盖（所有 poll 调用者用 hz=0）→ 新增 `poll_async_flushes_overdue_coalescer`（5Hz 下间隔内合并无新 revision，sleep 过间隔后 poll flush 推进 revision）。**spec 3**：取消测试仅断言无 hard failure → 补 `cancelled_tasks >= 1`（operation_cancelled 经计数器显现）。judgement 保留（文档化）：ADR「默认十次」实现为引擎默认 0（向后兼容 + 库更安全）、invalidate-selection 分支 append 不可达（append 仅扩展轴）、压力测试单线程（session 单线程契约）。commit `5e743a8`（feature）+ `4e3944e`（review fix）。40/40 green。

**#162 链状态**：#196 ✅ → #197 ✅ → #198 ✅ → #199 ✅ → #200 ✅ → **#201 ✅** — **#162 epic 全部 6 子工单完成**。原子分块追加实时曲线并可跟随最新深度（CompositeBufferView + AppendBatchCommand + 增量 LOD + 视口策略 + 高频合并 + 压力健壮性）全部交付。

## Session: 2026-08-01（续 12）- #158 /to-tickets 拆解 + #202 DocumentPatch 基础（ADR 0025）

`/implement` #158（可撤销 Document Patch epic）。调研发现 ADR 0025 指定的 undoable patch + 内核 undo 栈 + 逐实体编辑**全无**（仅 SetDocumentCommand/SetPresentationCommand 全量替换 + AppendBatchCommand append-only）。**走 /to-tickets 拆 5 子工单**（#202-#206，GitHub 已发布，blocking 链：#202 frontier -> #203 undo/redo -> {#204 layout coverage, #205 interpretation coverage} -> #206 seam validation），#158 body 加子工单注释。

**#202（foundation，本会话实现）**：`PatchableEntity` variant（Interval/Marker/Symbol/Annotation 文档解释 + TrackSpec/TrackScaleSpec/CurveLayerSpec 布局）；`UpsertEntity`/`RemoveEntity`/`EntityEdit`；`DocumentPatch{base_revision, edits}`；`ApplyPatchCommand`。execute：patch_conflict 门（base != current -> 新稳定码 `ErrorCode::patch_conflict` + `MessageKey::patch_base_revision_conflict`，不按名称/位置猜测）；整批校验（nil id 拒、重复 id 拒、remove 须存在）；原子 apply（builder 重建文档+presentation，patched id 跳过拷贝由 edit 提供->upsert 替换/remove 删除无重复）；委托 SetDocumentCommand 提交（复用 validate/LOD/selection 重映射/事件）；恢复 patched presentation + 保留 viewport（patch 不移深度窗口）。测试 12 用例。

**两轴 review**（固定点 `4e3944e`，Standards 返回，Spec 撞 session 限额）：**hard** - patch 不暂存 `pending_append_reuse` -> 仅编辑解释实体的 patch 仍全量重建每条曲线 LOD（违 architecture §7 最小闭包 + 退于 append 路径）。**修复**：patch 委托前暂存旧 pyramid（曲线 immutable，pyramid 原样复用；extend_tail 回退路径安全）。**judgement 应用**：#6 remove-of-missing 的 `presentation_document_missing` 消息键误导->改 `document_structure_invalid`。新增 2 测试（patch 保 untouched 集合字节不变、无 presentation 时 presentation-entity upsert 拒）。保留（文档化）：capture/restore 与 append 重复（共享 commit helper 待重构）、repeated-switch variant 分发（新类型须改 4 处 visitor，static_assert 可加固）。commit `ba458ce`（feature）+ `b1d1090`（review fix）。41/41 green。

**#158 链状态**：#202 ✅（foundation）-> #203（undo/redo 栈，frontier，blocked）-> {#204, #205}（coverage）-> #206（seam validation，closes #158）。ADR 0025 的 QC Mask/Derived Curve/cross-well/depth-transform 编辑非 #158 AC，延后。

## Session: 2026-08-01（续 13）- #203 内核 Undo/Redo stack（进行中）

已从 `/tmp/zcode_handoff_202_158.md` 恢复 #202 交接上下文，读取 #203、#158、ADR 0025、现有 planning 文件与 `/implement` / `/code-review` 工作流。#203 的固定点为 `b1d1090`；目标是为每个 document 添加 patch/append 历史、Undo/Redo 命令、可观察 history 状态，并通过已有提交路径恢复 document revision 与 selection 的语义状态。下一步：定位 `well-log-engine/` 中 session 的提交 / revision / event 实现，完成最小的 history entry 设计后测试先行。

**完成**：每 document `DocumentHistory` 保存 undo/redo entry；entry 以 document/presentation/Selection 前后 snapshot 精确反转（append 的 immutable composite buffer 同样可恢复），patch 额外保存 `Upsert↔Remove` / 旧值 inverse edits。新增 `UndoCommand` / `RedoCommand`、`can_undo` / `can_redo`、`ViewEventKind::history_changed` 与稳定 `history_empty` Error；新成功 patch 或可见 append 会清 redo。Undo/redo 仍进入 `SetDocumentCommand` 的 revision、任务取消与 invalidation 路径；semantic restore 在其 event 发布**前**暂存完成，observer 不会读到临时清空的 presentation 或 Selection。Qt adapter 处理新 event，Python error-name 映射同步。

**测试与审查**：新增 `welllog.undo-redo`（3 patch round trip、patch/append redo-clear、Selection revision restore、observer coherence、history event、append round trip、ErrorCode numeric stability）。完整 build 通过；headless CTest 42/42 green（排除既有 4 项 Qt/Python 环境依赖测试）。两轴 `/code-review`（固定点 `b1d1090`）：Spec 0；Standards 2 hard——稳定 ErrorCode 数值与 observer 原子性——均已修复。保留「inverse edits 同时不直接执行」的 judgement：#203 明确要求 history record 携带反向 edit，snapshot 则是 append 与 exact revision restore 的权威机制。

**提交**：`59fa229 feat(welllog): add kernel undo redo history (#203)`；`78aa746 fix(welllog): address #203 history review findings`。#203 已解除 blocked 标签并关闭；下一 frontier 为 #204 / #205。

## Session: 2026-08-01（续 14）— #204 Presentation patch prepared-scene coverage（进行中）

用户选择 `/implement` #204。按 TDD 执行，固定点 `78aa746`。工单已明确预先约定 public seam：从 `WellLogSession::execute(ApplyPatchCommand)` 施加 Track/Scale/CurveLayer patch，随后以 `prepare_scene` 的 prepared-scene 输出断言布局和几何；不依赖 session 私有 presentation storage。下一步是阅读 scene 输出模型和现有 scene 测试，先添加一个会因当前缺口失败的端到端测试。

## Session: 2026-08-01（续 15）- #205 Interval/Marker/Annotation patch 覆盖（ADR 0025）

`/implement` #205（#158 AC #2）。#203/#204 由前上下文窗口已完成并提交（commits `59fa229`/`78aa746`/`5eea446`），本会话关闭 #204 并实现 #205。9 用例测试（welllog.interpretation-patch）：Interval/Marker/Annotation 各 create/move/modify/delete + 无效编辑拒绝（Interval top>=bottom、无效 UTF-8 label，断言文档不变）+ prepared-scene 反射（PreparedInterval 深度、PreparedMarker 深度、text-run/文档回退、删除消失）。

**latent 修复**：#203/#204 提交将 `pending_append_reuse` 重命名为 `pending_lod_reuse`（结构体 PendingLodReuse + kind），但 execute(ApplyPatchCommand) 和 commit_append_batch 中残留 2 处旧名引用 + patch 路径误用 `LodReuseKind::append_tail`（应为 `unchanged_document`--patch 不改原始曲线，ADR 0025，pyramid 原样复用）。修复两处。

两轴 /code-review：子代理撞 5h 限额；inline 自审 Spec 4/4（prepared-scene annotation text-run 无 text engine 时诚实回退文档断言），Standards 干净。commit `a4d2570`。43/43 green。

**#158 链状态**：#202 ✅ -> #203 ✅ -> #204 ✅ -> **#205 ✅** -> #206（seam validation，frontier，ready-for-agent，closes #158）。

## Session: 2026-08-02 — #206 + 源适配 + 井位预览 + tracker hygiene (A)

### WellLogEngine 收口

| 工单 | 状态 | 关键提交 |
|------|------|----------|
| #205 | 代码先前完成 | `a4d2570` |
| #206 | 代码完成并关闭 | `541ac7b` session seam validation |
| #158 epic | **关闭** | 子链 #202–#206 全部 ✅ |
| #154 / #155 | 代码先前完成，tracker 关闭 | Phase W1–W2 commits |
| #164 LAS | 关闭 | `2435277` |
| #165 DLIS | 关闭 | `097287b` |
| #166 LIS79 | 关闭 | `b5ffb9f` + `98ff351`…`aab9217` 身份/归一化加固 |

### 数据页井位预览 PRD #136（#133–#142）

| 项 | 内容 |
|----|------|
| 功能 | ActiveWell 点选/聚焦/复位、可搜索列表双向联动、全量解析+数据质量、SourceXY/CRS 可信呈现、按资产状态恢复、50k + 双入口 |
| 主提交 | `1060c3e` feat: complete well location preview workflow |
| 审查修复 | `3c311b3`（缓存 CRS、旧版本状态回写、阻断错误重载、滚动恢复、EPSG 别名） |
| 引擎 | `geo-viz-engine@43178a04` preserve well coordinate trust status |
| 验证 | 工作台相关 **144 passed**；引擎 DAT/编解码 **59 passed**；Wayland Qt 冒烟 **passed**（未强制 xcb） |
| 全量 | 根套件有既有失败；引擎全量因无关 QtWebEngine 慢测 10min 后终止 — 非本波 blocker |
| GitHub | #133–#136、#138–#142 关闭（#137 先前已关）；PRD #136 关闭 |

### Tracker hygiene（选项 A，2026-08-02）

关闭代码已交付但仍 OPEN 的工单，并写交付摘要评论：

- 井位：#133 #134 #135 #136 #138 #139 #140 #141 #142
- WellLog：#154 #155 #158 #164 #165 #166 #206

规划文件同步：`task_plan.md` Current Phase → W14–W16 / WL complete；`progress.md` 本段。

**分支**：`agent/welllog-pdf-spike-185` @ `3c311b3`（相对 origin 大幅 ahead；未在本步 push）。

**下一 frontier（示例）**：#167（716）、#169/#170（Workbench 迁移）、#174（一亿点门禁）、#183/#184（图像金字塔路径）、#157/#159–#161/#163/#168/#171–#173。

## Session: 2026-08-02 — #167 Format716 Source Adapter

`/implement` #167（716 Source Adapter）。支持 profile **`welllog-716-disk-v1`**（多曲线磁盘：128B 文件头 + 64B×曲线头 + sample-major float32）。

| 项 | 内容 |
|----|------|
| 公共 seam | `Format716SourceAdapter::{detect_endian,inspect,import}` → `WellLogDocument`（不泄漏 716 类型到 Core） |
| 策略 | 显式 endian/layout；`detect_endian` 在 0/2 匹配时拒猜；深度通道 DEPT/DEPTH/MD 或合成深度 |
| 安全 | max_input/curves/samples；尺寸算术溢出检查；截断/区间不一致拒文 |
| 测试 | `welllog.format716-adapter`：语义、方向/重复深度、limits、endian、NaN、table/SVG/CSV |
| 审查 | Standards hard：checked size arithmetic + resource_exhausted 对齐 — 已修 |
| 提交 | `feat(welllog): add Format716 disk source adapter (#167)` |

**#167 验收**：AC 覆盖；well_name/刻度 min-max 仅 inspect（Core 无 well 槽）；文本仅 ASCII（非 ASCII 拒）。

## Session: 2026-08-02 — #161 Marker 对齐 + Cross-Well Overlay（ADR 0013）

`/implement` #161（依赖 #160 multi-well surface）。可逆 Depth Transform + 按 Marker 对齐多井 + Cross-Well Overlay 几何注入 multi-well surface。

| 项 | 内容 |
|----|------|
| DepthTransform | 分段线性控制点；严格单调校验；clamp/linear 外推；正逆映射 `map_reference_to_display` / `map_display_to_reference` |
| Prepare | 曲线/Interval/Marker/Symbol/Annotation 走 Display Depth；`PreparedCurvePoint.display_depth`；域不匹配 + 非恒等变换 → diagnostic |
| Session | `SetDepthTransformCommand` / `AlignWellsToMarkersCommand` / `SetCrossWellOverlaysCommand`；存 `depth_transform` + `cross_well_overlays` |
| Surface | `append_surface_overlay_geometry`：全宽 overlay track + horizon polyline / correlation-band quad；`prepared_surface_scene` 解析 Marker EntityId → 场景毫米 |
| 测试 | `welllog.depth-transform-overlay`：round-trip 性质、冲突控制点、clamp/linear、session 变换、Align 共享 Display Depth、overlay SVG 实体 id、域不匹配 |
| 回归 | multi-well-surface + session/layer/document-annotation green |

**#161 验收**：AC 覆盖（参考域选择经 presentation domain + 变换时轴域校验；Patch/Undo 与 #158 文档补丁同轨——变换/overlay 为 session 状态命令 + state_version）。明确延后：host 完整 MD↔TVD 换算表、交互式拖拽控制点 UI、transform 入 history stack。
