# QGIS 原生 Shell 收敛台账（Prompt 1：主显示框架方向）

- baseline：`192422c60c4eb99ee78a6a410676293ca09053cc`（origin/main，PR #1480 之后）
- worktree：`../paleo-qgis-shell`；分支：`feat/qgis-native-shell-convergence`
- 方向所有权：主显示框架、主窗口、dock/toolbar/menu/action/map-tool/status/message/UI state 管理
- 并行边界：不改 `libs/qgis` layer tree/layer lifecycle 核心（Prompt 2）、不改 catalog/project/data provider/storage 核心（Prompt 3）

## 0. 结论摘要

PR #1480 之后，地图会话主干（`MapSession` 拥有 `QgsProject + QgsMapCanvas + QgsLayerTreeView`，
编辑走 `QgsVectorLayer` undo stack，select/digitize 走 `QgsMapToolSelect`/`QgsMapToolDigitizeFeature`）
已经是 QGIS 原生结构，阶段切换与工程开合不再重建第二套地图状态。剩余债务集中在：

1. **已退役但仍在构造的兼容壳**（hidden `LayerManagerPanel`、未绑定的第二实例 `reference_layers_`、
   退役的 `MappingStageBar` 僵尸）；
2. **文件命令的三份 QAction identity**（AppShell 最小菜单 / ribbon 完整菜单 / 原生 文件 菜单）
   与 MRU 双菜单各自建 QAction；
3. **窗口布局双存储**（`WorkbenchLayout` 与 `platform_services::save_window_layout` 各存一份
   `QMainWindow::saveState` blob，靠手工删 key 调和）；
4. **一处 worker 线程裸 `this` 捕获**（`superviseAttributeRun`，#1429 crash 家族形态）；
5. **零产品消费者的自研 canvas/layer-tree/canvas 事件路由残留**（`NativeMapCanvas`、
   `NativeLayerTree`、`UnifiedMapCanvas` 工具面、`surface_state`、`OperationRegistryQt`）。

## 1. 重复架构清单（审计台账）

### 1.1 apps/paleo_workbench_platform

| 组件 | 位置 | 持有状态 | QGIS/Qt 原生替代 | 决策 |
|---|---|---|---|---|
| hidden `LayerManagerPanel` | `libs/ui_composite/src/layer_manager_panel.cpp`；由 `composite_document.cpp:90` 构造；`app_shell.cpp:257-272` 隐藏 | 自维护 `layers_` 快照副本（可见性/透明度/顺序）、`editing_layer_id_`、装饰、CRS；完整 `MapRenderSnapshot` 发布路径（产品中从未 bind，`layers_` 恒空） | `QgsLayerTreeView` + `QgsLayerTreeModel`（LayerTreePanel 已落地） | **已删除**（类文件+构造+三个 no-op `select_layer` 调用+死 connect；`adopt_layer_tree_dock` 相应简化） |
| `reference_layers_` 第二实例 | `app_shell.cpp:613-619`（"reference_maps" dock 工厂） | 同上类，从未 bind，可见但惰性 | 同上 | **已删除**（dock 落回诚实占位） |
| `MappingStageBar` 僵尸 | `libs/ui_composite/src/mapping_stage_bar.cpp`；`composite_document.cpp:94` 构造；`stage_flow_install.cpp:446-450` 注释声明退役 | 阶段段片 + 层位下拉 + last committed | ribbon 页签 + StatusBar 层位下拉 | **已删除**（连同 `test_three_stage_flow` 的僵尸断言；visualqa 场景宿主自带 Fake，不受影响） |
| 文件命令 QAction×3 | `app_shell.cpp:444-458`（孤儿菜单）；`main_window.cpp:1080-1128`（ribbon）；`main_window.cpp:1261-1287`（原生 文件） | 三份 QAction 集合 | 单一 QAction 集合挂多菜单 | **已收敛**：`buildFileActions()` 建一次成员 QAction，原生与 ribbon 两菜单共用；AppShell 孤儿菜单已删除 |
| MRU 双菜单 QAction | `main_window.cpp:2979-3014` `refreshRecentProjects` 分别 `fill` 两个菜单 | 每菜单每条目独立 QAction+connect | 同一 QAction 挂两个 QMenu | **已收敛**：每条目一个窗口拥有的 QAction，两菜单共享；`清除最近工程` 亦共享 |
| 窗口布局双存储 | `libs/ui/src/workbench_layout.cpp`（`layout/window_*` keys）；`libs/platform_services/src/settings_service.cpp:168,187`（第二份 saveState blob） | 两份 saveState/geometry，`main_window.cpp:4320-4334` 手工调和 | `QMainWindow::saveState` + 单一 QSettings 存储 | **已收敛**：CONV-27 build 唯一走 `WorkbenchLayout`；platform_services 读写降级为非 CONV-27 reduced build 回退；reset 不再需要跨存储删 key |
| `superviseAttributeRun` worker 捕获 `this` | `main_window.cpp:3489-3521` | worker 线程经 `this` 调 `context_.attributeRunner()`/`attributeOutcome()` | 数据捕获（`submitSegyJob` 模式） | **已修复**：按值捕获 AppContext 拥有的 runner 指针（窗口析构期间轮询仍安全） |
| `ToolActionSet` 无父 QAction | `libs/ui/src/tool_actions.cpp:21-24` | 自行 delete 的 QAction 表 | QAction 挂 parent | **已加固**：`apply()` 接受 host QObject，主窗口传入 `this`（销毁序随 QObject 树） |
| AppShell 内 static `SeismicVolumeService` | `app_shell.cpp:309-313` | 进程级服务状态藏进每窗口壳 | AppContext 拥有（`seismic_volume_service_` 同型） | **已迁移**：AppShell ctor 注入窗口拥有的服务指针（MW `seismic_volume_service_`，init_shell 先建）；无注入时页面保持诚实未绑定 |
| AppShell 早期 ribbon evaluator | `app_shell.cpp:472-478` | 无状态 lambda，但被 MW:1062 的 live-session 版本取代 | — | **已删除**（MW 版本为准） |
| 非 CONV-27 行号→图层映射 | `main_window.cpp:2725-2737` | 行号假设 | join-key 查找（LayerTreePanel 模式） | 保留（仅 reduced build 编译；原生产品走 CONV-27 join-key 路径） |

