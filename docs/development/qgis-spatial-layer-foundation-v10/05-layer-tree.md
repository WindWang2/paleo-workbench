# 05 — Layer tree（V10）

## 1. 权威结构（不变）

- **QgsLayerTree 是运行时树权威**；`LayerGroupController` 持 desired-tree
  做 reconcile（期望态 → QGIS 树执行），无第二棵树。
- 该分工自 V7 起裁定，V8/V9 复核维持
  （docs/development/qgis-geological-authoring-v9/00-baseline.md §C2
  「保留」项）。
- 组结构（membership）唯一 reconcile 对象；层呈现（样式/可见域/
  名称）走发布面（qgis_mirror，07-rendering.md），不经树。

## 2. V10 对树模型的贡献：零

V10 不给树模型新增任何表面——不加节点类型、不加平行树、不加第二
reconcile 通道、不改 writeback 语义。goal F「深化而不扩张」在本域的
满足方式就是**不建新面**：V10 的全部预算投向运行时基础
（01-qgis-runtime.md）、CRS 链（02-crs-transform.md）、账本
（04-layer-registry.md）与 provider 事实（06-provider-schema.md），
树仅作为这些改动的既有承载面。

这本身是审计结论：起点审计未发现树 reconcile 路径的新缺陷
（00-baseline.md §B 的 11 项缺口无一落在树模型），无缺陷即无扩张
授权。

## 3. 语义回归钉（既有，V10 复核未动）

- hoist 语义：`test_remove_groups_except_hoists_layers_never_deletes`
  （tests/test_qgis_layer_groups.py:111）——删组提升子层、永不删层。
- no-echo 语义：`test_group_visibility_programmatic_does_not_echo`
  （tests/test_qgis_layer_groups.py:127）、
  `test_programmatic_group_operations_do_not_echo`
  （tests/test_qgis_layer_groups.py:165）——编程态变化不回灌
  desired-tree reconcile。
- 树语义回归文件（tests/test_native_layer_tree.py、
  tests/test_qgis_layer_groups.py、tests/test_qgis_layertree_embed.py、
  tests/test_qgis_layertree_writeback.py）全量通过是合入前置条件。
- V10 的 name token（04-layer-registry.md §2）只影响发布判定，不进
  树 reconcile 路径——改名重发后 `setName` 生效，树节点呈现随 QGIS
  自身信号更新，desired-tree 不感知 name（组结构唯一 reconcile 对象）。
