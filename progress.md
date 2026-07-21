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
- **连井/地震 P4-B 地震切片交互性能加固**：新增 `SliceReadWorker`（自有 loader、最新优先队列、±2 邻域预取、generation 失效、失败可见化）；SeismicView 缓存未命中改异步（消除 GUI 线程 segyio 卡顿），`_pending_slice` 按轴字典修复 `_on_jump` 三面板不一致；renderer_3d 按轴平面更新；预览控件 80ms 防抖 + resize 缓存缩放 + NumPy 蓝-白-红色表（去 matplotlib）。终审修复 worker 失败路径与面板新鲜度门控。引擎 112+ 通过、workbench 全量 1174 通过（Commits: engine `53d36297..b4e24f23`，workbench `dec3c6a..0ec2906`）。
