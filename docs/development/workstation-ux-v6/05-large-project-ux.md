# Workstation UX V6 — 05 大工程 UI 规模

Date: 2026-09-07 · 生产尺度：100k 资产 / 10k 井 / 5k 要素 / 1000 图层

## 1. 已关闭的旁路（baseline C 家族，全部 TDD + 结构性断言）

| 旁路 | 修复 | 证据测试 |
|------|------|----------|
| 工区概览点击全量物化计数（100k 多秒冻结）；普通刷新显示清零计数 | 大目录（≥25k）从 `cached_catalog_aggregates()` 供给；冷缓存转既有 `_AggregatesWorker` 线程，期间「—」不伪造 | `test_data_overview_perf.py`（spy 证明零物化调用） |
| 完整性智能视图 ≥25k 退出分页全量重建 | 未在本轮修复（诚实遗留，见 10） | — |
| 属性表每次编辑全量重建行+组合框 | mapping_page：编辑会话日志 `changes_since` 增量；composite 表：同会话 content_changed 只 setText 触及单元格；组合框按 id 集签名门控 | `test_attribute_table_differential.py`（计数不随 n 缩放；2000 要素单编辑 <2s 仅为 backstop） |
| 地层对比井列表每次 update_state 全量重建 | 稳定 key→item 差分；选择/滚动/勾选保留 | `test_large_list_differential.py` |
| 预测/可视化组合框每次重填 + 逐条 `Path.is_file` | 签名门控 + 按源修订的探针缓存 | 同上 |
| 捕捉对话框每层 5 widget（1000 层=5000） | item 化行（≤50 widget @1000 层），accept() 写回契约不变 | 同上 |
| 回收站徽标全量同伴计算 | 分页模式 SQL COUNT；物化分支才做同伴重建 | `test_data_overview_perf.py` |
| legacy/name 映射每修订全量走查 + 缓存永不失效（读了不存在的属性） | 修订键缓存 + 修复 `catalog_revision` 属性来源 | 同上 |

## 2. 判定纪律

- **不伪造基准**：测试断言结构性界限（行创建数/调用数/探针数为常数或 Δ），墙钟仅作宽松 backstop；报告环境为 Windows/offscreen（见 09）。
- 既有分页契约（keyset、SQL 排序、不可映射过滤器诚实拒绝、<50ms/页 & <100ms/计数 @100k 的测试钉子）未动。

## 3. 未达标/未做（诚实）

- 完整性智能视图 100k 路径仍走物化回退（需要 SQL 化完整性谓词——设计上 fs probe 不可映射；方案：离线程扫描 + 「—」占位，未实施）。
- 镜像发布全层重序列化（B-P1-1，1000 层重绘噪声热点）与 fallback 树全量重建（B-P1-4）未在本轮处理。
- `group_summary` 聚合尚无树 UI 消费者。
