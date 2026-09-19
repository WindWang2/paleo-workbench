# 26 — PR：well-log native host / UI / engine integration

- 分支：`feat/cpp-well-log-native-host`（base: origin/main @ ff67dcf3）
- Scope：Python 测井 host 面迁移首闭环（adapter/layout 语义全量、canvas 交互语义、load 单位/取消）；多井剖面与 prediction 页不在本切片。
- Python surfaces replaced/oracle：`welllog_engine_adapter.py`、`well_log_track_layout.py`（+fixture 生成器为 oracle 基础设施）；legacy：`well_log_host.py`、`well_log_canvas_panel.py`、`well_log_track_settings.py`；partial：`well_log_load.py`。
- C++ targets：`Pwb::VisualizationWellLog`（+3 Qt-free 模块、host 扩展）、`pwb-platform`（测井轨道面板 dock + 事件接线）。
- Tests：`science.viewer.well_log_plan`（12 案例 Python oracle 对账 + 负例自检 + layout/模板语义，Qt-free）、`science.viewer.well_log_native_host`（offscreen GL：DTO 加载/深度同步/选区/解释事件/游标/视口/导出/空井/重复深度/降序/NaN/取消/2M 样本/未知单位/模板往返/B1 回归）。
- Local verification：science ctest 9/9、platform ctest 40/40（offscreen + vendor QGIS runtime）、pwb-platform 全链接。
- Resource note：全程 `-j3`（`CMAKE_BUILD_PARALLEL_LEVEL=3` / `cmake --build --parallel 3`），单 worktree 单 build。
- Known limitations：多井剖面待迁（engine `SetWellLayoutCommand` 已具备）；`WellLogTrackPanel` 为薄胶水无单测；`python_repr_double` 与 factor_host canonical_json 待合并共享工具；load 同步在 UI 线程（v1，注释标注）；`PwbQgisSdk.cmake` 的 `external/nlohmann` include 缺口属 PR #1347（HY-4）范畴，本分支本地构建以 `CMAKE_CXX_FLAGS` 注入规避，未改共享 cmake。
- Parallel-branch interaction：与 #1346/#1348/#1349 零交集；与 #1347 仅 `apps/paleo_workbench_platform/CMakeLists.txt` 块内 +2 行。
- No-online-CI：Local verification completed; online CI is not required or awaited for this task.
