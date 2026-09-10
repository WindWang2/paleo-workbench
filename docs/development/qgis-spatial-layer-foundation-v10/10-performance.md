# 10 — Performance（V10）

## 1. 发布环预算（不变）

发布环维持同步、既有预算钉
（tests/perf/test_mirror_publish_scale.py）：

| 层数 | 全量首发预算 | no-op 重发预算 |
|---|---|---|
| 50 | 60ms | 8ms |
| 200 | 240ms | 30ms |
| 500 | 700ms | 80ms |
| 1000 | 1600ms | 180ms |

## 2. token 增量代价（O(1)/层）

- name token + scale_range token 加入 no-op 比较（04-layer-registry.md
  §2）——每层两次哈希/元组比较，常量级，不改变 no-op 路径复杂度。
- **改名后的 no-op 重发布 = 一次单层 upsert**：预算等价于单层
  style-only 路径（既有单层用例覆盖该量级），不触发全量重发。

## 3. native-apply 大层数探针（实测）

`tests/perf/test_qgis_v10_native_scale.py`（qgis-marked，无桥跳过），
本机实测（2026-09-11，conda 配方）：

| 层数 | 原生全量发布 | 预算 |
|---|---|---|
| 200 | ~1.4s | 900ms 起校准 |
| 500 | ~3.2s | 2400ms |
| 1000 | ~7.5s | 9000ms |

**已知特性**：`upsertMirrorLayer` 每次触发 `syncCanvasLayers`——
全量发布渐近 O(n²)（1000 层 ≈ 7.5ms/层）。全量发布是一次性成本；
交互相关路径走廉价通道并有独立预算（500 层可见性翻转 < 2s 实测
通过；no-op 判定 O(1) token 比较）。批量发布 API（一次 upsert 组、
末尾单次 sync）列为后续优化面，不在本集合。

## 4. provider facts 探针代价

`mirror_provider_facts` 是每次 ToolContext 构建**一次 C++ 调用**，
调用内缓存 dict——同次构建的多次读取（`_writable_gate` 等）不再过桥。
无自省面（None）时零调用。

## 5. §26 门对照（沿 V9 07 格式）

| 门 | 状态 |
|---|---|
| 单要素编辑 ≠ 全量 republish | 既有 ledger/feature-delta 维持；token 化只增判定维度不增遍历 |
| 图层状态变化 ≠ 全树重建 | 维持；name/scale 失配走单层 upsert |
| pan/zoom ≠ 全 availability 重算 | V8 轻路径维持；scale_denominator 仍只在上下文构建时读 |
| 探针/诊断 ≠ 帧级链 | runtime_facts/health 进程级一次性；provider facts 每 ToolContext 构建一次 C++ 调用 |

## 6. 100k 级承诺面

V8/V9 既有：记录序列化修订键控缓存、属性表差量刷新、树模型差分。
V10 未新增任何 O(全量) 路径；`runtime_facts`/health 探针是一次性
进程级成本（12-known-limitations.md 第 8 条），不进帧级链。
100GB seismic 零接触（00-baseline.md §E）。
