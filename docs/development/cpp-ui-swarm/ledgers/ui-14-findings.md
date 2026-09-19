# UI-14 findings — root controllers（6 Python 源 → 7 核 + 6 壳）

Branch: `feat/cpp-ui-root-controllers`（base `origin/main`，合并至
`f0af9d4e` — 含 UI-08 mapedit / UI-09 wellseis / UI-10 seqviz /
UI-11 review / UI-12 workstation）。Worktree:
`../worktrees/cpp-ui-root-controllers`。切片 UI-14 of the M10
UI→C++ migration：六个根控制器 —— 选择总线 + 视图协调、地图动作
注册、数据目录生命周期、工程生命周期 + 三段式保存 worker、跨页
工作流编排。应用壳接线（app_shell 集成）不在本切片 —— 一律注入
seam，绝不伪造页面。

## Scope ledger（Python source → semantics → C++ target → 终态）

| Python source | Semantics | C++ target | 终态 |
|---|---|---|---|
| `view_coordination.py`（含 `viz/selection_context.py`） | `SelectionContext`：`update(**kwargs)` 只写显式字段（双 optional 哨兵）、`source_widget_id` 回声抑制、`publish_*` 便捷门、`clear()` 跨工程防串、订阅即发快照；`ViewCoordinationController`：井名↔id 索引、wells/seismic_surveys/time_depth 绑定入坐标 hub、`publish_*` 路由（well→dock/log/map 三槽）、seismic cursor → horizon 联动、**标定门控**深度光标（无时深标定 → 拒发，绝不猜速度）、dock 120 ms 节流回写 | `selection_bus`（`SelectionBus`/`SelectionPatch`/`SelectionState`）+ `view_coordination`（`ViewCoordinationCore` + `CoordinateHubApi` 抽象缝）+ Qt 壳 `QtSelectionContext`（`selection_changed(ctx)` 信号）/`ViewCoordinationController` | ported |
| `map_action_controller.py` | `_TOOL_IDS`（独占 QActionGroup 可勾选 MapTool）/`_COMMAND_IDS`（一次性命令）/`_SURFACE_EXTENSION_IDS`（V7 扩展，追加序即契约）；`ACTION_SPECS` 静态身份（label/group/icon/risk/shortcut/表面/原生标记）；`apply_availability` 只写呈现（enabled/tooltip=`label\n原因`/statusTip=`label（原因）`）；`toolbar` 组间分隔（多 id 组前插 sep，单 id 永不） | `map_actions`（Qt-free 词表 + spec + 呈现计划 + toolbar_plan，复用 `Pwb::ToolPolicy`/`Pwb::UiWorkstation` 注册表）+ `MapActionController`（QAction 物化、`tool_requested`/`command_requested` 信号、icon 解析） | ported |
| `project_save_worker.py` | `ProjectSaveTask` worker 簿记：`outcome_stats`/`outcome_error` 在终态回调**之前**写（drain 竞过排队投递仍可提交 — #1040 review-C1）；`run()` = progress→execute→记 stats→progress("committing")；`"{Type}: {message}"` 错误形 | `project_save`（`ProjectSaveApi` 三段式端口 + `ManagerProjectSaveApi` 适配 + `ProjectSaveTaskState` + `make_project_save_job_spec` + `may_commit_drained_save`）。`ProjectManager` 本体在 `libs/project` 加 `prepare_save`/`execute_save`/`commit_save` 三相（`save()` 保留为组合门脸）；`ensure_artifact_layout` 入 `paths.*` | ported |
| `project_controller.py` | `_end_current_session`（drain 保存→join 维护→#1126 composite 落盘→关壳 workers→**detached-keeper 闸 C18**→关 catalog→reset runtime，任一拒 → 会话保活 + 壳恢复）；开/新建/示例工程（v6 恢复决策表直通 `services.load_project`）；`save_project` 阻塞门脸 / `save_project_async`（GUI prepare→worker execute→GUI commit）；`save_as`（同写者 drain 闸、artifact 目录 staging 搬迁 + 失败回滚、catalog 重绑定、factor/interpretation 路径 rebase、维护调度代际闸）；`post_next_turn` 迁移投递 | `project_controller`（`ProjectControllerCore` + `ProjectHostApi`/`ProjectServiceApi` seam 袋）+ Qt 壳（QFileDialog/QMessageBox 绑定、JobOwnerRunner save 槽） | ported |
| `data_lifecycle_controller.py` | DataPage 面（document/selected/status/refresh/verify 闸）；catalog 桥（resource↔ref↔asset 三向）；移出=目录回收站优先 + legacy `resources[]` 行删 + `prune_asset_links` + V13 影响预览门（仅目录持有资产过闸）；trash/restore 伴随行；派生/纳管/新版本/提升（均 worker 化 `run_catalog_action`，失败→booked run 标失败）；tag 单写目录镜 + legacy 行镜像（目录失败留 `last_tag_mirror_failed` 可见）；delivery（prepare/copy+sha256/finish）；registration 500/块一批事务（批失败只丢本块）；integrity `verify_assets`（进度 hop 经 runner 完成回调，worker 回调不触 UI） | `data_lifecycle`（`DataLifecycleCore` + `CatalogServiceApi`/`CatalogRuntimeApi`/`DataPageApi`/`DataLifecycleServiceApi`/`LifecycleDialogApi` 缝）+ Qt 壳（stock 对话框绑定、catalog/verify 双 runner） | ported |
| `workflow_controller.py` | 预览设置对话框回路由当前壳；`request_recompute`（#834 全局代际抢占、`make_recompute_job_spec` worker 只碰快照、`on_recompute_completed` GUI 端提交 staged 任务 + 成对存网格、被超则按指纹清本 run 网格不逐新 — #881）；发送制备（`PrepareGenerationApi` + `FactorPrepareSeams` + `commit_prepare` 过期丢弃计数）；各 update_*_page 扇出；**发送编图**：演示显式路径（demo/mock 标记 → `compile_map_draft`）/ 生产可编（`prediction::is_map_compilable` → `compile_map_production`，ProductionMapError → 警告且不生成占位）/ 非空间科学结果 → **诚实阻断**（井深区间绝不自动变占位方块）；测井导入中继（路径归一 pending 集、data page 起导、完成选行）；`on_home_navigation` legacy 页索引 → (hub, submodule) 映射 | `workflow_controller`（`WorkflowCore` + `WorkflowPageApi`/`WorkflowDialogApi`/`WorkflowServiceApi`/`PrepareGenerationApi`/`LiveFactorGridApi`/`FactorRecomputeSeams` 缝 + `run_recompute`/`make_recompute_job_spec` 自由函数）+ Qt 壳（QMessageBox 绑定、`wire_*` 按 metaobject 信号名 string-connect + defer_page_binding 缝） | ported |

