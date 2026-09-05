# Baseline — 井–震–图一体化联动解释工作站（linked-interpretation-v5）

基线 commit：`049423ab`（= origin/main，2026-09-05）。
审计方式：主智能体直读核心链路 + 3 个只读调查 agent（well-log 侧 / seismic 侧 / catalog+多井+tie 侧）。

## 1. 联动链路现状（production graph）

```
Map/QGIS (project_well_map → WellMapPanel/MappingPage)
   ↕ well_selected / well_activated / select_well(emit=False)
SelectionContext (viz/selection_context.py:59)
   ↕ selection_changed（全量 state，source_widget_id 标记）
ViewCoordinationController (ui/view_coordination.py:42)   ← 唯一中介
   ↕ 差分路由（只路由变化字段，防 stale 重发）
CoordinateTransformHub (viz/coordinate_hub.py:183)
   ├─ TimeDepthCalibration（MD m ↔ TWT ms，分段线性，fail-closed）
   ├─ well registry（surface x/y、KB、TD、minimum-curvature 轨迹）
   └─ bin grid（origin/il_step/xl_step/il_min/xl_min，2×2 矩阵求逆）
Well 页（well_log_prediction_page + WellLogCanvasPanel，engine/legacy 双后端）
Seismic（SeismicViewPanel → geoviz SeismicView；cursor gate 30ms + 16ms Qt 去抖）
LinkedInterpretationWorkspace（ui/workstation/linked_workspace.py:69，seismic+well 两个 DocumentPane 的 dock 宿主）
```

## 2. 关键事实（file:line 以基线为准）

### 联动/协调
- SelectionContext slots：`active_well_id / selected_well_ids / depth_range / seismic_cursor / active_horizon_id / active_fault_id / active_interpretation_id / spatial_cursor / depth_cursor / active_layer_id / map_extent / source_widget_id / custom_attributes`（selection_context.py:36-49）。well key = 井名（#1029 约定）。
- 差分路由 + source-tag 防回声已存在（view_coordination.py:587-622）；seismic cursor 两级去抖（profile_vd.py 16ms + SeismicCursorGate 30ms，panel:29-64）。
- `publish_depth_cursor` 已 calibration-gated（view_coordination.py:521-556）；`_route_seismic_cursor` 的 well-MD 只作 approximate readout（custom_attributes 标记 approximate）。
- LinkedInterpretationWorkspace 的 depth cursor 只发状态文本（linked_workspace.py:276-279），未接 coordination。

### 坐标/域
- `TimeDepthCalibration.md_to_twt/twt_to_md`：范围外→None、无校准→None（coordinate_hub.py:61-83）。
- **缺陷 B1**：`seismic_to_map/map_to_seismic` 的 z↔TWT 用隐式默认速度 2000 m/s（coordinate_hub.py:471,494），非 fail-closed；`configure_seismic_grid(velocity=...)` 可换值但仍是"常速猜测"。
- **缺陷 B2**：`well_to_seismic`（:501）绕过 calibration gate 直连 map_to_seismic。
- 无 CRS、无单位元数据（全部隐式 m/ms）。
- `map_to_well_depth_all` 处理非单调轨迹多解（#1037 已修）。
- bind_project 从 role=time_depth 资产解析 TD 表注册校准（view_coordination.py:100-139）；SMI TD 表 `TIME TVDSS TVD MD` 列序（joint_well_parsers.py:83）。

### Well-log 视图
- 双后端：engine（Shiboken6 绑定 `welllog.WellLogView`）/ legacy（geoviz QPainter canvas）。env `PALEO_USE_WELLLOG_ENGINE` 默认 on（welllog_engine_adapter.py:144-153）。
- **缺陷 B3（L2 核心）**：`depth_cursor_supported()` 对 engine 硬编码 False（well_log_canvas_panel.py:189-197），engine 路径从未连接信号。绑定实际已有 `hover_info()`（含 display_depth/reference_depth，numpy_bridge.cpp:3811-3862）与无参信号 `crosshairChanged/hoverChanged/curveClicked/selectionChanged`（well_log_view.hpp:101-102）。
- C++ 已有但未暴露：`SetCrosshairCommand`（外部设 crosshair，session 层）、`set_selection(EntityId, SelectionDepthRange)`/`clear_selection`、`hover_pick()/click_pick()`、viewport 编程控制（Pan/Zoom）。绑定层 `clear_selection` 已在（无参形式）。
- legacy cursor 链路：`WellLogCanvas.mouse_moved(float)` → 120ms 门控 → depth_at_pixel 线性映射 → `depth_cursor_moved`（panel:269-287）。
- 绑定构建：CMake preset `dev-python`（Shiboken，CPython 3.12 声明但 abi3 .so 在 3.13 可用）；需 `LD_PRELOAD=/usr/lib/libstdc++.so.6`（系统 GCC 的 GLIBCXX_3.4.35，conda 自带库过旧）。主 worktree 现存 build 陈旧（缺 97984b8 的四个新入口）。
- 多井：`welllog_multi_well_adapter.adapt_multi_well_section` → `submit_multi_well_section`（纯数据提交，无交互接线）。C++ `pick_surface_curve` 支持多井面拾取。

