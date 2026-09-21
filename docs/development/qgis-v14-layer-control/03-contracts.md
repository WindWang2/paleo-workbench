# 03 — Contracts（冻结词汇与不变量）

以下词汇/不变量一旦实现即冻结：改动需要新 ADR。断言载体是各测试文件
（见 05-test-plan）。

## 1. Layer Order Contract（唯一方向规范）

- **公共契约：top-first**（index 0 = 图例/树最上 = 渲染在最上）。
  适用于：`LayerTreeSnapshot` 遍历、planner 输出、reconcile 放置索引、
  `ILayerTreeStack` 观察快照、`MapSession::layerIdsTopFirst`、
  `QgsMapSettings/Canvas::setLayers`（QGIS 语义即首元素在上）。
- **bottom-first 只存在于两个命名边界**：
  `QgsLayoutItemMap::setLayers`（布局项）——转换函数必须命名
  `bottom_first_for_layout_item(top_first)`（libs/qgis/layer_order_util.hpp）。
  除该助手与既有 LayoutService/layout_spec_exec 的显式反序外，全仓
  **禁止**无命名 reverse。
- 排序键：`a–z` 字母表字符串、纯字典序全序；默认键 = 定宽 8 位 base-26
  （值域从 2 起）；单键 >64 字符触发整容器 rebalance；紧邻对抛
  `KeySpaceExhausted`（调用方 rebalance 后重试——设计内路径）。
- 组内默认科学序 = ROLE_BANDS（33 角色，20–158；未知角色 → 150 参考带）；
  factor 容器内 = FACTOR_ROLE_RANK（input→grid→contour→classification→
  uncertainty→QC）。带值只决定**默认**；用户拖拽经 LIS 保键 + 中点插入，
  一次拖动只改最少的键。

## 2. Layer Identity & Binding Contract

- 领域身份 = `LayerBinding.layer_id`（= QGIS `pwb/layer_id`；读兼容
  `pwb/doc_id`）。**path/显示名/QGIS internal id 永不作为身份**；rename
  不断绑定；QGIS id 重建后按稳定 layer_id 复绑。
- 绑定权威 = `MappingWorkspaceState.memberships`（V13 全字段）。QGIS
  custom property 只是运行时 join 键投影，**禁止**把 source_version_id 等
  catalog 身份写入 QGIS 属性当第二数据库。
- 未知 = 空串（UNKNOWN），绝不猜：`binding_kind=""` 读侧经
  `effective_binding_kind` 解释；写侧 `rebind_to_version` 显式落
  `catalog_version`。
- 注册入口：`LayerGroupController::register_layer`（`source_version_id`
  非空且未显式给 kind → `catalog_version`；重钉 = 覆盖）。
- 生命周期：removed layer → `remove_layer_binding`（清 per-stage 覆盖）；
  restored layer → 复注册（同 layer_id）；stale source →
  `repair_stale_bindings`（repaint-to-current 或 reset-UNKNOWN，绝不静默
  删 membership）；duplicate doc_id → 发布层拒绝（mirror 既有语义）。
- 双向查询：`usages_of_version/usages_of_asset`（kind ∈ layer/factor_grid/
  compilation_input/map_product_output/map_product_input/run_input；
  run 上限 100 + `truncated` 如实）；图层→数据由 membership 记录自答。
  catalog 侧只经 `UsageCatalog` seam（不直查 SQLite）。

## 3. Tree Transaction Contract

- 一切批量树变更（reconcile / stage 应用 / 批量增删 / source replacement）
  必须在 `begin_tree_update()→end_tree_update(token)` 单窗口内：
  - 窗口内：中间结构变更不触发收口同步（applier 抑制 + canvas
    renderFlag(false)）；
  - 收口：恰好一次 sync + refresh；`revision` 单调递增；
  - 回声：窗口内及 revision ≤ applied_revision 的树事件**必须丢弃**
    （echo_is_stale）；
  - 异常：RAII 保证收口执行；已应用变更保留（partial-failure 由
    revision/diff 对账，不回滚半树）；
  - skipped placements > 0 → reconcile abort（`_last_applied` 不动）。
- programmatic vs user：程序化路径全部经 applier（抑制回声）；用户路径
  （树视图拖拽/勾选/改名）走 observe/record 入口（不抑制）。两类事件
  在控制器内可区分（`reconciling` 标志）。

## 4. Group Model Contract

- 组身份 = `group_id`（系统组模板 id / `factor.<task_id>` / `user.<hex>`），
  与显示名解耦；rename 不改 id。
- 种类：system（模板，role-managed 不可删）/ factor（任务动态）/
  user（可嵌套，parent ∈ {root, user组}；拖入系统组非法——拒绝并携带
  (group_id,parent) 反馈）。
