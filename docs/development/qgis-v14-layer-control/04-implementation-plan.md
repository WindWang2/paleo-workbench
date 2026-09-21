# 04 — Implementation Plan（实际执行记录）

Base `412d8baf`；全部为 additive 新文件或具名 `BEGIN/END V14-QGIS-CONTROL`
块。顺序 = 实际执行顺序。

## 阶段 1 — Qt-free 核心（libs/workspace，data 闭包全量本地验证）

| 交付 | 文件 | 移植源（冻结 oracle） |
|---|---|---|
| 排序键引擎 + 角色带 | `include/pwb/workspace/layer_order.hpp` + `src/layer_order.cpp` | `layer_order.py` |
| 树模型 LayerRef/GroupNode/Snapshot | `include/pwb/workspace/layer_tree.hpp` + `src/layer_tree.cpp` | `layer_tree.py` |
| keyed-LCS 最小操作集 | `include/pwb/workspace/layer_tree_diff.hpp` + `src/layer_tree_diff.cpp` | `layer_tree_diff.py` |
| 状态行为面 | `include/pwb/workspace/state_ops.hpp` + `src/state_ops.cpp` | `stage_state.py` 行为方法 |
| version/asset → 用途反查 | `include/pwb/workspace/source_usage.hpp` + `src/source_usage.cpp` | `source_usage.py` |
| 测试 | `workspace_tests/{oracle_replay_test, layer_control_scale_test, CMakeLists, fixtures}` | `tools/oracle/generate_layer_control_fixtures.py`（新增） |

## 阶段 2 — 控制平面（libs/ui_composite Qt-free core，fake-stack 验证）

| 交付 | 文件 | 移植源 |
|---|---|---|
| 期望树 planner | `include/pwb/ui_composite/layer_tree_plan.hpp` + src | `layer_tree_plan.py` |
| 组控制器 + ILayerTreeStack seam + 事务窗口 | `layer_group_controller.{hpp,cpp}` | `layer_group_controller.py` |
| 阶段控制器 | `layer_stage_controller.{hpp,cpp}` | `controller.py` 图层子集 |
| 目标模型 | `layer_targets.{hpp,cpp}` | Prompt §10 契约（新设计，Python 无对应物） |
| 行状态语言 | `layer_presentation.{hpp,cpp}` | Prompt §12；词汇对齐桥 setRowIndicators |
| 测试 | `composite_tests/layer_control_test.cpp` | fake-stack call-count 契约 |

## 阶段 3 — QGIS applier（libs/qgis，需 vendored SDK，本机不可编→模式镜像 + 独立 review）

- `include/pwb/qgis/layer_tree_stack.hpp` + `src/layer_tree_stack.cpp`：
  `QgsLayerTreeStack : ILayerTreeStack`（`pwb/group_id` 组、layer_adapter join、
  一次遍历索引化批量放置、子树安全搬移、事务窗口 render 抑制 + 单次收口、
  DFS 观察快照）。移植模式取自 `map_stack_service.cpp` 已验证实现。
- `include/pwb/qgis/layer_order_util.hpp`：命名方向转换
  `bottom_first_for_layout_item` / `top_first_from_layout_item`。
- `MapSession::canvases()` 访问器（additive）。

## 阶段 4 — 修复与平台 glue（具名块）

- `libs/ui_widgets/src/qgis/canvas_shim.cpp`：`export_vector` 改用
  `layerTreeRoot()->layerOrder()`（top-first）过滤镜像层——修复导出 z 序
  与屏幕/布局不一致（与 #1434 的镜像过滤语义正交；见 01 §1 协调记录）。
- `apps/paleo_workbench_platform/main_window.{hpp,cpp}`：
  `applyLayerControlForOpen`（openProject 成功路径：活状态载入 → stack 绑定 →
  ensure_memberships → reconcile → restore_stage_view → facts 状态语言注入）；
  `applyStageValue` 接 `layer_stage_->set_stage`；`syncLayerControlOnSave`。
- `apps/paleo_workbench_platform/shell_project_actions.cpp`：save 前调
  `syncLayerControlOnSave`（`write_mapping_workspace` 落 `mapping_workspace` 节）。
- `libs/application/project_session.hpp`：`DomainLayerFacts` 增加
  `status_flags/status_summary`（additive）。
- `libs/ui/layer_tree_panel.cpp`：tooltip 消费状态语言（additive 三行）。

## 明确不做（本轮）

- `map_qgis_project_xml` envelope 的 C++ apply（原生路径样式经 sidecar；
  见 08-known-limitations §1）。
- Python 桥（`native/qgis_render_bridge`）零改动——原生产品经 MapSession
  路径获得同等能力，桥继续服务遗留 GUI。
- LayerTreePanel 的右键新动作（信号/moc 变更在无编译环境下的风险大于收益；
  现有 default actions + 属性面板已接；见 08 §3）。
