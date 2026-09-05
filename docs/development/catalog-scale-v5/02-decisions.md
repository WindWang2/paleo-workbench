# Catalog Scale v5 — Decisions（架构决策记录）

原则：与现有架构最一致、风险最低、长期维护成本最低。不建第二权威。

## D-01 统一 Query API 放在 DataCatalogService（包装 CatalogIndex），UI 不再直持 index
现状 UI 在 `data_page.py` 直接 `service.index` 构造 `CatalogPageProvider`（绕过 service 边界）。
决策：service 增加只读查询门面（`search_assets_page` / `count_assets` / `catalog_aggregates`，签名与 Index 版本对齐并加 revision-guard 语义），provider 改为经 service 获取。SQLite 仍是唯一 canonical；service 门面只是查询缝，不复制状态。
理由：Catalog 单一权威边界（CONTEXT.md 不变量）不因 scale 被击穿；后续替换存储/加 FTS 只动一处。

## D-02 keyset 优先、offset 兜底；排序白名单扩展
现状 keyset 仅 name 序。决策：为可索引序（name、created_at、updated_at、type+id…）提供 keyset cursor；无法 keyset 的用户排序用 offset+LIMIT（页深有限，Qt 滚动模式可接受），ORDER BY 恒以 `id` 收尾保证 stable。不引入 RowID 语义变更。

## D-03 FTS5 决策以基准为准；预期采用「normalized LIKE + 前缀索引」而非 FTS5
现有 `assets.name_search`（NFKC+casefold）+ `idx_assets_name_search` 已服务 LIKE 'prefix%'。全文 `LIKE '%q%'` 在 10w 行内通常 <数十 ms；FTS5 引入 index_schema_version bump、全量重建、外部 token 化维护成本，且只优化 text 一个维度。
决策：先实测（bench 记录于 04-verification.md）；除非 LIKE 路径在 10w 级超预算（>100ms 中位），否则不启用 FTS5。任何升级仅动 Index 层。

## D-04 异步页取回用「单 worker QThread + latest-only 请求版本号」，不引入 TaskScheduler
导入/验证已有 OwnedWorkerJob 模式；页取回是高频短任务，TaskScheduler 的 FIFO+admission 过重。
决策：`PagedAssetTableModel` 持有一个常驻 worker（惰性创建、页面级任务、请求代数化：携带 `request_epoch`，过期结果丢弃）；cache 为有界 dict（默认 24 页 LRU，含游标）；SQLite 侧用 connection-per-thread（Index 已支持池化）+ 取消靠 epoch 丢弃（避免 sqlite3 interrupt 的跨线程复杂度）。页内当前版本列批取沿用 100/chunk。

## D-05 Missing Source 为「派生态 + 可审计 relink 事件」，不新增 authoritative missing 标志列
决策：`find_missing_sources()`（service API，stat-only，fsync/哈希不做）即时派生；UI 过滤/警告基于该 API 与 filter 谓词 `missing=true`（SQL 无法表达 fs 探针——paged 模式下 missing 视图按「候选集 from SQL + 后台 stat 校验」实现，物化候选而非全表）。relink 仅 external 版本：sha256/size 校验一致才允许更新 path/source_uri 并写 audit 事件；任何内容差异 → 拒绝（fail-closed），引导新 import/new version。managed payload 丢失不提供 relink（属损坏，需重导入）。
理由：避免每次扫描写库（写放大 + 多进程 revision 冲突）；audit 已有事件基础设施承载审计。

## D-06 relink 契约
- 允许：新文件 sha256 == 记录 sha256（mtime/size 可不同）→ 更新 external path + audit 事件。
- 允许：sha256 不可得（源已丢）但 size+mtime 与上次已知值一致 → 可选宽松档，默认关闭。
- 拒绝：sha256 不同 / 无法证明身份 → `CatalogRelinkIdentityError`。
- RAW managed 永不在原地改写；relink 不触碰 managed 路径。

## D-07 Tag 热路径：name→id dict map + 单遍大选择收集
决策：CatalogDocument 维护 `tags_by_name` map（与 `_CatalogMaps` 同点维护/重建）；`add_tags` 用增量替换而非整 map 深拷贝（保留 journal 回滚语义：失败恢复改为从 journal 反放而非全量快照——若风险高则保留快照但以 copy-on-write 结构降频）。UI `_prompt_remove_tag_from_assets` 改为对选中资产的 tag 并集一次收集。
理由：消除 per-op O(T) 与 O(N×T)；journal 机制（_TagJournal）已可精确反放。

## D-08 Version 工作台与 Lineage Explorer 为独立 QDialog（非 dock），全部走 service 门面
数据量小（单资产版本数、单节点邻接），同步取回可接受；不做常驻后台刷新。Lineage lazy expand：节点展开时按需查询直接父子（SQL 单跳，`lineage` 表两向索引），全局链路仍可走既有 `get_lineage_chain`（cap 5000）。

## D-09 导入进度/取消
决策：`_ImportWorker`/`_RegisterWorker` 增加协作式 cancel 标志 + 进度信号（每 N 文件 emit；发现阶段计 discovered/classified，登记阶段 registered/skipped/failed）；OwnedWorkerJob 已有 cancel 通道。事务语义不变（batch_save 整批单事务）；取消发生在发现阶段即中止，发生在登记阶段则该批完成后停止后续批次（chunk 化登记：每 500 资产一个 batch_save，兼顾内存与取消粒度，且单批失败不放大）。

## D-10 工程对象视图 = Catalog 上的 typed read model
复用 `catalog/domain_binding.py` + `project/domain.py` 的既有 DomainEntity 模型，在 NavigationTree/查询层增加 object-type 分组视图；不新增表、不新增文档字段（视图按 asset.metadata/domain binding 派生）。

## D-11 【修订】索引布局变更不 bump INDEX_SCHEMA_VERSION（superseded 初版）
初版曾计划 bump 到 v6；实现期发现两条硬约束推翻了它：
1. 纯 CREATE/DROP INDEX 是布局变更，连接时幂等 DDL 即可在任何旧库就地生效（沿 `idx_assets_name_id` 先例），不需要重建；
2. `INDEX_SCHEMA_VERSION` 与 `STORE_SCHEMA_VERSION` 共用 `sync_state.index_schema_version` 键，且 `load_document` 历史上将其与 STORE_SCHEMA_VERSION 做**等值**比较——单独 bump 会被误判为非 canonical store，进而从陈旧 manifest「重建」，这是潜在数据丢失路径。
落地：保持 INDEX_SCHEMA_VERSION=5；`load_document` 改为版本地板（≥5 即 canonical，可加载），由 `tests/test_catalog_paged_query.py::test_load_document_accepts_newer_index_layout` 钉死；新索引连接时幂等创建。任何**列级**变更仍按仓库既有 rebuild 机制处理。

## D-12 每次 lifecycle 操作后的全量 `_refresh()` 本轮不重写为增量事件总线
风险/收益权衡：增量刷新牵动 legacy projection/selection/inspector 全链，属独立大改造。本 Goal 的规模路径是「paged mode 下全量刷新本身走 SQL 聚合而非物化」，即让 `_refresh` 在 paged 模式下 O(page) 而非 O(N)。该点必须在实现中验证（update_state 在 paged 模式不得跑全量 enricher）。若发现无法回避的全量路径，记录为已知限制并给出量化证据。
