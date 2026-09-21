# 02 — Architecture（V14 QGIS Layer Control Plane）

## 0. 总原则

- **QGIS `QgsLayerTree` 是运行时树/顺序/组结构唯一权威**；领域侧持有的是
  *期望树*（desired tree）——由「组模板 + 成员资格 + 用户放置 + 排序键」
  纯函数构建，经增量 reconcile 应用到 QGIS，用户树事件回写期望树。
  两侧永不对抗（程序化变更抑制回声；用户变更先落期望树）。
  这是 Python V5/V11/V13 已验证的权威模型——本线是**移植，不是再发明**。
- **不建第二棵树、第二套 order、第二套绑定**：所有持久化落在既有
  `mapping_workspace` JSON 节（`state.tree`/`memberships`/`stage_states`）。
- 分层：**Qt-free 纯核心**（可全量本地测试）→ **QGIS applier**（薄、机械）→
  **平台 glue**（具名小块）。

## 1. 模块地图

```
libs/workspace（Qt-free；data 闭包；本机全量可验证）
├─ layer_order.{hpp,cpp}      分数排序键引擎 + ROLE_BANDS/FACTOR_ROLE_RANK
│                             （layer_order.py 1:1 移植；KeySpaceExhausted 等）
├─ layer_tree.{hpp,cpp}       LayerRef/GroupNode/LayerTreeSnapshot +
│                             tree_from_nodes（layer_tree.py 移植）
├─ layer_tree_diff.{hpp,cpp}  keyed-LCS 最小操作集 TreeDiff（layer_tree_diff.py）
├─ source_usage.{hpp,cpp}     version/asset → 地图用途反查（source_usage.py；
│                             project 节以 Json 只读传入；catalog 以 seam 注入）
└─ state_ops.{hpp,cpp}        StageViewState/MappingWorkspaceState 行为面
                              （view_state/effective_group_visibility/record_*/
                              membership/set_membership/drop_membership——
                              stage_state.py 行为方法补齐，codec 不动）

libs/ui_composite（Qt-free core；与 layer_groups/stage_profiles 同居）
├─ layer_tree_plan.{hpp,cpp}          期望树 planner（layer_tree_plan.py；
│                                     复用本库 layer_groups 注册表 + workspace 引擎）
├─ layer_group_controller.{hpp,cpp}   reconcile/observe/stage 可见性/用户组/
│                                     绑定注册入口（layer_group_controller.py）
│                                     ——经 ILayerTreeStack seam 驱动任意栈
├─ layer_stage_controller.{hpp,cpp}   set_stage/restore_stage_view/active target
│                                     重指派（controller.py 的图层相关子集）
├─ layer_targets.{hpp,cpp}            active/edit/tool/selection 显式目标模型
│                                     + 事务后重验证（fail-closed）
└─ layer_presentation.{hpp,cpp}       图层行状态语言（active/editing/dirty/
                                      stale/missing/locked/RAW/role/warning）
                                      ——panel/statusbar 消费的纯数据投影

libs/qgis（QGIS applier；薄机械层；本机不可编译→镜像既有已验证模式 + 独立 review）
├─ layer_tree_stack.{hpp,cpp}   QgsLayerTreeStack : ILayerTreeStack
│                               （MapSession 的 QgsProject 上：pwb/group_id 组、
│                               layer_adapter join key、索引化批量放置、
│                               事务窗口 + revision + 回声抑制、DFS 观察快照）
└─ layer_order_util.hpp         命名方向转换：bottom_first_for_layout_item(top_first)

libs/ui_widgets/src/qgis/canvas_shim.cpp   export_vector 树序修复（3 行，
                                           与 #1434 的镜像过滤正交）

apps/paleo_workbench_platform/main_window.cpp   BEGIN/END V14-QGIS-CONTROL 具名块：
                                                stage 切换接 layer policy、
                                                openProject reconcile、save 回写 tree
libs/ui/layer_tree_panel.cpp                     行内状态 chips + 右键动作（additive）
```

## 2. 关键对象与生命周期

### ILayerTreeStack（seam，ui_composite 定义）
控制器对「栈」的全部依赖面（Python duck-type stack 的显式化）：
`groups_available / upsert_group / rename_group / remove_groups_except /
move_layer_to_group / move_group / apply_tree_placements(→skipped 数) /
set_group_visibility / set_group_expanded / tree_snapshot_nodes /
begin_tree_update→token / end_tree_update(token)→{revision,deferred_sync}`。
实现一：`QgsLayerTreeStack`（libs/qgis）。实现二：测试 fake（记录调用计数
——call-count 断言的基础）。Python 桥本身就是第三个等价实现（已存在）。

### LayerGroupController（ui_composite）
- 状态来源：`MappingWorkspaceState&`（引用，非拷贝——单一状态真源）。
- `reconcile(layer_snapshots, force)`：build_desired_tree → tree_transaction
  窗口内 diff 应用（组创建→清理→批量放置，skipped>0 抛出且基线不动）→
  `state.tree = desired.to_json()` → 记录 revision。
