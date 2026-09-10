# 08 — 性能与规模（goal §34）

目标规模：10万+ catalog 实体 / 1000 层 / 10k 井。

## 已有路径（复用）

lazy catalog open（热读走 SQLite 不物化文档）、keyset 分页、O(1) id 映射、
lineage 有界（max 5000 + truncated 旗）、factor grid LRU（64 项/256MiB）、
DAG cache index、增量图层树同步。

## V9 增量

* 所有 V9 对象是投影/索引——零载荷复制（评审 R2 确认）；
* `factor_products()` 单次新鲜度评估复用（无 O(n²) 重评估）；
* 提交路径 payload 仅几何 JSON（小），catalog staging lease 管拷贝；
* 结构化输入集条目数 = 证据数（有界）；
* 规模结构测试：10k 井行 + 500 factor 任务下 evidence/projection 有界且
  身份唯一（tests/test_interpretation_v9_adversarial.py::test_scale_…）。

## 已知热点（沿基线，未恶化）

`MappingDependencyService.evaluate` 每次阶段切换全量评估 artifacts×versions
（基线 P1，1000 层量级可测量）；`compute_summaries` 全版本遍历。
V9 未新增全库扫描。
