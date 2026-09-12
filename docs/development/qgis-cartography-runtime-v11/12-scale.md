# 12 — Scale (V11)

## 1. 结构性断言（非计时门禁）

| 场景 | 断言 |
|---|---|
| 1000 层初始构建 | 组 upsert ≤20；放置批量 = 1 调用（plan）/ 单窗口单同步（native） |
| 单层插入 | diff 恰 1 move；发布单窗口单同步 |
| 组移动 | 有界 ops（≤3，单挂载回归） |
| 二次 reconcile | 0 moves |
| 阶段切换 | 0 结构调用 |
| 重命名 | diff 恰 1 rename（零放置扰动） |
| 栅格未动 | 0 桥调用 |
| 单点扰动（300 要素） | 1 次重签；delta 恰触及要素 |

## 2. 关闭的 O(N²)

* `known_ids.index`（factor sort）→ `FACTOR_ROLE_RANK` dict。
* `_place_delta` 兄弟扇出 → diff 子集批应用。
* `upsert_group` × G 全量 → diff creates（拓扑序）+ keep-set。
* 全量逐要素签名 → changed_hints 快道 + 缓存。
* 栅格逐发布重调 → raster ledger。
* 中点键插入 O(1)；LIS 保键（用户拖动最小扰动）。

## 3. 残留热路径（已知，未关）

* `_group_summaries` O(G×M)（debounced UI 路径；待虚拟化）。
* presentation per-layer profile 重建 O(N×G)（dict churn；待缓存）。
* panel `_layers.index` 惯用法（UI 规模可接受；待 id 索引）。
* `_place_delta` 已删除（diff 替代）；`flatten_for_render`/`profile_group_order`
  等死 API 未删（待清理轮）。
