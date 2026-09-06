# 02 — 图层组与角色

## 稳定身份（§10/§11）

- **LayerRole**（`layer_roles.py`）：machine-readable 科学角色（30+ 值），
  不由用户 rename 改变；RAW 保护集（初始相图/预测/插值面）拒绝编辑会话。
- **group_id**：稳定组标识（`phase1.initial_facies` / `factor.<task_id>` /
  `user.<ts>`），与显示名解耦；经 QGIS custom property `pwb/group_id` 寻址。

## 联合树（Union Tree，§38 One Layer Identity）

QGIS 树是**全阶段系统组 + 用户组 + factor 组的联合树**；一个图层只出现一次
（home group 由角色路由决定）。跨阶段证据（如 Phase 2 的「上阶段成果」）
通过组的多阶段 membership + 阶段锁表达，而非复制图层：

| 组 | 阶段可见 | 阶段锁定 |
|---|---|---|
| `phase3.cartography / qc / integrated / geology` | P3 | — |
| `phase1.interpretation`（人工解释与修编） | P1/P2/P3 | P2/P3（证据） |
| `phase2.constraints` | P2/P3 | P3 |
| `phase2.factors`（含 factor.* 子组） | P2/P3 | P3 |
| `phase1.well_predictions / seismic_predictions` | P1 | —（模型结果） |
| `phase1.initial_facies` | P1/P2 | —（RAW 由角色保护） |
| `base.reference` | 全部 | — |
| `legacy.unclassified` | 全部 | —（旧工程兜底） |

排序（order 小者在上=渲染在上）：编图要素 > QA > 综合解释 > 地质表达 >
人工解释 > 约束 > 单因素 > 预测 > 分析 > 初始相 > 辅助 > 基础。

## 角色路由与拖放校验（§51）

`home_group_for_role(role, stage_hint, factor_task_id)` 决定 home group；
`movable_into_system_group` 拒绝语义不相容的系统组放置（科学角色 ≠ 视觉
放置）；用户组自由。非法放置经 `observe_tree_nodes` 拒绝，下一次 reconcile
把 QGIS 树拉回正确位置。

## Factor 组（§21/§26/§71）

factor 任务 → `factor.<task_id>` 子组（挂 `phase2.factors` 下），内部按
`FACTOR_CHILD_ORDER`（输入→栅格→等值线→分级→不确定性→QC）排序。删除
factor 组绝不删输入数据（`remove_groups_except` 先上提子节点再删空组）。
同一 FactorGridResult 在 P2/P3 共享同一数据身份（live 网格缓存派生叠加）。

## 系统组 vs 用户组（§52/§53）

系统组（模板注册表 `SYSTEM_GROUP_TEMPLATES`）承载阶段流程语义，role-managed，
不可删除（可隐藏/折叠）；用户组（QGIS 树右键「新建图层组」）自由组织，
删除时图层上提保留。
