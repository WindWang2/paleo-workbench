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
