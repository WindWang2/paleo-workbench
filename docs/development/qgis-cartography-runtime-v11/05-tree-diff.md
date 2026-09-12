# 05 — Tree Diff (V11)

## 1. 设计

`LayerTreePlan` 产期望树 → `diff_trees(current, desired)` 产最小操作集 →
`_apply_tree` 在原生事务窗口内执行。current = `_last_applied`（增量基线；
force/reload 后为空树 = 全量）。

## 2. 操作集

| 操作 | 语义 |
|---|---|
| GroupCreate(group_id, name, parent) | 拓扑序输出（父先于子）；桥 upsert_group |
| GroupRemove(group_id) | keep-set 清理（removeGroupsExcept，上提子节点，绝不删层） |
| GroupRename(group_id, new_name) | 桥 rename_group |
| GroupMove(group_id, new_parent, new_index) | 桥 move_group |
| LayerMove(layer_id, new_parent, new_index) | 桥 move_layer_to_group |
| GroupStateSet(group_id, kind, value) | 报告用（visible/expanded/locked 由专职路径应用，不双写） |

## 3. LCS 匹配（per-container）

每个容器（组 / root）独立对其子 id 序列求 current↔desired 的 LCS——
属于 LCS 的位置已保序就位，不发 move；其余按目标位置逐个 move。
复杂度 O(n log n)（patience 归约）；等长同序快路径 O(n)。

全反序（LCS=1）→ n-1 个 move（结构性最小：任何保序方案的下界）；
单层插入 → 恰 1 move；no-op → 0 ops（1000 层亦然，测试钉死）。

## 4. 应用映射

`_apply_tree`：creates（拓扑序）→ renames → keep-set 清理 →
moves 子集批应用（`apply_tree_placements` 一次桥调用；旧桥逐 move 回落）。
显隐/展开不在本路径（`apply_stage_visibility`/`apply_group_expanded`
专职，避免双写对抗）。失败重抛，`_last_applied` 不变（下次重试）。
