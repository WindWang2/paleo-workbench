# 01 — Lazy Catalog（#1212）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 1. 问题

`DataCatalogService.open` 把 SQLite 全部行物化为 Pydantic + `_ensure_maps` 二次 O(N) 全在 GUI 线程（`db.py:_load_document_once`、`service.py:_ensure_maps`），且 `ensure_index` 形参是死参数——控制器传 `ensure_index=False` 什么都没推迟。10 万资产 = 秒级打开阻塞 + 全量 RSS（本机 20k 实测急切重开 33s）。

## 2. 目标形态（已实现）

```
Canonical Store (catalog.sqlite, WAL)
      ↓ store_health/revision 探针（open 全部工作）
Lazy Hot Reads（按 id 行→模型 / SQL 分页计数聚合 / 一跳 lineage）
      ↓ 后台 warm_document() 或首个变更/全量读触发内联物化
Warm Document + _CatalogMaps（与 v5 行为逐字节一致）
```

- `open(lazy=True)`：空文档 + 存储 revision 基线；健康/损坏隔离/清单 mtime 记账照旧。
- 热读 API 预热期直达存储：`get_asset/get_version/get_run/list_assets/get_trashed_assets/list_runs/list_versions/list_all_versions/search_assets_page/count_assets/cached_catalog_aggregates/catalog_aggregates/search_assets/get_lineage/resolve_asset_models`（`_lazy_read_cache` 保持窗口内对象身份稳定；未知 id 干净抛错，不触发物化）。
- 收敛不变量：**任何变更意味着已 warm**——68 个全文档方法经 `_WARM_REQUIRED_METHODS` 装饰器在入口 `require_warm()`（急切服务 `_warm=True` 出生，装饰器为零开销旗标检查，非懒会话行为逐字节不变）。
- `warm_document()` 后台线程：无锁 load → 锁内 revision 复核 + 一次性换文档（无合并逻辑，correct-by-construction）；内联 `require_warm` 与之竞争安全（任一方赢，另一方丢弃）。
- 预热期 revision 漂移（外部进程提交）：**信任存储**（漂移只可能来自外来提交；本进程变更必已 warm）——分页/搜索/聚合永不因空文档回退而返回错误空结果（评审 R1#1/R2#3 修复）。
- 零变更懒会话 `close()` 跳过清单重写（mtime 基线证明清单已与存储同步）。
- 控制器：`_open_catalog` 懒打开；维护线程 warm → 工作副本恢复 → 幽灵 run 修复 → 迁移/清扫/索引 → 地震 resume。

## 3. 兼容性

- DataCatalogService 仍是唯一公开权威；UI/业务不触 SQLite。
- adapter（CatalogPort 缝隙）`list_versions/list_runs/_tag_*/_asset_for/_find_*` 全部懒感知；`queries.search_assets` 索引行不再在预热期被空 maps 过滤为空。
- 删除死参数 `ensure_index`（仓库内全部调用点已更新）。
- 新公共 API：`open(lazy=)`、`warm_document`、`require_warm`、`is_warm`、`list_all_versions`、`resolve_asset_models`。

## 4. 实测

本机（Windows，Defender+fsync 慢盘）20k 生产路径：懒打开 **13.2ms**；急切重开 33,072ms。CI 门（tests/test_catalog_scale_v6.py + test_catalog_lazy_open.py）：懒打开 <500ms、页 <150/200ms、get <10ms、warm 期间查询正确、eager/lazy 等价性、warm-变更竞态。
