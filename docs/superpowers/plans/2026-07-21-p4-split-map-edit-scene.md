# P4 — 拆分 map_edit_scene.py 实施计划

> **基线测试**：68 个 `test_map_*` 测试全部通过，全量 1109 测试全绿。  
> **目标**：将 `paleo_workbench/ui/pages/map_edit_scene.py`（1382 行 / 84 方法）拆分，抽取图形工厂、草图状态机、吸附计算与拓扑编排模块，主 Scene 代码量降至 ~600 行以内。零 UI / 零 API 行为变更。

---

### Task 1: 抽取 GraphicsItem 工厂到 `map_edit_factory.py`

**目标**：将 `_make_facies`、`_make_well`、`_make_line`、`_make_label` 及 `_item_from_record` 等 Item 创建与规范化逻辑从 `map_edit_scene.py` 抽离到独立模块。

**文件**：
- 新建 `paleo_workbench/ui/pages/map_edit_factory.py`
- 修改 `paleo_workbench/ui/pages/map_edit_scene.py`

**步骤**：
1. 创建 `map_edit_factory.py`，定义 `item_from_record(record: dict[str, Any]) -> FeatureItemMixin | None`。
2. 将 `_make_facies` / `_make_well` / `_make_line` / `_make_label` 迁移为 `map_edit_factory.py` 中的纯函数。
3. `MapEditScene._item_from_record` 委托给 `map_edit_factory.item_from_record`。
4. 运行 `test_map_edit_scene.py` 验证功能不变。

---

### Task 2: 抽取草图绘制状态机到 `map_edit_draft.py`

**目标**：将线段/相带轮廓草图绘制过程的点集管理、QGraphicsPathItem 实时预览与草图完成/取消逻辑抽取为 `DraftController` 类。

**文件**：
- 新建 `paleo_workbench/ui/pages/map_edit_draft.py`
- 修改 `paleo_workbench/ui/pages/map_edit_scene.py`

**步骤**：
1. 创建 `map_edit_draft.py`，实现 `DraftController`：
   - 维护 `_draft_points`、`_draft_kind` 与 `_draft_preview` 图形项。
   - 提供 `append_point`、`update_preview`、`cancel`、`finish_line`、`finish_facies` 等接口。
2. `MapEditScene` 组合 `DraftController` 实例，将 `finish_line_draft`、`finish_facies_draft`、`cancel_line_draft`、`draft_point_count` 等公共 API 委托给该实例。
3. 运行 `test_map_facies_draw.py` 与 `test_map_line_label.py` 验证草图交互。

---

### Task 3: 抽取吸附与候选点计算到 `map_edit_snap.py`

**目标**：将控制点吸附使能、公差管理、参考吸附点以及吸附候选点缓存构造等逻辑抽离为 `SnapManager` 类。

**文件**：
- 新建 `paleo_workbench/ui/pages/map_edit_snap.py`
- 修改 `paleo_workbench/ui/pages/map_edit_scene.py`

**步骤**：
1. 创建 `map_edit_snap.py`，实现 `SnapManager`：
   - 维护 `snap_enabled`、`snap_tolerance`、`reference_snap_points` 与 `candidate_cache`。
   - 提供 `snap_xy(x, y, draft_points)`、`invalidate_candidates()`、`rebuild_candidates(items, reference_points)`。
2. `MapEditScene` 组合 `SnapManager`，将 `set_snap_enabled`、`set_snap_tolerance`、`set_reference_snap_points` 等接口委托给 `SnapManager`。
3. 运行 `test_map_vertex_edit.py` 验证节点吸附行为。

---

### Task 4: 抽取拓扑与几何编排到 `map_edit_topology.py`

**目标**：将相带几何自交/拓扑检验、相邻相带缝隙检查、拓扑强制重建（rebuild_topology_forced）、相带合并（merge_selected_facies）与拆分（split_selected_facies_by_line）的高级编排算法抽取为独立模块。

**文件**：
- 新建 `paleo_workbench/ui/pages/map_edit_topology.py`
- 修改 `paleo_workbench/ui/pages/map_edit_scene.py`

**步骤**：
1. 创建 `map_edit_topology.py`，定义相带拓扑计算辅助函数：
   - `facies_geometry_issues(item)`
   - `validate_adjacency_warnings(items, snap_tolerance)`
   - `build_rebuild_topology_plan(items, snap_tolerance)`
   - `build_merge_facies_command(...)`
   - `build_split_facies_command(...)`
2. `MapEditScene` 中的拓扑方法调用上述模块，并将 Undo/Redo 命令 push 入 `_command_stack`。
3. 运行 `test_map_topology.py` 与 `test_map_topology_rebuild.py` 验证拓扑运算全绿。

---

### Task 5: 最终集成与全量测试验证

**目标**：确认 `MapEditScene` 结构精简至目标范围内，跑全量 pytest 并提交。

**步骤**：
1. 检查 `map_edit_scene.py` 行数，确认已降至 ~600 行以内。
2. 运行全量 `pytest tests`（1109 个测试）。
3. 更新 Spec 状态与 `.superpowers/sdd/progress.md` 进度台账。
4. Git 提交。