## 结构

`libs/ui_controllers/`（两 target，同 UI-09..12 先例）：

- **`pwb_ui_controllers`**（`Pwb::UiControllers`，STATIC，Qt-free）—
  7 TU：`selection_bus`、`view_coordination`、`map_actions`、
  `data_lifecycle`、`project_save`、`project_controller`、
  `workflow_controller`。PUBLIC 链 `Pwb::JobRuntime`/`Domain`/`Catalog`/
  `Project`/`UiDataCore`/`UiWorkers`/`UiShell`/`WorkflowRuntime`/
  `Prediction`/`ToolPolicy`/`UiWorkstation`。
- **`pwb_ui_controllers_qt`**（`Pwb::UiControllersQt`，AUTOMOC，需
  `Qt6::Widgets` + `Pwb::JobQt`）— 6 TU：`job_owner_runner`（UiJobRunner
  over `job::qtbridge::JobOwner`）、`map_action_controller`、
  `view_coordination_controller`、`project_controller`、
  `data_lifecycle_controller`、`workflow_controller`。

Seam 约定：所有 `std::function` 空值 = 「宿主无此面」（Python
`getattr(..., None)` parity —— 不崩不伪造）；seam 袋按值在构造/core()
物化时捕获；worker 回调只写 worker 侧簿记，UI 投递一律走
`UiJobRunner` 完成回调（owner 线程）。

## 服务 seam（不移植不伪造）

| seam | 服务域 | 承接方式 |
|---|---|---|
| `CoordinateHubApi` | `viz.coordinate_transform_hub`（viz_engine 未移植） | 抽象类端口；全部调用 try/except 非致命 parity |
| `CatalogServiceApi`/`CatalogRuntimeApi`/`CatalogPortApi` | `DataCatalogService`/`get_catalog*`/`catalog.lifecycle.*`/`domain_binding` | 函数袋逐点注入；未注入 → 诚实降级（registration → `last_registration_failures`） |
| `ProjectSaveApiFactory` | `ProjectManager(path)` 每保存一实例 | 默认 `ManagerProjectSaveApi`；测试注入 Fake |
| `WorkflowServiceApi` | `workflow.service`/`workflow.qc`/`pipeline.compile_map*`/`prepare_slice`/`commit_prepare` | 未注入 → 各调用点 Python try/except 语义降级 |
| `LifecycleDialogApi`/`WorkflowDialogApi`/`ProjectHostApi` 对话框 | QMessageBox/QFileDialog/影响预览/标签输入 | Qt 壳 `bind_dialogs` 绑定 stock 件；复合对话框留集成缝 |
| `UiJobRunner`（×5 槽） | save/recompute/prepare/catalog-copy/verify | `JobOwnerRunner`（生产）/`InlineJobRunner`（测试） |