- `observe_tree_nodes(nodes)`：用户结构回写 + 角色路由校验（非法放置拒绝并
  携带 (layer,group) 反馈，期望树保持原状→下次 reconcile 拉回）+ 观察序→键。
- `apply_stage_visibility(stage)`：全量推组显隐（Python 漂移rationale保留）。
- `register_layer(...)`：V13 绑定注册入口（source_version_id 非空且未显式给
  kind → catalog_version；委托 workspace mutations）。
- 事务性：`reconciling` 标志 + revision 对账（echo_is_stale）。

### LayerStageController（ui_composite）
`set_stage`：current_stage 写入 → rematerialize_for_stage（try 保护，桥 throw
不中断切换）→ apply_stage_visibility → reassign_active_target（stored→profile
roles→None，绝不跨阶段继承）→ 信号。`restore_stage_view`：reopen 后恢复
可见性/展开/目标。目标存在性经 `ITargetLayerValidator` 探针（无探针退
membership 存在性——保守近似）。

### LayerTargets（ui_composite）
显式四目标：`active_layer_id` / `editing_layer_ids`（集合，编辑会话）/
`tool_target_id` / `selection_layer_id`。不变量与重验证见 03 §5。
与既有 `ProjectSession::set_active_layer` 统一 setter 的关系：平台 glue 将
panel/编辑事件汇入本模型，由 glue 单点回写 ProjectSession（不产生第二
「当前层」真源——LayerTargets 是策略层，QGIS canvas currentLayer 仍是
运行时事实，模型重验证以探针读回）。

### QgsLayerTreeStack（libs/qgis）
- 组：`QgsLayerTreeGroup` + `pwb/group_id` custom property（与桥同词汇）。
- 层 join：`layer_adapter`（`pwb/layer_id` 主，`pwb/doc_id` 读兼容）。
- 事务窗口：guard 标志抑制树回调处理 + `canvas setRenderFlag(false)` +
  收口一次手动 `syncCanvasLayers` + `refresh`（仅用稳定公共 API；
  bridge 自身的中间 setLayers 为幂等）。
- revision：每次程序化收口 ++；供 echo_is_stale 对账。
- 批量放置：一次遍历建 `node→(parent,index)` 索引后逐项 take/insert
  （桥 applyTreePlacements 的 MapSession 版）。

## 3. 数据流

### 正向（领域 → QGIS）
```
组成快照(layer facts) ──ensure_memberships──▶ memberships
        │
        ▼
build_desired_tree(plan) ──diff──▶ TreeDiff ──ILayerTreeStack(事务窗口)──▶ QgsLayerTree
        │                                                                          │
        └──────────── state.tree 持久化 ◀──────────────────────────────────────────┘（应用成功后）
```

### 反向（QGIS 用户事件 → 领域）
```
树结构回声(nodes) ──observe_tree_nodes──▶ 放置表/序表/键（校验失败→拒绝+拉回）
组勾选回声 ──record_group_visibility──▶ StageViewState（当前阶段覆盖层）
层勾选/透明度回声 ──record_layer/visibility/opacity──▶ StageViewState
```

### 双向数据绑定查询
```
数据→地图：usages_of_version/asset(workspace, project Json, catalog seam)
地图→数据：membership(layer_id) → LayerBinding（version/asset/kind/bound_at/stage）
```

## 4. 线程/异步模型

全部 GUI 线程同步执行（与既有 MapSession/panel 一致）；无新增线程。
reconcile/stage 应用均为短瞬时操作（≤百级组、千级层的纯内存计算 + 已索引
的树操作）。性能合同见 03 §8（call-count 断言）。

## 5. 失败语义

- 桥/applier throw：reconcile 抛出（不吞），`_last_applied` 不变，下次重试；
  stage 切换路径 try 保护（切换本身不失败）。
- 事务窗口异常：RAII 收口（applied 保留，host 经 revision/diff 对账）。
- skipped placements：reconcile abort（基线不动）。
- QGIS 不可用：`groups_available()==false` → 控制器诚实 no-op + degraded
  reason（UI 必须显示，不假装分组）。
- 未知输入：unknown 不猜（unknown stage→default+诊断、unknown binding kind→
  ""、unknown group placement→home 路由）。

## 6. 与其他线的接缝

- Prompt1：`UsageCatalog` seam 由 data 侧实现（catalog 查询面）；本线不改 catalog。
- Prompt2：`layer_presentation` 行状态 + 本线 panel glue 提供；页面布局不动。
- Prompt4：factor 产出 → `register_layer`（既有 mutations API）。
- Prompt5：canonical order 读取面 = `LayerTreeSnapshot::layer_ids_top_first` /
  `MapSession::layerIdsTopFirst`；不建第二 order。

## 7. 明确的非目标

- 不做 mini-QGIS；不接管渲染。
- 不重建 Python 桥已有能力（桥零改动；原生产品经 MapSession 路径获得同等能力）。
- envelope（`map_qgis_project_xml`）的 C++ apply 为**已知限制**（见
  08-known-limitations）：原生路径样式经 sidecar；顺序/组/可见性 parity 由
  state.tree reconcile 保证。
