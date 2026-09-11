# 07 — Undo / Redo / Transaction（V10 审计）

## A. 三层撤销架构（不变）

| 层 | 机制 | 粒度 |
|---|---|---|
| 单层单命令 | `undo_stack`/`redo_stack`（EditCommand 快照） | 一个原始命令 |
| 单层复合 | `begin/end_edit_command` 宏 → `compound` 命令（before/after 合并） | 一个手势 = 一个 undo 单元（delta 保留逐操作） |
| 跨层复合 | `TopologyService.CompoundUndoGroup`（身份匹配 pop_command/push_command_back + revision guard） | 一次地质动作（move+传播）= 一组原子 undo/redo |

纪律：宏打开时拒绝 undo/redo；compound 组冲突扫描（组内要素被后续非组
编辑触碰 → 拒绝并给理由）；`pop_command` 不进单层 redo 栈（组持有历史）。

## B. 不变量（V10 以测试锁定）

1. **一个用户级动作 → 一个 undo 单元**：vertex 拖动（宏）、split、merge、
   reshape、repair、duplicate、add_ring、delete_ring、add/delete/move part、
   explode、collect、move feature、delete selected —— 每项 undo 一次即回到
   动作前（`test_v10_transaction_invariants.py`）。
2. **undo/redo 不产生 EditDelta**（前向审计流纪律，V7 D7）。
3. **rollback 作废 delta journal**（`changes_since → None` 全量重建语义）。
4. **无绕过路径**：任何持久化矢量变更必经 VectorEditSession 命令
   （源码级扫描测试 + 生产路径 runtime 断言；legacy 场景与 domain import
   的既有豁免记录在案）。
5. **新命令族 delta 映射**：add/delete/move part → `replace_geometry`；
   duplicate → `create_feature`；explode → `split_feature`（replacements =
   related ids）；collect → `merge_features`。

## C. V10 新增命令类型登记

| 命令 | 类型串 | delta 操作 | 说明 |
|---|---|---|---|
| DuplicateFeatureCommand | `duplicate_feature` | create_feature | add 的审计区分类型 |
| AddPartCommand | `add_part` | replace_geometry | SetGeometry 子类 |
| DeletePartCommand | `delete_part` | replace_geometry | 同上 |
| MovePartCommand | `move_part` | replace_geometry | 同上（复用平移语义） |

ring 命令（`add_ring`/`delete_ring`）与 vertex 命令（`set_vertex`/
`insert_vertex`/`delete_vertex`）既有，仅补 ring 闭环维护。

## D. 提交/审计链（不变）

```
session.commit_changes → layer._commit（data_revision+1）
  → audit_history() → MapAuthoringDocument.edit_history
  → sync_to_project（仅 committed features → UserVectorLayer）
EditDelta.qgis_capability = snapshot_stable_hash（单一注入点）
```
