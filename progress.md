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

