# 00 — Baseline（执行时快照，2026-09-20）

线：`V14-QGIS-CONTROL` · 分支 `feat/v14-qgis-layer-control-plane` · Base SHA
`412d8baf22a6a928c860e2e3d6c1108a9c035c78`（= 执行时 `origin/main`，与 Prompt
快照一致）。

## 1. 仓库状态

- open PR：**#1434**（`fix/open-issues-batch`，CONV-25/curve/polygonize/QGIS
  mirror-export perf/表格 perf/卫生/CI 环境）与 **#1435**
  （`devin/1789909230-cpp-final-closure`，迁移矩阵 + cmake/install 收口）。
  详见 `01-overlap-audit.md`。
- 最近 30 个 main commits 为 C++ closure wave（#1412–#1433）收口合并。

## 2. 双栈现状：谁在操纵 QGIS 图层树

执行时 main 存在**两个平行的 QGIS 栈接入面**：

| 面 | 代码 | 消费者 | 已有能力 |
|---|---|---|---|
| Python 桥 | `native/qgis_render_bridge/src/map_stack_service.cpp`（`QgisMapStack`） | 遗留 Python GUI | tree transaction 窗口、group API、`applyTreePlacements`（索引化批量放置）、`mirrorTreeOrderTopFirst` 单一顺序源、revision/echo 抑制、`pwb/doc_id` 身份、project XML envelope 读写 |
| 原生产品 | `libs/qgis`（`MapSession` 拥有 `QgsProject`）+ `libs/ui/LayerTreePanel` + `apps/paleo_workbench_platform` | C++ 平台 App | 真图层添加（`addVectorLayer` + 样式 sidecar）、`pwb/layer_id` join key（`layer_adapter`）、`layerIdsTopFirst`、布局导出显式反序、active-layer 统一 setter、stage 仅改工具面 |

**控制平面缺口全部在原生产品侧**：Python `mapping_workspace/` 的
order 引擎、期望树 planner/diff、LayerGroupController reconcile、
stage 可见性应用、active target 重指派、source_usage 反查，均无 C++ 对应物。

## 3. 已有权威（本线复用，不重建）

- 组模板/角色 home 路由/拖放校验：`libs/ui_composite/src/layer_groups.cpp`
  （`layer_groups.py` 的冻结移植，Qt-free）。
- 阶段词汇：`libs/tool_policy/stages.{hpp,cpp}`；stage profile：
  `libs/ui_composite/src/stage_profiles.cpp`。
- 绑定记录（V13 全字段）：`libs/workspace/state.hpp`（`source_version_id`/
  `source_asset_id`/`binding_kind`/`bound_at`）+ `mutations.cpp`
  （`set_layer_binding`/`rebind_to_version`/`repair_stale_bindings`）。
- 编辑会话/门禁：`libs/mapping_document/native_edit_session.*`（#1412）。
- 顺序契约文档：`geodata-qgis-control-v13/07-layer-order-contract.md`
  （top-first 公共契约；布局边界显式反序）。
- 镜像发布账本：`libs/ui_widgets/qgis/mirror_snapshot.*`（#1434 正在加
  doc_id 索引——本线只调用不重建）。

## 4. 关键缺口（本线工作项）

1. `layer_order.py`（分数排序键 + ROLE_BANDS + LIS 保键分配）无 C++。
2. `layer_tree.py` / `layer_tree_diff.py` / `layer_tree_plan.py` 无 C++。
3. `layer_group_controller.py`（reconcile/observe/stage 可见性/用户组）无 C++。
4. `controller.py` 的 `set_stage`/`restore_stage_view`/`_reassign_active_target` 无 C++。
5. `source_usage.py`（version/asset → 地图用途反查）无 C++（仅 ui_review 有
   `IMapUsageSource` seam）。
6. C++ 平台 `openProject` 不应用 `map_qgis_project_xml` envelope，
   不从 `mapping_workspace.tree` reconcile 树。
7. `QgisCanvasShim::export_vector` 用 `project.mapLayers()`（QMap id 序）
   构建导出层列表——**不按树序**，与 `LayoutService`（显式反序树序）不一致。
   #1434 修的是该函数的镜像过滤，顺序 bug 仍在。
8. Active/edit/tool/selection target 无显式状态模型与事务后重验证。

## 5. 构建环境事实（本机）

- cmake 3.30.5（tarball 安装于 /tmp）、系统 Qt 6.11.2 dev（256 个 cmake
  config）、GCC 16.2.1、无 ninja（用 Unix Makefiles）。
- **vendored QGIS SDK 缺失**（`~/main/third_party/qgis` 不存在）→
  `PWB_BUILD_PLATFORM=ON` 在 `PwbQgisSdk.cmake` 处 FATAL。
- 可完整构建+ctest：`PWB_BUILD_DATA=ON` 闭包（domain/project/workspace/
  catalog/ingest + tests/cpp/data），全部 Qt-free。
- 平台/QGIS/Qt-widget TU 本机不可编译——与 #1434/#1435 同一环境限制；
  该部分代码按既有已验证模式（map_stack_service.cpp 等）编写并经
  独立 review，PR 中如实申报。

## 6. Source-of-Truth Map（执行时）

| 关注点 | 真源 | 位置 |
|---|---|---|
| 运行时树/顺序/组结构 | QGIS `QgsLayerTree` | `MapSession::project_`（原生）/ `QgisMapStack`（桥） |
| 领域期望树 + 排序键（持久化） | `mapping_workspace.tree`（JSON） | `libs/workspace`（本线补消费/生产 C++） |
| 图层身份 join key | `pwb/layer_id`（读兼容 `pwb/doc_id`） | `libs/qgis/layer_adapter.hpp` |
| 数据绑定 | `MappingWorkspaceState.memberships` | `libs/workspace/state.hpp` |
| 组模板/角色路由 | `system_group_templates()` | `libs/ui_composite/layer_groups.cpp` |
| 阶段状态 | `StageViewState` ×3 | `libs/workspace/state.hpp` |
| 顺序方向 | top-first 公共契约；布局边界显式反序 | v13 `07-layer-order-contract.md` |
| 阶段工具面 | `tool_policy` | `libs/tool_policy` |
| 编辑会话 | `native_edit_session` | `libs/mapping_document` |