### 1.2 libs/ui_shell

| 组件 | 状态 | QGIS/Qt 原生替代 | 决策 |
|---|---|---|---|
| `CommandRegistry`（进程级单例） | id→closure、MRU、QSettings sink | QAction + QActionGroup | 保留（Ctrl+K palette 骨架），本方向不动其回调面；QAction 优先触发为后续项 |
| `CommandPalette` | 无自有状态 | — | 保留（唯一 Ctrl+K 面） |
| `StatusBar`（QFrame 五标签+层位下拉） | 工程名/探测/坐标等缓存 | `QStatusBar::addPermanentWidget` | 保留（产品状态面；层位下拉为 target_horizon 的视图/编辑器之一，无第二权威） |
| `MapStatusBar` | chips、collapsed 集、snap 匹配缓存 | QStatusBar permanent widgets | 保留 composite 实例（ToolContext 事实投影面） |
| `DockRegistry`（34 描述符） | 不可变数据 | — | 保留（dock identity 单一数据源） |
| `DockManager`（进程级） | preset + panel 词表 | `QMainWindow::saveState` | 保留（ui_map/ui_seqviz/ui_review 页消费；随页退役） |
| `FloatController`/`FloatingPanel`/`LayoutPersistence` | 浮动记录 + QSettings | `QDockWidget` floating | 保留（页内面；随 ui_map 退役） |
| `OperationRegistryQt` + `bind_registry_to_shell` | 无消费者（仅自身 smoke） | — | **已删除**（类/绑定函数/smoke 断言；`OperationRegistry` 核心与 `operation_registry()` 全局保留——stage_flow 有产品读路径） |
| `crs_guidance.hpp` | 无消费者（仅自身测试） | — | 保留（无状态工具头，删除收益为零、动测试成本高——复核后若零依赖再删） |
| `ShortcutRegistry` | spec + QShortcut 表 | QAction::shortcut | 保留（无键冲突审计元数据；ribbon 收起键经它） |

### 1.3 libs/ui_ribbon

