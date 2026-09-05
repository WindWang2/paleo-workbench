# Catalog Scale v5 — Baseline（D0 审计，以源码为准）

日期：2026-09-06 · worktree `/home/kevin/projects/paleo-wt-catalog-scale-v5` · branch `feat/catalog-scale-v5` · base `049423ab`

## 1. 现有架构事实（file:line 均相对 `paleo_workbench/`）

### 1.1 权威与存储
- Canonical store = `catalog.sqlite`（WAL），位于 `<project>.artifacts/metadata/catalog.sqlite`（`catalog/db.py:31,616-618`）；`catalog.json` 仅是 close/export checkpoint manifest（`catalog/store.py:1-12`，`catalog/service.py:813-837`）。
- Schema version：`STORE_SCHEMA_VERSION = INDEX_SCHEMA_VERSION = 5`（`catalog/db.py:84-85`）；无 ALTER 迁移——版本不符即判定 legacy 并从事务性全量重建（`catalog/db.py:832-981`，open flow `catalog/service.py:664-786`）。
- 写入全部经 `DataCatalogService`：每个 mutator 构建 `DirtySet` → `_save` → `index.apply_changes` 单事务 upsert（`catalog/db.py:1156-1340`，事务在 :1223）。`batch_save()`（`catalog/service.py:959-973`，`_BatchSave` :146-210）合并为单事务+单 revision bump。
- Cross-process stale-write guard #411：flush/export_manifest 比较 `_flushed_revision`（`catalog/service.py:211-219,829-834,884-889`）。
- Crash consistency：WAL + busy_timeout=5000（`catalog/db.py:763-769`）；未显式设置 `synchronous`；payload temp+fsync+rename+read-only bit（`catalog/storage.py:436-465`）；trash 先 tombstone 后 move + 崩溃恢复探针（`catalog/service.py:2402-2467`）。

### 1.2 查询层现状
- `CatalogIndex.search_assets_page`（`catalog/db.py:1877-1978`）：LIMIT/OFFSET + (name,id) keyset（仅 name 序 :1941-1944）、order 白名单 `_PAGE_ORDER_COLUMNS` :1867-1875、current-version 列分块(100)批取 :1955-1964、default limit=500；`count_assets` :1980-2024；`catalog_aggregates` :2026-2076。
- `DataCatalogService.search_assets`（`catalog/service.py:3170-3202` → `catalog/queries.py:90-195`）返回全量 materialized list；index 路径 revision guard 失败或任意异常 → 裸 `except Exception: pass` 回退 O(N) Python 扫描（`catalog/queries.py:150-151`）。
- `list_assets/list_runs/list_versions` 全量物化（`catalog/service.py:1123-1138`）；`adapter.list_versions/list_runs` 每行做 `resolve_path`（含 stat/identity 校验，`catalog/adapter.py:787-810`，`catalog/service.py:1140-1199`）。
- Lineage：materialized edge 表 `lineage(parent_version_id,child_version_id)`（`catalog/db.py:174-179`），仅有 `idx_lineage_child`，**无 parent 索引**；ancestors/descendants 是 Python BFS（`catalog/lineage_graph.py:112-174`，cap 5000；`catalog/adapter.py:695-748`）；无递归 CTE。

### 1.3 UI（DataPage）现状
- 经典路径：`AssetTableModel` 持有全部资产三平行列表（`ui/pages/asset_table_model.py:113-118`），一切更新走 `beginResetModel` 全量 reset（:151-219）；`FilterIndex.filter_query` 每 keystroke O(N) 线性扫 + needle in haystack（`ui/pages/filter_index.py:188-285`）。
- 分页路径：`PAGED_MODE_THRESHOLD = 25_000`、`PAGE_SIZE = 500`（`ui/pages/paged_asset_model.py:40-41`）；`CatalogPageProvider` 直持 raw `CatalogIndex`（`data_page.py:624-645` 构造）；`canFetchMore/fetchMore` 逐页插入、rowCount 返回总数、未取行渲染"…"、排序重查 SQL（`paged_asset_model.py:311-374`）。**页取回为 GUI 线程同步 SQL**；integrity/entity/auxiliary/review_status 视图 unmappable 回退物化路径（:45,174-177）。
- 刷新模型：一切以 FULL refresh 结束——所有 lifecycle action 末尾 `page._refresh()`（`ui/data_lifecycle_controller.py:378,505,545,626,711,843,905,941`）；`update_state` 每次对全部资产跑 `catalog_row_overview`（revision-keyed 缓存，`ui/pages/data_view_models.py:832-914`）+ `catalog_only_rows`（`data_lifecycle_controller.py:312-365`）。
- 选择持久化：`DataAssetTable._sync_selection` 按 key=("artifact"|"resource",id) 重建并收缩（`ui/pages/data_asset_table.py:519-570`）。
- Worker 模式：parentless QObject + `OwnedWorkerJob`（`ui/owned_worker_job.py:13-231`），DataPage 持 8 job（`data_page.py:283-294`）；表数据加载未线程化。

