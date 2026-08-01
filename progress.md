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







