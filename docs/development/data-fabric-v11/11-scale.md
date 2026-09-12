# 11 — Scale（10 万级资产）

## 1. 契约（继承 + 新增）

继承：分页 SQL、lazy 实体读、warm-up 守卫、图缓存、单写者批事务。

新增约束：

| 面 | 约束 |
|---|---|
| 实体树根层 | O(W)（井 ≤10k）内存组装；每井摘要 = links 聚合，无 catalog 全量 |
| 树展开 | 每次展开 = 批量点查（≤500 id/批）+ 分页版本列表 |
| unassigned 桶 | search_assets_page 分页，禁止全量 |
| impact/staleness | 层级批量 IN 扩展；缓存 (revision, serial, scope)；节点上限 + 截断标记 |
| explain | 单版本闭包（受界）+ 单 run 点查 |
| bundle | 成员数软上限（默认 64/版本）防误导入目录成巨型 bundle |
| ports | 每 run 端口数软上限（默认 256） |
| 写路径 | batch_save 合并；ports/members 行随所属 run/version 同事务 |

## 2. 结构性验证（不依赖 wall-clock）

- 10k 井 × 10 链接 × 多版本：树根组装/展开的 SQL 次数为 O(分批)，
  断言查询计数而非耗时。
- 100k 资产：实体树根层不发出 list_assets()（以调用计数钉住）。
- lineage 闭包深度：构造 N 层链，断言扩展批量数 = O(深度) 而非 O(节点)。
- 现有 perf 套件（tests/perf/）继续通过。

## 3. 风险与缓解

- links 列表本身在 ProjectDocument（内存全量）：10k 井 × 8 角色 × 平均
  2.5 资产 ≈ 200k links —— Pydantic 文档加载代价已在现状承受范围
  （同量级 resources）；如后续成为瓶颈，links 索引化（per-entity 分片）
  是 V12 方向，本 Goal 不做（记录于 12-known-limitations）。
- impact 全图闭包的病态星型图：节点上限截断 + 报告"结果被截断"。