- 组删除**绝不级联删层**：子层与嵌套组上提一级。
- 拖放校验：`movable_into_system_group(role, group_id)`（语义不相容拒绝；
  用户组/root 恒允许）。拒绝 → 期望树不动 → 下次 reconcile 拉回 + 宿主提示。
- 组显隐应用 = **全量推**（不跳未变化——漂移 rationale，Python R6）；
  组展开态 = UI 偏好（QSettings 侧），不进科学工程。

## 5. Target Model Contract（active/edit/tool/selection）

不变量（违反任一 = P0 缺陷）：
1. UI 宣称「正在编辑 A」时，编辑工具的写目标**必须**是 A（tool_target ⊆
   editing 集合；vertex/绘制工具激活前 preflight：目标不在编辑集 →
   fail-closed 带原因，绝不静默写到别层）。
2. layer 删除 → 该层编辑目标失效：`revalidate(live_probe)` 将其移出
   editing/tool/selection 集，dirty 会话按宿主策略 fail/close（不静默丢）。
3. stage 切换 → edit target **不跨阶段继承**：重指派顺序 = 本阶段持久化
   `active_layer_id`（图层仍在）→ profile.active_editing_roles 首个有现存
   图层的角色 → None（编辑动作禁用并显示原因）。
4. multi-layer snapping ≠ multi-layer editing（snapping 配置永不扩大写目标）。
5. `selection` 变更不改变写目标（select B 后 vertex 仍写 A 时必须有可见
   提示——由 presentation 层 `tool_target` 状态语言承载）。
6. native current layer 与领域目标一致性可验证：`revalidate` 以运行时探针
   读回为准（canvas currentLayer = 事实；模型失败即报告 drift）。

## 6. Stage Layer Policy Contract

- `set_stage`（瞬时，绝不触发重计算/重建图层/重写 order）：
  1. `current_stage` 写入；
  2. `rematerialize_for_stage`（新阶段空系统组物化，diff 最小；桥 throw
     不中断切换）；
  3. `apply_stage_visibility`（profile 默认 + 用户覆盖全量推）；
  4. `_reassign_active_target`（见 §5.3）；
  5. 组锁默认（locked_groups 无用户覆盖时置 locked）。
- per-stage 用户可见性/透明度覆盖层（StageViewState）跨切换保留；
  shared layer 单实例，不重复实例化；新层入组 = 系统组尾部 / 用户组与
  root 头部（V12 D9/R10）。
- 首见容器默认序 = 科学带序；已观察容器 = 观察序 + 新成员并入。

## 7. Persistence / Reopen Contract

- 持久化载体：`mapping_workspace` JSON（tree{children[source,order_key,
  kind,expanded,locked,visible]} / memberships / stage_states{group_visibility,
  layer_visibility,layer_opacity,active_layer_id,customized}）。
- save/reopen 后必须满足：`tree == canvas == legend == layout`（同一
  top-first 序）；组结构/键/可见性/展开/active target 语义保留；
  阶段视图状态恢复（restore_stage_view）。
- 旧工程缺字段：additive 默认（无 tree → 路由默认树；无 kind → 读侧解释）；
  unknown 不猜；**无破坏性重写**（extra 保留——codec 既有契约）。
- 阶段视图 `customized` 只由用户手势置位；程序化 stage 推送不得冻结成
  用户覆盖（record_* 只从用户回声入口调用）。

## 8. Scale & Performance Contract（结构断言，非仅 wall-time）

以 fake-stack 调用计数 + 复杂度断言承载：
- 1000 层 / 20 组 reconcile：`upsert_group` ≤ 组数、`remove_groups_except`
  恰好 1 次、`apply_tree_placements` ≤ 1 次、move 数 = diff 真实差异
  （同树重复 reconcile = 0 move）；无 O(N²) `.index` 热点（LIS/LCS 均
  O(N log N)）。
- 批量增删 N 层：单事务窗口（begin/end 各 1 次），无 per-layer sync。
- stage 切换 ×100：不重写 order（键不变断言）、组显隐全量推但
  `set_group_visibility` 调用数 = 组数（非层数）。
- usage 查询有界（run 条目 ≤100，truncated 如实）。
- UI 行更新 diff-based（观察快照→放置表更新为键控，不整树重建——
  由 observe 契约承载）。

## 9. 词汇冻结（新增稳定字符串）

- usage kinds：`layer / factor_grid / compilation_input /
  map_product_output / map_product_input / run_input`。
- 状态语言（layer_presentation）：`active / editing / dirty / stale /
  source_missing / locked / raw / role:<v> / warning / scale_range /
  selected`（与桥 setRowIndicators kinds 对齐：dirty/stale/missing/
  missing_input/superseded/degraded/frozen/published/reviewed）。
- 组 id 前缀：`phase / factor. / user. / base. / legacy. / epoch.`（既有）。
- 排序键字母表：`a–z`；INDEX_WIDTH=8；REBALANCE_LENGTH=64。