## 构建说明

- `origin/main`（UI-08..12）已并入；根 `CMakeLists.txt` 解法：保留
  全部既有块，UI-14 块追加于 UI-10 之后、CONV-04 之前。
- **配置**：UI-14 门需 `Pwb::WorkflowRuntime`（CONV-26B）+
  `Pwb::Prediction`（CONV-21 链），均不在 linux-ninja 默认 flag
  内 —— 未开时按门设计诚实跳过（STATUS 提示，Python 控制器仍是
  生产路径）。本切片验证配置：

  ```bash
  cmake --preset linux-ninja -DPWB_BUILD_CONV_26B=ON -DPWB_BUILD_CONV_21=ON \
    -DPALEO_QGIS_SDK_DIR=.../output -DPALEO_QGIS_SOURCE_DIR=.../qgis \
    -DPALEO_QGIS_BUILD_DIR=.../qgis-vendor
  ninja -C build/presets/linux-ninja pwb_ui_controllers pwb_ui_controllers_qt \
    ui_controllers.core_smoke ui_controllers.qt_smoke
  ```

- QGIS SDK cache 覆盖同 UI-12 记录（兄弟 checkout 命名约定）。

## 验证

- `ui_controllers.core_smoke`（7 案例，Qt-free）：总线哨兵/清空、
  井索引+路由+标定门拒发、动作词表+呈现+toolbar 分隔、三段式
  job spec + drained-save 提交闸、工程 new/save-as/save-async
  prepare→execute→commit 序、remove/tag/register、recompute 提交 +
  非空间阻断 + demo 编译路径 —— **全过**。
- `ui_controllers.qt_smoke`（6 案例，offscreen）：QAction 物化/触发
  信号、QtSelectionContext↔core 路由、JobOwnerRunner 真实
  scheduler 完成投递（GUI 线程断言）、三个壳 lazy-core 物化、
  `wire_home_page` metaobject 连接 —— **全过**。
- 回归：`data.project_paths`/`project_roundtrip`/`project_recovery`、
  `job_runtime.lifecycle`/`cancel`、`job_qt.bridge` —— 全过
  （`libs/project` 三相改动未破既有契约）。
- `ctest -R ui_controllers` 2/2 通过。

## 修缺记录（构建期暴露）

| 位置 | 问题 | 修法 |
|---|---|---|
| `libs/project/src/manager.cpp` | `Result<T>` 无 `operator*`（`save()` 门面误用） | `.value()` |
| `src/data_lifecycle.cpp` 等 | `domain::StrongId`（AssetId/VersionId/RunId）↔ `std::string` 全线接口错位（目录模型强类型 id，控制器边界字符串） | 统一 `.str()` 越界转换（~25 处） |
| `include/.../selection_bus.hpp` | cursor/extent 状态结构体无 `operator==`，路由 diff 编译失败 | `= default` 三路相等 |
| `include/.../qt/{data_lifecycle,workflow}_controller.hpp` | 前置声明 `JobOwnerRunner` 但 inline 返回基类指针需完整类型 | 改 include `qt/job_owner_runner.hpp` |
| `src/qt/workflow_controller.cpp` `wire_signal_` | `SIGNAL()` 宏产 `"2name(sig)"` 前缀；`normalizedSignature` 不剥 → `indexOfSignal` 恒 -1，`wire_*` 全部静默不连 | 查信号名前剥 `0/1/2` 旗标字符 |
| `include/.../qt/workflow_controller.hpp` | `on_home_navigation` 为普通 public 方法，`SLOT()` 字符串连需声明槽 | 按既有模式补 `slotHomeNavigation(int)` 私有槽 |

## 已知缺口（留给集成切片）

- `CoordinateHubApi` 生产适配待 viz_engine 切片；目前 seam 未接 →
  绑定阶段每步 try/except 跳过（与 Python hub 缺失同语义）。
- `ProjectManager::prepare_save` 恒产 payload —— Python 段差分
  「clean → skip」优化未移植（C++ 侧无持久快照追踪；返回型已留
  Result/可空位，快照到达时免 API 变更）。
- `wire_data_visualization_jump` 的 `open_in_*` 负载为 typed ref，
  string-connect 不可达 —— 由集成适配器直调 `core()`（Python 同样
  走直接回调路径）。
- Qt 壳 `bind_dialogs` 只绑 stock 对话框；新版本/提升/回收站影响
  预览等复合对话框待 UI-13 composite 页切片按 seam 接入。