| 组件 | 状态 | 决策 |
|---|---|---|
| `RibbonBar` | 契约明确"库不建 QAction"——命令按钮携带宿主注入的 governed QAction（`set_command_action`），未绑定时是诚实的普通按钮 | 保留（identity 已正确） |
| `ribbon_spec.hpp` 文本表 | label 与 QAction 文本并行 | 保留（M4 语义占位；绑定后按钮随 QAction） |

### 1.4 libs/ui_stageflow

| 组件 | 状态 | 决策 |
|---|---|---|
| `StageFlowController` | 可见性-only 缝合（无 canvas/project/layer 生命周期触及），QSettings per-stage 偏好 | 保留（正是目标形态） |
| `surface_state.hpp` | 零消费者（仅自身 core 测试） | **已删除**（连同其 3 个测试块） |

### 1.5 libs/ui_map / ui_canvas / ui_composite（主窗口相关部分）

| 组件 | 状态 | QGIS/Qt 原生替代 | 决策 |
|---|---|---|---|
| `DisplayMapCanvas`（自有 MapSession+ExtentHistory） | 验证工作区只读对照画布等隔离场景消费 | `QgsMapCanvas`（含内建缩放历史） | 保留（隔离展示画布是设计需要；ExtentHistory 与 canvas 历史并存的收敛属 Prompt 2 画布域，此处仅记录） |
| `UnifiedMapCanvas` | 产品零消费（回退角色）；自带工具控制器面平行于 `QgsMapTool` | `QgsMapCanvas` | 保留核心（headless 导出回退路径）；工具面不扩展 |
| `NativeMapCanvas` | 仅 `ui_canvas.qt_widgets_smoke` 消费 | `QgsMapCanvas` | **已删除**（连同 `NativeRasterRequestController`——其唯一消费者即此画布） |
| `NativeLayerTree`/`NativeLayerModel` | 仅 `ui_canvas.qt_widgets_smoke` 消费 | `QgsLayerTreeView` | **已删除**（第三套 layer tree；对应测试块移除） |
| `CompositeDocument` | 装配壳：宿主注入 canvas、governed QActions 组 `map_toolbar_`、MapStatusBar | — | 保留（无第二 action identity） |
| `LayerGroupController`+`LayerTreePlan` | 声明式"期望树"与 QGIS 运行时树调和（单一写者） | `QgsLayerTree` | 保留（领域调和层，QGIS 是运行时权威） |
| `map_tools.hpp` 工具族 | 头文件声明 QGIS 原生 QgsMapTool 是生产执行器、状态机仅 headless 回退 | `QgsMapTool*` | 保留 commit_* 落点；不再扩展回退鼠标机 |

### 1.6 主窗口 map tool 盘点（任务 C）

| 能力 | 现状 | QGIS 原生 | 决策 |
|---|---|---|---|
| pan | `QgsMapToolPan`（MW:783） | ✓ | 已原生 |
| zoom in/out | `QgsMapToolZoom`（MW:784-785） | ✓ | 已原生 |
| select | `QgsMapToolSelect`（edit_tool_controller.cpp） | ✓ | 已原生 |
| digitize 点/线/面 | `QgsMapToolDigitizeFeature`×3 + `QgsAdvancedDigitizingDockWidget` | ✓ | 已原生（提交走 session edit 单一 undo stack） |
| vertex 移动 | `VertexMoveMapTool : QgsMapToolEmitPoint`（MW:302-381） | `QgsVertexTool` 为 QGIS app 私有（非 public API）；`QgsMapToolVertexEdit` 是 gui 公共基类但不带交互 | 保留自研薄交互层，几何提交仍走 session edit（QGIS 无可直用的公共顶点工具） |
| identify | 未实现 | `QgsMapToolIdentifyFeature`（gui 公共） | **已新增**：governed action `identify` 直挂原生工具，结果摘要进状态条；active layer 派生 |
| measure（距离） | 未实现 | QGIS 的 QgsMeasureTool 在 `src/app/`（app 私有，非公共 API） | **已新增**：按公开 API 组合（`QgsMapToolEmitPoint` + `QgsRubberBand` + `QgsDistanceArea`），governed action `measure_distance`；未复制 QGIS 源码（许可证/移植条款 4 不触发） |
| snapping | QGIS 原生 snapping 配置（session/工具栈） | ✓ | 已原生 |

## 2. 与 Prompt 2/3 的边界