### 1.4 导入管线现状
- UI 入口 → `_ImportWorker`（QThread）→ `import_files/import_folder`（`resources/import_service.py:235,272`）→ `_RegisterWorker` → `register_imported_resources` 全程包 `catalog.batch_save()`（`ui/data_lifecycle_controller.py:1457-1502`）——元数据写入已单事务化（#849-3/#1027），无 O(N²) 保存。
- 分类：扩展名+路径关键词（`resources/classifier.py:6-104`）；`.xml` <2MB 内容探针；GeoJSON <2MB probe（`import_service.py:116-180`）。
- 指纹：legacy ImportReport 不哈希（checksum=None）；catalog 层 `register_resource_input` 惰性 sha256（`catalog/lifecycle.py:77-81`）；dedup 走 index O(logN) + batch overlay（#1139，`catalog/adapter.py:315-383`）。
- Managed vs external：`relativize_path`（`project/paths.py:274-296`）项目内=managed copy（hash-while-copy 单遍，`catalog/storage.py:371-465`），项目外=external link 不拷贝不哈希（`catalog/service.py:1697-1748`）。
- **缺**：无进度信号（worker 只发 finished/failed）、无取消、无 pause、无 import receipt 对话框/持久化；重扫无 `skip_checksum_over_bytes` 传入（`data_lifecycle_controller.py:580-582`）。

### 1.5 Tag / Version / Missing / Relink 现状
- Tag：`tags/asset_tags/version_tags` 表 + 文档内 map（`catalog/db.py:135-152`，`catalog/models.py:219-221`）；名字解析线性扫 `document.tags`（`catalog/tags.py:89-94`，`catalog/service.py:3038-3042`）；`add_tags` 每次深拷贝两个关联 map（`catalog/service.py:2983-2990`）；UI 移除 tag 前对每个选中资产做 O(tags×find_assets_by_tag) 扫（`data_page.py:2035-2042`）。bulk_add/remove 已批（`catalog/tags.py:336-447`）。
- Version：不可变契约（`catalog/models.py:9-14`，service 层 `catalog/service.py:1289-1302,1349-1353`）；promote=复制产生新版本+promote run（:2813-2903）；UI 侧仅 inspector 版本表+对话框，无 timeline 工作台。
- Missing：分散检测（rescan `data_lifecycle_controller.py:565-577`、投影 :1417、`verify_integrity`、audit `external_path_missing`、freshness MISSING_PAYLOAD、filter_index 缺失行）；**无正式 Missing Source 状态、无 relink 全流程**（grep 仅测试注释）。
- Lineage UI：inspector `LineageTreeWidget`（`ui/pages/inspector_panel.py:94-266`）+ 表列状态文本；无独立 explorer、无 lazy expand。

### 1.6 既有规模测试/基准
- `tests/test_catalog_scale.py`：ratio 断言（LINEAR_CEILING=5.0/SUB_LINEAR=2.5/FLOOR_MS=20），env `CATALOG_SCALE_N`（默认 64）。
- `tests/perf/test_catalog_scale.py`：`capacity`+`slow` marker，20k 真实 import_raw 批量种子。
- `tests/test_paged_catalog_mode.py`：100k 行索引 module-scope fixture，page<50ms、count/search<100ms。
- `benchmarks/catalog_scale_benchmark.py`（10k/50k/100k 单操作预算）；`scripts/benchmark_catalog_100k.py`（#1027 验收，RSS 报告）。
- 运行方式：`scripts/run_tests.sh workbench [pytest args]`（conda `paleo312`，offscreen）。

## 2. Baseline 测试结果

见 `04-verification.md` §Baseline（首次运行记录）。

## 3. 结论：真实差距（相对 Goal）

1. **Query API 停在 Index 层**：service/adapter 仍 list-everything；UI 直接拿 `service.index` 组 provider（绕过 service 边界）。
2. **页取回同步于 GUI 线程**，无取消/无 latest-only/无 prefetch/无有界 cache（除 SQL 层 limit）。
3. **lineage 反向（parent）查询无索引**；无递归 CTE；独立 explorer 缺失。
4. **Missing Source / Relink 全缺失**。
5. **导入无进度/取消/收据**。
6. **Tag 热路径 O(N) 线性扫 + UI O(N×T)**。
7. **Version 工作台 UI 缺失**（能力在 service 已全）。
8. 每个操作全量 `_refresh()`（大目录下 100k 时不可接受）——本 Goal 以 paged mode + 增量事件逐步缓解，全面增量刷新不在此 Goal 强制（见 target-state 标注）。
