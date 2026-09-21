# 06 — Performance Baseline

## 1. 方法论

Prompt §15 要求 call-count/sync-count 结构断言为主，wall time 仅作 sanity。
载体：`workspace.layer_control_scale` + `ui_composite.layer_control`
（FakeStack 计数器）。测量机：本机（GCC 16.2.1 -O2，单线程主频不受控，
仅相对参考）。

## 2. 结构断言结果（全部通过）

| 场景 | 断言 | 结果 |
|---|---|---|
| 1000 层 / 20 组 reconcile | begin/end_window == 1；remove_groups_except == 1；apply_placements ≤ 1；move 调用 == 0 | ✅ |
| 幂等 reconcile（同输入二次） | upsert/placement 增量 == 0 | ✅ |
| 1000 层排序键 fresh | 键长恒 8（无增长） | ✅ |
| 1000 层单拖 | 键变更 ≤ 1 | ✅ |
| 1000 层全逆序 | 重排后键长 ≤ 65（阈值约束） | ✅ |
| 1000 层 diff 相同树 | 0 op | ✅ |
| 1000 层单交换 | move ∈ [1,2] | ✅ |
| 10×stage 切换（1000 层） | 既有键值零改写；set_group_visibility 调用 = 组数（非层数） | ✅ |
| usage 反查 10k runs | 条目 = 100 上限 + truncated=true | ✅ |

复杂度设计：LIS/LCS 均 O(N log N)（patience）；批量放置一次遍历建索引
（无 O(N²) `.index`）；树查询线性有界。10 轮 1000 层 shuffle 全管道
（diff+assign+build）实测 < 40ms（-O2，参考值）。

## 3. 已规避的既有热点（本线不重复 #1385/#1388 的租约范围）

- `mirror_snapshot.cpp` doc_id 线性扫描 → #1434 的 `build_doc_id_index`
  （本线只调用不重建）。
- `canvas_shim` 的 doc_id 扫描点（set_current_layer 等）→ 同上复用。
- 本线新增代码的查找全部走 `std::map`/`std::set` 索引；reconcile 放置
  走 seam 批量（栈侧一次索引化）。

## 4. 平台/QGIS 侧（待 SDK 环境测量）

- reconcile 收口 sync 次数（期望：每窗口 1 次 refresh）。
- stage 切换 ×100 的 canvas refresh 计数（QgsLayerTreeMapCanvasBridge 中间
  setLayers 为幂等；renderFlag 抑制后无中间重绘）。
- 1000 层 QgsLayerTree 实际批量放置耗时。