### Seismic 2D/3D
- SeismicViewPanel = geoviz SeismicView 薄包装 + 解释 bar（开始解释/同步拾取/撤销/重做/保存版本/重开，panel:165-209）+ cursor 生产者。
- 已有显示控制：VD/Wiggle 模式、colormap（seismic/gray/jet）、clip percentile（50–99.9%）、3D opacity 预设、属性+RGB 融合。
- **缺口 B4**：无 polarity、无独立 gain；arbitrary line 只有 preview 体质量（chunked.read_arbitrary_line 高质量 API 无 UI 消费者）；无 depth slice；profile mode 隐藏 crossline/time/arb 三个副剖面（inline 单方向）。
- horizon picking 闭环完整：draft（NaN=未解释）+ SparseDeltaPatch undo/redo + fingerprint + no-op 检测 + 原子 npz artifact + catalog DERIVED+run + ProjectDocument ref + reopen 网格校验（interpretation_lifecycle.py:145-255）。
- 地震读取 ROI/window 语义：`SeismicVolumeSource`（LOD preview、共享字节预算、single-flight）；chunked `read_voxel_window`/`read_arbitrary_line`。
- `SeismicVolumeState`（事件驱动切片状态）存在但未接线（第二状态模型风险点，不动它）。

### 多井对比 / 层位顶
- 纯 Python 栈：`WellSectionDatum`（md/tvdss/horizon 对齐）→ `DTWLogMatcher`（z-归一、峰值保持降采样、Sakoe-Chinda）→ `FormationTopCorrelator`（相关多边形带 + 推荐）→ `StratigraphicCorrelationEngine`（fluent）。
- UI：`StratigraphyCorrelationPage`（app_shell 注册，DTW QThread worker，engine 双路径渲染）。
- FormationTop 版本化完整：`CorrelationScientificPayload` JSON artifact + DERIVED + no-op/branch-from-tip（correlation_lifecycle.py:102）。

### 井震标定
- 算法全在 `geoviz_well_tie` 包：Ricker/Ormsby、统计子波、合成记录、互相关 auto-tie、质量评估、sonic 单位归一、7 轨 canvas、PDF 报告。
- workbench 入口：3D 页 auto-tie、复合面板 WellTieHost（单井、地震道取体积中心）、地震预测页按钮。
- **缺口 B5**：tie 结果不落 Catalog、不生成 TimeDepthCalibration、不写 entity_asset_link(role=time_depth)，重开工程后 bind_project 拿不到标定成果；无 bulk shift 人工审查闭环；无 stretch/squeeze。

### 曲线解释
- `curve_interpretation.CURVE_OPERATIONS` 注册表：depth_shift/despike/baseline_shift → `create_derived`（每次新 asset、parent_version_ids 谱系）。
- **缺口 B6**：无 resample/smoothing/median/normalization/clip/unit-conversion/派生曲线计算器；LAS 头部 NULL/STRT 处理已有 `_ensure_writable_well_header`。

### Catalog
- 写路径双轨：`create_derived`（单步原子）与 Port 协议（begin_run → register_derived → complete_run，含失败补偿）。解释类推荐走 `catalog/lifecycle.py` 的领域封装（horizon/correlation 已有）。

## 3. 测试基线（现有、与本 Goal 相关）

workbench：test_view_coordination_seismic_producer / test_view_coordination_wiring / test_geological_context_scenarios / test_welllog_engine_adapter / test_welllog_engine_native_integration / test_well_log_canvas_panel / test_workstation_well_backend / test_seismic_profile_mode / test_horizon_picking_workflow / test_interpretation_lifecycle / test_curve_interpretation / test_stratigraphic_correlation_* / test_well_tie_host / test_joint_well_parsers。
well-log-engine：tests/python/test_qt_embedding.py、test_track_commands.py；tests/qt/well_log_view_test.cpp（hover/crosshair QSignalSpy、外部 SetCrosshairCommand、多井 hover）。

## 4. 环境契约

- python3.13（/opt/miniconda3），QT_QPA_PLATFORM=offscreen，LIBGL_ALWAYS_SOFTWARE=1，LD_PRELOAD="libxmlshim.so + /usr/lib/libstdc++.so.6"（绑定需要后者）。
- 本 worktree wrapper：`/home/kevin/projects/paleo_project/run_env_li.sh`（PYTHONPATH 含本 worktree 子模块 + well-log-engine/build/dev-python/python）。
- 编译并发 ≤2（CMAKE_BUILD_PARALLEL_LEVEL=2 / MAX_JOBS=2）。
- 绑定构建目录：well-log-engine/build/dev-python（preset dev-python）。
