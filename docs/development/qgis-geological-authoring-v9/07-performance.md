# 07 — Performance（V9）

## 1. §26 门对照

| 门 | 状态 |
|---|---|
| 单要素编辑 ≠ 全量 republish | 既有 ledger/feature-delta（V7）未动；`test_mirror_publish_scale` 增量/no-op 用例通过 |
| 图层状态变化 ≠ 全树重建 | 既有；role 标注是快照字段级增量（无额外遍历——`role_of_layer` O(1) 字典查询） |
| pan/zoom ≠ 全 availability 重算 | V8 轻路径（checked-only）确认未动；V9 的 `scale_denominator` 只在上下文构建时读（pan 不构建上下文） |
| 选集变化 ≠ 全数据扫描 | split/merge readiness 维持 O(layers+选集)（审计确认无 feature 全扫；不引入缓存以避免陈旧正确性风险——03 决策记录） |

## 2. V9 新增代价核算

| 新代价 | 量级 | 位置 |
|---|---|---|
| `cached_error_count` 上下文读 | O(层数) 字典读 | 帧级链安全（刷新点才 O(要素)） |
| `_mapping_blocking_task_label` | `statuses()` 快照遍历（活动任务数级） | 每次上下文构建 |
| `canvas_scale`/destination CRS | 桥 getter 单调用 | 每次上下文构建 / 每次数字化提交 |
| `_verify_published_schema` | 仅带 fields_json 的发布层；O(字段) 读回比对 | 发布路径（no-op 层跳过） |
| 属性表 parity | 全量 refresh 各一次桥自省 | 不在帧级链 |
| 测地测量 | pyproj Geod.inv 每次点击 | O(1) |

## 3. 门禁运行记录

- `test_perf_lifecycle_v8`（evaluate_all 线性/廉价、extent 无全量重算、
  满载活动层切换有界、重复命令分发稳定）：**6/6 通过**（本 worktree）。
- `tests/perf/test_mirror_publish_scale`：14 用例中 13 通过；
  `test_full_first_publish_within_budget[50]`（167.6ms vs 60ms 预算）在
  **V8 基线 worktree 同样失败**（同机同桥对照）——预存环境性失败
  （CI qgis 腿覆盖），非 V9 回归。证据：
  `paleo-workbench-v8-spatial` 上同用例同失败。

## 4. 100k 级承诺面

V8 既有：记录序列化修订键控缓存（数字化点击只重编码变化层）、属性表
差量刷新（V6 C-P0-3，V9 保留并修排序态错行）、树模型差分。V9 未新增
任何 O(全量) 路径；1000 层门（no-op publish 30ms 预算）在既有测试中
维持。