- 本方向不改：`libs/qgis/**`（MapSession 的 layer/tree/project 生命周期核心）、`libs/workspace/**`、
  catalog/project store/data provider。
- 唯一跨线缝：`MainWindow` 继续以 `context_.session().map()` 公共 API 消费 MapSession——零新接口。
- ui_composite 的删除（LayerManagerPanel/MappingStageBar）只涉及主窗口直接装配面，
  `LayerGroupController`/`LayerStageController` 等领域调和层不动。

## 3. 残留兼容层与退休计划

| 兼容层 | 唯一消费者 | 删除条件 |
|---|---|---|
| `DockManager` 全局 | ui_map/ui_seqviz/ui_review 页 + 少量测试 | 这些页随 closure slice 退役时一并删除 |
| `FloatController` 家族 | 同上 | 同上 |
| `CommandRegistry` 回调面 | palette/ribbon/workflow 步进 | 后续以 QAction 间接层替代 closure（另行 PR） |
| 非 CONV-27 行号映射 | reduced build（无 QGIS conv-27） | CONV-27 成为唯一配置时删除 |


## 4. 本轮实施摘要（v1）

- 删除：`LayerManagerPanel`（类文件、构造、隐藏舞步、第二实例）、`MappingStageBar`、
  `NativeMapCanvas`、`NativeRasterRequestController`、`NativeLayerTree/Model`、
  `surface_state`、`OperationRegistryQt` + `bind_registry_to_shell`、AppShell 孤儿文件菜单、
  AppShell 超级旧 ribbon evaluator、`refreshRecentProjects` 每菜单独立 QAction。
- 收敛：文件命令共享 QAction（`buildFileActions()`，含 MRU 共享与 `清除最近工程` 共享）；
  窗口布局单存储（CONV-27 唯一 `WorkbenchLayout`，platform_services 降级为 reduced 回退）。
- 生命周期（#1429 家族）：`superviseAttributeRun` worker 改为按值捕获 runner 指针；
  `ToolActionSet::apply` 支持 host parenting；AppShell 的函数内 static 服务改构造注入；
  新增 `check_map_object_identity` 回归（阶段切换 + 工程 close 后 QgsProject/canvas/tree 指针恒等）。
- 新增：governed `identify`（QgsMapToolIdentifyFeature，公共 API）与 `measure_distance`
  （公共件组合，QGIS 的量测工具在 app 私有层，无公共等价可直用——组合声明见 §1.6）。

## 5. 验证证据（本地，无线上 CI）

- 配置：`cmake --preset linux-native-product`（Ninja，Release，`build/native-product`，QGIS SDK 只读复用）；
  构建 `ninja -j4/-j2/-j1`（全过程并行度 ≤ 6；主机高负载时 GCC 16.2.1 偶发 transient ICE，
  重试同一目标即过，非本改动引入——单文件单独编 0 ICE）。
- 全量构建：`BUILD_OK`（1799 目标全部完成，含 tests 与 apps）。
- `pwb-platform --self-check`（offscreen）：**13/13 PASS**（ui_shell、data_gpkg_roundtrip、
  render_frame、layout_export、project_lifecycle、seismic_chain、python_free_process、
  service_registry 等）。
- 定向测试（ctest，offscreen）：
  - platform.app_shell、platform.three_stage_flow、platform.tool_policy、platform.ui_closure、
    platform.shell_project_actions、platform.lifecycle_cycles、platform.qgis_smoke、
    platform.qgis_smoke_app、platform.ribbon_visual_dpi15 —— 全部 Passed；
  - 库级 ui_composite / ui_canvas / ui_shell / ui_stageflow / ui_ribbon / ui_workstation /
    tool_policy 全部 smoke/oracle 测试 —— 16/16 Passed；
  - platform.closure_mapping —— Passed（A/B：baseline 亦通过；首轮 timeout 是负载下的 ctest 超时）。
- A/B 复核的环境型基线失败（与本次改动无关，如实记录）：
  - `closure_science.core`：缺 libonnxruntime（baseline 同样 FAIL）；
  - `platform.closure_mapping` 首轮 Timeout：单跑复验通过。
- 已知未覆盖：ONNX Runtime 执行器在本机不可用，closure_science 的预测路径未实测。
