# 10 — Performance Baseline（V13）

## 方法论

延续仓库反 wall-clock 立场：结构性断言（查询计数/调用计数/无全量扫描）
优先；本 Goal 未引入新的 O(N) 全量路径，以下为新增面的结构性证据。

## 新增面的复杂度账

| 面 | 复杂度 | 证据/设计 |
|---|---|---|
| usages_of_version | O(memberships + tasks + sets + products) + run 查询有界(100, truncated) | source_usage.py 单次线性扫内存小集合 |
| usages_of_asset | O(资产版本数 × usages_of_version(include_runs=False)) + 去重 | 版本数典型 1-几十 |
| impact 门（remove 前） | O(受影响资产数 × delete_impact) | delete_impact 自身 MAX 20k/2k + LRU |
| Inspector 地图用途行 | 同 usages_of_asset，选中时单次 | provider 注入，无刷新风暴 |
| IngestPlanDialog 表 | ObjectTableModel 虚拟行（零 item-per-cell）+ limit_items≤5000 | 构建在 worker 线程 |
| manual_edit run 簿记 | O(1) run 登记 + ports 预算内 | register_run/set_run_ports |
| 图层显隐/不透明度覆盖记录 | O(1) dict 写 | 手势入口，非批量路径 |
| stage 切换目标恢复 | O(1) 探针 + membership 查 | _target_layer_exists |

## 既有规模护栏（复验通过，未回归）

- test_v11_scale（查询计数 pin）、test_v11_performance_structural
  （模型重置/调用计数上限）、test_runtime_scale_v11（同步调用数上限）
  ——本分支全绿（见 15-verification）。
- 分页 UI 阈值与实体分页未动。

## 明确未做（scale 债务，诚实）

- lineage/impact SQL 递归 CTE 化（仍走内存文档遍历——10k 井基线
  由 V11 scale 测试覆盖，更大规模是 V14+ 议题）；
- entity_staleness 增量化（仍全量 downstream_stale 后过滤 + LRU）；
- usages 的持久化索引（当前规模无需）。
