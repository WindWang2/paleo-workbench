# CONV-31b R2 recon — db.py 惰性读 / working-copy / lease 写侧 / SQL 查询：语义契约与 C++ API 冻结

范围（D6，31-decisions.md）：`paleo_workbench/catalog/db.py` 的
① 14 个惰性单实体读（1745-1949）；② working-copy CRUD（1335-1425）；
③ staging lease 写侧（1227-1331，读侧 active_staging_targets 已在 gc.hpp）；
④ 查询缺口：search_assets(2631)/catalog_aggregates(2992)/list_versions(3044)/
lineage_edges(3055)/assets_for_tag(3079)/versions_for_tag(3093)/
find_managed_raw(3107)/find_external_by_path(3128)；
⑤ 辅助 metadata_search_value(253)/like_escape_literal(268) 的归属。
apply_changes/DirtySet/CAS 归 R1；本文件只钉读/簿记侧契约与接口点。
行号锚点基于 branch `feat/cpp-catalog-service` 当前 HEAD 的 db.py（3142 行）。

对照现状：C++ 已有 paged_sql.hpp/cpp（分页谓词/键集游标/100-id 批取）、
queries.hpp/cpp（**文档扫描路径** + metadata_search_value 已导出）、
entity_view.hpp（normalize_search_name/normalize_tag_name，ASCII fold 边界=
15-decisions D6）、models.hpp（WorkingCopy/StagingLease/Tag/DataRun 已有）、
document_index.hpp（managed_raw_for/external_for 内存键）、repository.hpp/cpp
（insert/remove/set_state 三个窄写 + load_document 全表加载先例）。
vendored SQLite 3.45.1（JSON 函数为内建核心，3.38+ 无需 SQLITE_ENABLE_JSON1）。

---

## ① 语义契约（逐函数逐分支）

### 1.0 两条降级通道（所有函数共用的前置契约）

Python 有**两种**错误形状，分属两组函数——这是最容易移植错的地方：

- **`_read_rows(sql, params)`（1736-1743）**——惰性读与 WC 读用它：
  1. `db_path` 文件不存在 → 直接 `[]`（不连接）；
  2. `_schema_present(conn)`（sqlite_master 有 sync_state 表，1172-1185）为假 → `[]`；
  3. 其余 sqlite3 错误**向上抛**——由**服务层** `try/except Exception` 吞掉后走
     warm 回退（service.py:1331-1339：读失败 → require_warm() → 全量加载）。
  即：缺文件/无 schema = 静默 miss；锁死/损坏 = 异常 → 服务层降级。
- **`_safe(default, fn)`（2620-2629）**——查询函数（search_assets 等 8 个）用它：
  文件不存在 → 掉连接 + 返回 default；`sqlite3.DatabaseError/OSError` → 掉连接 +
  返回 default。**查询永不抛**（含 "no such table"——OperationalError 是
  DatabaseError 子类）。

**C++ 冻结口径**（单连接模型下的如实降级）：所有新读函数统一
"prepare 失败 / 表缺失 / step 出错 → 返回 default，永不抛"。
理由：(a) 查询组 Python 本就 _safe；(b) 惰性读组的"抛→服务层 warm 回退"
依赖 Python 懒开形态（#1212），C++ 单连接由服务持有、无跨线程池竞争，
把降级折叠进函数即等价于 Python 组合后的净行为。
**已知边界**（如实记录，见 ⑤-1）：Python 中"锁死读失败"会让 get_asset 走
warm 路径而不是报 Unknown asset；C++ 折叠后 nullopt 无法区分 miss 与
unreadable，31b 服务组合层若在 pre-warm 把 nullopt 当 unknown-id 报错，
锁死场景行为不同——接受为有界偏离（busy_timeout 5000ms 下窗口极小）。

### 1.1 惰性单实体读（db.py:1745-1949；#1212）

总纲（1729-1734 注释）：行序 = load_document 的 rowid 序——惰性结果与
eager 文档**逐字节可替换**。这是冻结的第一不变量。

| 函数 | 行号 | SQL 形状（冻结文本） | 返回/排序保证 |
|---|---|---|---|
| `get_asset_model(asset_id)` | 1745 | `SELECT * FROM assets WHERE id = ?` | 行→DataAsset；无行→None。PK 点查无序问题 |
| `get_asset_models(ids)` | 1749 | 500-id 分块 `WHERE id IN (?,…)` | **dict 插入序 = 请求 id 首见序**（不是行序！）；`asset_id not in out` 去重，首次出现胜出 |
| `get_version_model(version_id)` | 1770 | versions 点查 + `_attach_members([v])`（version_members 表存在才挂，1885-1896） | 无 members 表 → members=[]（pre-V11 语义等价） |
| `get_run_model(run_id)` | 1778 | runs 点查 + `SELECT version_id FROM run_inputs WHERE run_id = ? ORDER BY rowid` + run_outputs 同形 + `_ports_for_runs`（500 分块、`ORDER BY rowid`，167-180） | inputs/outputs 序 = 链接表 rowid 序 = 写入列表序；ports：`direction == "output"` → output_ports，**其余任意值→input_ports**（148-164 的 else 分支） |
| `list_asset_models(*, include_trashed=True, trashed_only=False)` | 1803 | 三分支：trashed_only→`WHERE trashed = 1`；elif include_trashed→无谓词；else→`WHERE trashed = 0`。均 `ORDER BY rowid` | 注意默认值 include_trashed=True（与下一条相反） |
| `list_asset_identity_rows(*, include_trashed=False)` | 1818 | `SELECT id, name, legacy_resource_id FROM assets [WHERE trashed = 0] ORDER BY rowid` | `(id, name, legacy_resource_id)` 三元组；`str(row[...] or "")`——NULL/None 归一为 ""（#1269：不水化 DataAsset） |
| `list_run_models()` | 1838 | 全表 `ORDER BY rowid` + run_inputs/run_outputs 全表扫（setdefault 按 run 分桶，桶内 = 表 rowid 序）+ ports 表存在则挂 | 与 load_document 的 runs 完全同构 |
| `list_version_models_for_asset(asset_id)` | 1869 | `WHERE asset_id = ? ORDER BY rowid` + members 挂载 | 注释明说：资产内文档序是 rowid；**服务层**的公开 list_versions 才按 version_number 排 |
| `list_all_version_models()` | 1879 | `ORDER BY rowid` + members | 同上 |
| `child_version_models(parent_version_id)` | 1898 | `SELECT v.* FROM versions v JOIN lineage l ON l.child_version_id = v.id WHERE l.parent_version_id = ? ORDER BY v.rowid` + members | 镜像 children_by_parent map（父索引、文档序） |
| `list_tag_models()` | 1914 | `SELECT * FROM tags ORDER BY rowid` | Tag（metadata JSON 解析） |
| `tags_for_version(version_id)` | 1926 | `SELECT t.* FROM tags t JOIN version_tags vt ON vt.tag_id = t.id WHERE vt.version_id = ? ORDER BY t.rowid` | 排序键是 **t.rowid**（tags 表），非 vt 行序 |
| `tag_ids_for_asset(asset_id)` | 1942 | `SELECT tag_id FROM asset_tags WHERE asset_id = ? ORDER BY rowid` | 字符串 id 列表 |

行→模型构造器（44-93）是整文档加载与惰性读**共用**的单一事实源——
C++ 对应物 = src/row_mapping.hpp 的 `rows::asset_from_row/version_from_row`
（其头注释明言此纪律）。runs/tags 的行解码目前内联在 repository.cpp
（348-419），无共享 mapper——见 ② 的 row_mapping 增补。

### 1.2 working-copy CRUD（db.py:1335-1425；表 DDL 517-528）

表级语义：`working_id` TEXT PK；`path` TEXT **UNIQUE**；`state` 默认
'checked_out'；created_at/updated_at 本地时间 ISO-秒（无时区后缀）。

| 函数 | 行号 | 语义 |
|---|---|---|
| `register_working_copy(*, source_version_id, path, display_name, payload_mtime_ns, source_size_bytes)` | 1335 | `working_id = "wc-" + uuid4().hex[:12]`；now=本地 ISO-秒；`INSERT INTO working_copies (…, state='checked_out', …)` **裸 INSERT**（无 OR REPLACE/IGNORE）→ UNIQUE path 冲突时 IntegrityError **向上抛**（但服务层 create_working_copy 2351-2352 整体 try/except pass——"registry is bookkeeping, never a checkout gate"，登记失败不阻断 checkout）。**不触碰 sync_state/catalog_revision** |
| `get_working_copy_by_path(path)` | 1369 | `SELECT * FROM working_copies WHERE path = ?` → dict/None（走 _read_rows：缺文件/无 schema → None） |
| `get_live_working_copy_for_source(source_version_id)` | 1375 | `WHERE source_version_id = ? AND state IN ('checked_out','dirty','committing') ORDER BY created_at LIMIT 1`。live 三态；created_at 字典序（ISO-秒同级精度，**同秒并列时平局顺序未指定**——实践不会发生：同源 live 副本唯一） |
| `list_working_copies(states=None)` | 1386 | `if states:`（**空列表 = 无过滤**）→ `WHERE state IN (?,…)`；均 `ORDER BY created_at`。返回 dict 列表 |
| `update_working_copy_state(working_id, state)` | 1402 | `UPDATE … SET state = ?, updated_at = <now> WHERE working_id = ?`——**updated_at 必刷**。sqlite 错误吞掉（try/except pass） |
| `remove_working_copy(working_id)` | 1416 | `DELETE WHERE working_id = ?`，错误吞掉 |

错误消息面：**零**（这组函数没有一条用户可见错误文本；沉默是契约的一部分）。

### 1.3 staging lease 写侧（db.py:1227-1331；表 DDL 503-511）

TTL 常量 `STAGING_LEASE_TTL_SECONDS = 3600.0`（1225）。读侧
active_staging_targets 已在 gc.hpp（cutoff 字符串字典序比较）。写侧：

| 函数 | 行号 | 语义 |
|---|---|---|
| `acquire_staging_lease(targets, kind="register")` | 1227 | `lease_id = uuid4().hex`（32 hex）；now=本地 ISO-秒；schema 缺失→None；`if conn.in_transaction: conn.rollback()`（清掉上次中断遗留的事务）；`BEGIN IMMEDIATE`；per-target `INSERT OR REPLACE INTO staging_leases (lease_id, target, kind, acquired_at, heartbeat_at)`；COMMIT。sqlite 错误→尽力 ROLLBACK→返回 **None**（lease 是保护不是闸门，注册照常进行=pre-lease 行为）。**不 bump revision** |
| `release_staging_lease(lease_id)` | 1265 | `with conn:` 事务里 `DELETE WHERE lease_id = ?`，错误吞掉 |
| `heartbeat_staging_lease(lease_id)` | 1275 | `UPDATE … SET heartbeat_at = <now ISO-秒> WHERE lease_id = ?`，错误吞掉（长时间计算的续约） |
| `prune_stale_staging_leases(ttl=None)` | 1310 | cutoff = now − ttl（默认 3600）本地 ISO-秒；`DELETE WHERE heartbeat_at <= ?`，返回 `cur.rowcount or 0`，错误吞掉返回 0 |

时间格式不变量：heartbeat_at/acquired_at 与 gc.cpp `default_lease_cutoff`
同构——本地时间 `%Y-%m-%dT%H:%M:%S`、无时区后缀、秒精度。**任何**精度/时区
偏差都会让 TTL 的字典序比较失真（跨日/夏令时边界静默失效）。

### 1.4 查询面（db.py:2606-3142）

#### search_assets（2631-2724）——SQL 路径契约

入口 `search_assets` = `_safe([], self._search_assets, …)`（永不抛、缺库返 []）。
`_search_assets` 逐分支拼 SQL（2722 的骨架：
`SELECT DISTINCT a.* FROM assets a {joins} {where}`，**无 ORDER BY**）：

1. **stage**（2674-2677）：`JOIN versions v ON v.asset_id = a.id` + `v.stage = ?`
   ——**资产任一版本**命中即选（与分页路径的 current_version_id IN-子查询
   **语义不同**，见 ⑥-3）。参数 = `stage.value if isinstance(stage, DataStage) else str(stage)`。
   join 造成扇出 → 顶层 DISTINCT。
2. **tags/tag**（2678-2699）：tag_list = [normalize_tag_name(t) for t in tags if
   str(t).strip()] + 单 tag（strip 非空才并入）。
   - `tag_op == "or"`：单个 `EXISTS (SELECT 1 FROM asset_tags at_o JOIN tags t_o ON t_o.id = at_o.tag_id WHERE at_o.asset_id = a.id AND t_o.name IN (?, …))`；
   - **else（含非法 tag_op 值！）**：每个 tag 一条 `EXISTS (… at_a … WHERE at_a.asset_id = a.id AND t_a.name = ?)` 以 AND 串联。
   EXISTS 每分支索引背书（idx_asset_tags_tag_id、tags.name UNIQUE），
   避免 DISTINCT 扇出。
3. **text**（2700-2707）：`a.name_search LIKE ? ESCAPE '\\'`，参数 =
   `%{like_escape_literal(normalize_asset_search_name(text))}%`（#897：LIKE 仅
   ASCII 大小写不敏感，靠 name_search 折叠列对齐 casefold 语义）。
4. **type**（2708-2710）：`a.type = ?`，`str(type)`。
5. **metadata**（2711-2720）：每对 (key, value) 一条
   `CAST(json_extract(a.metadata, ?) AS TEXT) = ?`，参数 =
   `$."{key}"`（**key 原样内插进带引号的 JSON 路径**，不转义）+
   `metadata_search_value(value)`（bool→"1"/"0"，其余 str()）。
   注：**db 层不过滤空值**；空串值过滤发生在 queries.py 组合层（126 行
   `if str(v).strip() != ""`）。
6. **trashed**：**SQL 层无 trashed 谓词**。过滤在 queries.py 消费端
   （167/173：`include_trashed or not trashed`）。C++ 冻结见 ②。

返回：行经 `_decode`（2608-2618：dict 化 + metadata/parameters 两列 JSON
解码、坏 JSON→{}）→ list[dict]。行序 = planner 序（无排序保证；
queries.py 按 rows 顺序输出模型列表）。跨路径一致性靠集合相等，
**不是**行序相等（文档扫描路径是文档序）。

#### catalog_aggregates（2992-3042）

`_safe({}, …)`。五段查询（trash_sql = "" 或 " WHERE a.trashed = 0"）：
- stages：`SELECT v.stage, count(*) FROM assets a JOIN versions v ON v.id = a.current_version_id {trash_sql} GROUP BY v.stage`——**按 current_version_id 连**（与 search_assets 的任一版本 join 不同！）。
- types：`SELECT a.type, count(*) FROM assets a{trash_sql} GROUP BY a.type`。
- tags：`SELECT t.name, t.display_name, count(at_c.asset_id) FROM tags t JOIN asset_tags at_c ON at_c.tag_id = t.id JOIN assets a ON a.id = at_c.asset_id [WHERE a.trashed = 0] GROUP BY t.id` → 键 = `str(display or name)`（display_name 空串/None 回退 name）。GROUP BY t.id 的裸列 t.name/t.display_name 由 SQLite 按 PK 组确定性给出。
- review：`SELECT json_extract(a.metadata, '$.review_status'), count(*) FROM assets a{trash_sql} GROUP BY 1`；**falsy 跳过**（None/''/0 不入桶）；注意此处 json_extract 不 CAST、路径是字面量。
- total：`SELECT count(*) FROM assets a{trash_sql}`。
返回 `{"total", "stages", "types", "tags", "review_status"}`（全 str 键/int 值）。
完整性计数**有意缺席**（MISSING/FAILED 需文件系统探测）。

#### 其余六个

| 函数 | 行号 | SQL（冻结文本） | 说明 |
|---|---|---|---|
| `list_versions(asset_id)` | 3044 | `SELECT * FROM versions WHERE asset_id = ? ORDER BY version_number` | 行经 `_decode`（dict + metadata 解码）；**不挂 members**；version_number 并列时次序未指定（实践 per-asset 唯一）。idx_versions_asset_version 背书 |
| `lineage_edges(version_id)` | 3055 | parents: `SELECT parent_version_id FROM lineage WHERE child_version_id = ?`；children: 反向 | 均无 ORDER BY（隐含 rowid 序）；返回 `{"parents": […], "children": […]}` |
| `assets_for_tag(tag_name)` | 3079 | `SELECT a.id FROM assets a JOIN asset_tags at ON at.asset_id = a.id JOIN tags t ON t.id = at.tag_id WHERE t.name = ? ORDER BY a.id` | 参数先 normalize_tag_name；**含 trashed 资产**（无 trashed 谓词）；id 字典序 |
| `versions_for_tag(tag_name)` | 3093 | 同形（version_tags JOIN）`ORDER BY v.id` | 同上 |
| `find_managed_raw(source_uri, sha256)` | 3107 | `SELECT id FROM versions INDEXED BY idx_versions_source_sha WHERE managed = 1 AND stage = 'raw' AND trashed = 0 AND source_uri = ? AND sha256 = ? LIMIT 1` | `_safe(None,…)`。**INDEXED BY 是行为契约**：索引缺失 → prepare 报 "no such index" → _safe → None → 调用方回退文档扫描（正确性从不依赖索引）。谓词五连：managed=1/stage='raw'/trashed=0/source_uri/sha256。LIMIT 1 无 ORDER BY：多候选时按 (source_uri, sha256, rowid) 索引序取首个——适配层会再验证 |
| `find_external_by_path(path)` | 3128 | `SELECT id FROM versions INDEXED BY idx_versions_external_path WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1` | 同构（#1043 partial covering index：`ON versions(path) WHERE managed = 0 AND trashed = 0`，DDL 414）。trashed 永不作 dedup 目标（review I2：垃圾箱里的版本重新导入不得静默解析过去） |

两个 INDEXED BY 是 adapter 三级 dedup 策略（当前索引→batch overlay→线性扫描）
的地基——#1139/#1043 的 planner 陷阱注释（3117-3119、3133-3136）必须随 SQL
一起搬：去掉 INDEXED BY 后 planner 会选 idx_versions_trashed（匹配 ~ 全表
= 实质全扫描，100k 版本 7-9ms/次）。

### 1.5 SQL 路径 vs 文档路径的启停口径（queries.py:127-176，CONV-31 已搬文档侧）

何时走 SQL（index 路径）、何时回退文档扫描——**判据在服务组合层**，两个
路径函数自身对新鲜度无感知（冻结边界）：

```
use_sql = (not service._batch_depth)                      # batch 内必走文档
          and not (lazy and not warm)                     # 懒开 pre-warm 跳过新鲜度门
          and service.index_revision() == document.catalog_revision
任何异常（含 SQL 抛错）→ except Exception: pass → 文档扫描兜底
```

懒开形态（#1212）：lazy&&!warm 时**跳过新鲜度门**直接查索引，结果 id 经
`resolve_asset_models`（又走惰性读）回解析成模型——索引行绝不因文档未 warm
而把结果过滤成空。**C++ 单连接降级**（如实记录）：Python 懒开是 UI 性能形态
（开工程秒开、后台 warm）；C++ 由服务直接持连接，无"半开"状态机——
14 个惰性读退化为**普通点查 API**（无 _lazy_read_cache 单槽缓存、无
lazy/warm 门），但**返回形状/字段解码/排序必须与文档路径逐字节 parity**
（惰性/急切 parity 本就是 Python 测试钉死的契约，C++ 用同一断言钉）。
新鲜度门（revision 相等）与回退逻辑归 31b 服务核组合层。

---

## ② 冻结 C++ API 提案（C++20、Qt-free、不实现）

### 2.1 新文件 `include/pwb/catalog/queries_sql.hpp` + `src/queries_sql.cpp`

**为什么不是 paged_sql.hpp**：paged_sql.hpp 的章程是 EntityPageQuery +
20-key page-row 的 v6 惰性浏览契约（头注释第一句就钉了 "One deterministic
page"）；聚合/id-查询/点查面混入会稀释该章程并让 header 双倍膨胀。
**为什么叫 queries_sql.hpp**：与 queries.hpp/cpp（CONV-31，文档扫描路径）
构成显式双轨——文件名即审计 #849-2 的对照表，两路径同参同型可对拍。
复用 queries.hpp 的 `AssetSearchQuery`（含 include_trashed/metadata Json 对），
使 cross-path 测试**同一个 query 对象**喂两侧。

```cpp
// SQL read-side over the canonical catalog.sqlite (conv-31b; db.py lazy
// entity reads + query surface parity). Every function degrades silently:
// missing file/table/prepare failure returns the default — the Python
// `_read_rows`/`_safe` composed behavior (the service layer's try/except
// warm-fallback is folded in for the single-connection model). Row order
// matches load_document (rowid) so lazy results are drop-in identical to
// the eager document's.
#pragma once
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/queries.hpp"    // AssetSearchQuery（复用，双轨同参）
#include "pwb/catalog/sqlite.hpp"
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::catalog {

// ---- lazy single-entity reads (db.py:1745-1949, #1212) --------------------
std::optional<DataAsset> get_asset_model(Database& db, const std::string& id);
// Python dict 插入序（= 请求 id 首见序，非行序）；重复 id 首次胜出。
std::vector<std::pair<std::string, DataAsset>> get_asset_models(
    Database& db, const std::vector<std::string>& ids);   // 500-id 分块
std::optional<DataVersion> get_version_model(Database& db, const std::string& id);   // +members
std::optional<DataRun> get_run_model(Database& db, const std::string& id);           // +io+ports
std::vector<DataAsset> list_asset_models(Database& db, bool include_trashed = true,
                                         bool trashed_only = false);
struct AssetIdentityRow { std::string id, name, legacy_resource_id; };  // NULL→""
std::vector<AssetIdentityRow> list_asset_identity_rows(Database& db,
                                                       bool include_trashed = false);
std::vector<DataRun> list_run_models(Database& db);
std::vector<DataVersion> list_version_models_for_asset(Database& db,
                                                       const std::string& asset_id);
std::vector<DataVersion> list_all_version_models(Database& db);
std::vector<DataVersion> child_version_models(Database& db,
                                              const std::string& parent_version_id);
std::vector<Tag> list_tag_models(Database& db);
std::vector<Tag> tags_for_version(Database& db, const std::string& version_id);
std::vector<std::string> tag_ids_for_asset(Database& db, const std::string& asset_id);

// ---- query surface (db.py:2631-3142) ---------------------------------------
// search_assets 的 SQL 路径：SQL 文本与 db.py 逐分支对齐（EXISTS-tag/
// json_extract/name_search LIKE），**无 trashed 谓词**；include_trashed 在
// 本函数内对返回行做后置过滤（= queries.py 消费端过滤的折叠，见 ⑤-2）。
// 返回行序为 SQL 扫描序；与 search_assets_scan 的文档序不保证互等——
// cross-path 断言用排序后集合。空串 metadata 值在绑定前丢弃（queries.py:126）。
std::vector<std::string> search_assets_sql(Database& db, const AssetSearchQuery& q);

struct CatalogAggregates {
    std::int64_t total = 0;
    std::map<std::string, std::int64_t> stages, types, tags, review_status;
};
CatalogAggregates catalog_aggregates_sql(Database& db, bool include_trashed = false);

std::vector<DataVersion> list_versions_sql(Database& db,           // ORDER BY
                                           const std::string& asset_id);  // version_number; 无 members
struct LineageEdges { std::vector<std::string> parents, children; };
LineageEdges lineage_edges_sql(Database& db, const std::string& version_id);

std::vector<std::string> assets_for_tag_sql(Database& db,           // ORDER BY id
                                            const std::string& tag_name);
std::vector<std::string> versions_for_tag_sql(Database& db,         // ORDER BY id
                                              const std::string& tag_name);

// adapter 三级 dedup 的第 1 级（O(log N)）。INDEXED BY 逐字保留：索引缺失
// → prepare 失败 → nullopt → 调用方回退扫描（正确性不依赖索引）。
std::optional<std::string> find_managed_raw_sql(Database& db,
                                                const std::string& source_uri,
                                                const std::string& sha256);
std::optional<std::string> find_external_by_path_sql(Database& db,
                                                     const std::string& path);
}  // namespace pwb::catalog
```

TU 归属：全部进 `src/queries_sql.cpp`（新 TU，CMake 追加
`# BEGIN CONV-31B` 块，照 CONV-26/31 先例只加新源不动既有列表）。
行解码复用 `src/row_mapping.hpp` 的 `rows::asset_from_row/version_from_row`；
**增补** `rows::run_from_row`（7 列 SELECT id, operation, parameters,
generator, status, model_ref, created_at 的形状，从 repository.cpp:349-367
提取）与 `rows::tag_from_row`（4 列）——row_mapping.hpp 是 src 内部头
（非公共安装面），其头注释本就要求"schema 列变化只落一处"；这是本提案
唯一触碰的既有文件（src 内部，非 include）。
`like_escape_literal`：paged_sql.cpp 有一份 file-local static（27-35）；
queries_sql.cpp 内再放一份同文 static 并交叉引用注释（避免动已交付 TU；
两份共 8 行，D2 oracle 可用同参断言钉等）。
stage 参数绑定：`domain::to_string(*q.stage)`（== Python str(DataStage) 值）。

### 2.2 既有 `repository.hpp/.cpp` 增补（WC 读侧 + lease 写侧）

**为什么进 repository**：这组是带事务的**写/簿记**面，Python 里挂在
CatalogIndex（≈ C++ CatalogRepository：同持连接、同事务纪律）；现有
insert/remove/set_state 三兄弟已在此，补齐读写 API 面保持 registry 内聚。
查询类（纯读、无连接所有权）才走自由函数。

```cpp
// ---- working-copy registry 完备化（db.py:1335-1425; #1211）----------------
// 读侧（const，缺表/缺行→nullopt/空，不抛）
std::optional<WorkingCopy> get_working_copy_by_path(const std::string& path) const;
std::optional<WorkingCopy> get_live_working_copy_for_source(
    const std::string& source_version_id) const;   // 三 live 态, created_at, LIMIT 1
std::vector<WorkingCopy> list_working_copies(
    const std::vector<std::string>& states = {}) const;  // 空=全量; ORDER BY created_at
// 生成式注册（Python register_working_copy 形状）：wc-<12hex> + 本地 ISO-秒
// 双时间戳 + state='checked_out'；返回 working_id。**裸 INSERT**（UNIQUE path
// 冲突→返回错误，= Python IntegrityError；组合层照 service.py:2351 吞掉）。
std::string register_working_copy(const std::string& source_version_id,
                                  const std::string& path,
                                  const std::string& display_name,
                                  std::optional<std::int64_t> payload_mtime_ns,
                                  std::optional<std::int64_t> source_size_bytes);

// ---- payload staging leases 写侧（db.py:1227-1331; #1222）-----------------
// lease 是保护不是闸门：失败返回 nullopt 后注册照常进行（pre-lease 行为）。
std::optional<std::string> acquire_staging_lease(
    const std::vector<std::string>& targets, const std::string& kind = "register");
void release_staging_lease(const std::string& lease_id);      // 错误吞掉
void heartbeat_staging_lease(const std::string& lease_id);    // 错误吞掉
int prune_stale_staging_leases(std::optional<double> ttl_seconds = std::nullopt);  // 默认 3600
```

**必须同时修的三处既有偏差**（现状核实于 repository.cpp:890-943）：
1. `insert_working_copy` 用 `INSERT OR REPLACE` → 改**裸 INSERT**
   （path 冲突时 Python 是"抛→服务吞→无行"，OR REPLACE 是"静默顶行"，
   会留下一行指向陈旧 source_version_id 的注册记录，改变 crash-recovery 面）；
2. `set_working_copy_state` 不刷 `updated_at` → Python 1402 是
   `SET state=?, updated_at=<now>`；补上；
3. 三个窄写各自 `bump_revision()` → **去掉**。Python 的 WC/lease 写完全不碰
   sync_state；revision 是 #411/#1220 的文档 CAS 基线，每次 checkout bump
   会让 is_fresh/sync 判"stale"触发 O(N) reconcile，且污染 R1 apply_changes
   的 expected_revision 比对。这是行为正确性问题，不是风格问题。

新私有 helper：`local_now_iso_seconds()`（strftime "%Y-%m-%dT%H:%M:%S"
本地时，与 gc.cpp default_lease_cutoff 同构；不要复用 refs.cpp utc_now_iso
——那是 UTC+微秒，格式不同）；id 生成用 std::random_device 十六进制
（refs.cpp new_ref_id 先例；32-hex lease / 12-hex wc 前缀，仅形状 parity）。

### 2.3 不做的东西（明确出界）

- 连接池/懒开/线程探活（_ConnEntry/native_thread_alive/prune/close 全家，
  949-1168）：C++ 单连接 RAII，31-gap-analysis §1 已判"不移植"。
- `_lazy_read_cache` 单槽缓存与 lazy/warm 方法包装：服务层形态，归 31b
  服务核（若做）。
- reconcile/rebuild/reset/sync（2313-2604）：不在 R2 范围。
- `_decode` 的通用 dict 行形状：C++ 用类型化结构承载（见 ⑤-6）。

---

## ③ 依赖与接口点

- **R1（apply_changes/DirtySet/CAS）**：
  - **共享不变量**：本文件的 14 个惰性读钉死了 rowid 序 = 文档序；R1 的
    `_ordered()`（2001-2026：存在行按 rowid、新 id 按 mark 序追加）正是为
    保住这个序而存在。Oracle 必须交叉验证：同一 dirty 序列经 R1 apply_changes
    后，`list_*` 输出 == write_all 后的 `list_*` 输出。
  - **revision 纪律**：R1 的事务内 CAS（2036-2051，CatalogStaleWriteError
    消息逐字：`"数据目录元数据已被其他实例修改（事务内比对失败）；为避免
    覆盖他人提交，本次保存已中止。请重新打开工程后重试。"`）要求 WC/lease
    写**永不**改 catalog_revision（见 ②-2 的修复 3）——否则簿记写会让下一次
    保存全部误判 stale。
  - R1 的 `_write_run_ports/_write_version_members`（DELETE+INSERT OR IGNORE）
    决定 get_run_model/list_*_models 读回的 ports/members 顺序。
- **R4（maps / DocumentIndex）**：`managed_raw_for/external_for`（内存键，
  document_index.hpp:45-48）与 `find_managed_raw_sql/find_external_by_path_sql`
  是**双轨**：内存键 = tier-3 文档扫描的等价物（DocumentIndex 从文档构建）；
  SQL 查询 = tier-1（index_revision == document.revision 时才可信）。31b
  服务核组合三级：SQL 命中→用文档/get_version 复验五谓词（managed/stage
  raw/not trashed/source_uri/sha256；外部路径复验 not managed/not trashed/
  path——SQL 行可能落后于未提交的文档状态）→ batch overlay（tier-2，
  _batch_overlay_fresh：base revision 对齐即"索引∪overlay 完备"，miss 可证
  无需扫描）→ 扫描（命中则 heal 内存键，miss 则摘除键，adapter.py:414-419）。
  唯一性注意：find_* 的 LIMIT 1 平局按索引序，复验失败时 Python 会落回
  扫描取文档序首个——C++ 组合必须保留"复验失败→继续降级"而不是直接 miss。
- **queries.cpp（CONV-31 文档路径）**：search_assets_scan/find_assets_by_tag/
  find_versions_by_tag + metadata_search_value 已就位。本切片补 SQL 侧后，
  启停门（revision 相等、非 batch、异常回退，queries.py:127-144）落在 31b
  服务核——两个路径函数都**不感知**新鲜度（冻结边界，防双路径各判一次）。
- **gc.hpp**：active_staging_targets/default_lease_cutoff 是 lease 读侧；
  本切片的写侧 heartbeat_at 格式必须与 cutoff 的字典序比较兼容（同格式）。
- **paged_sql.cpp**：like_escape_literal 的同文 static 复制（见 ②-1）；
  分页谓词与 search_assets 谓词是**两套**（stage 语义不同），不要合并出
  "统一谓词构造器"。
- **sqlite.hpp**：Database/Statement/Transaction 现有能力足够
  （bind text/i64/null + json_extract 是服务端 SQL），无需改动。
- **models.hpp**：WorkingCopy/StagingLease/Tag/DataRun/DataVersion 已有，
  无需新增域类型；CatalogAggregates/LineageEdges/AssetIdentityRow 是
  queries_sql.hpp 的局部形状。

---

## ④ Oracle 冻结场景建议

在 tools/oracle fixture 流（31-decisions D2 的 replay 基建）上建议加：

1. **惰性/急切 parity（逐实体）**：fixture store 上，对每个 id：
   get_asset_model == load_document.assets[i]（字段级）；get_version_model
   （含 members 序）；get_run_model（inputs/outputs/ports 序与方向桶）；
   list_asset_models 三分支；list_asset_identity_rows 两分支（含 NULL
   legacy_resource_id → ""）；list_run_models/list_all_version_models/
   list_version_models_for_asset/child_version_models（对照 DocumentIndex
   .children_of）；list_tag_models/tags_for_version/tag_ids_for_asset（对照
   文档 maps）。**全部序敏感**。
2. **get_asset_models 语义**：乱序 + 重复 id 输入 → 输出序 = 首见序、去重；
   >500 id 跨块。
3. **WC 生命周期**：register（断言 working_id 前缀 wc- + state/双时间戳）→
   get_by_path → update_state（updated_at 前进）→ list(states) 过滤/全量 →
   get_live_for_source（多死态+一活态只取活态；committing 亦活）→ remove →
   再查 None；UNIQUE path 二次注册 → 错误/无新增行；**全程 revision 不变**。
4. **lease**：acquire 多 target → gc.active_staging_targets(过去 cutoff)
   可见；heartbeat 后旧 cutoff 不可见新 cutoff 可见；prune_stale 只删过期
   （返回计数）；release 后 target 消失；无表 store 上 acquire → nullopt。
5. **search_assets 双路径对拍（#849-2）**：同一 fixture × 查询矩阵
   （text 含 `%`/`_` 字面量；stage；tag 单/多 × and/or × 含空白 tag；type；
   metadata bool/int/str/空串值；include_trashed 两态）→
   sorted(sql_ids) == sorted(scan_ids)；额外钉 SQL 文本（golden SQL）。
   场景含"资产任一版本命中 stage 但 current 不命中"——钉与分页路径的语义差。
6. **aggregates 对拍**：与文档侧手算计数对拍（stages 按 current_version、
   tags display 回退、review falsy 跳过、include_trashed 两态）。
7. **list_versions/lineage_edges/for_tag**：排序断言（version_number/a.id/
   v.id）+ normalize_tag_name 归一命中（大小写/空白）。
8. **find_managed_raw/find_external_by_path 谓词矩阵**：正例；trashed 排除
   （I2）；managed 反例（0）；stage 反例（非 raw）；checksum/source/path 不符
   → None；**索引删除**的 scratch db → nullopt → 组合层回退扫描（钉三级）。
9. **降级矩阵**：空文件/无 schema store 上全部读函数返回 default、不抛。
10. **R1 交叉**（与 R1 oracle 合流）：dirty 写后 list_* == write_all 后 list_*。

---

## ⑤ 有界偏离清单（如实）

1. **_safe 折叠**：Python 惰性读组 sqlite 错误上抛→服务层 warm 回退；C++
   统一静默 default。锁死窗口（busy_timeout 5000ms 内）get_asset 的
   unknown-asset 误报可能；接受（单连接无池竞争）。
2. **include_trashed 后置过滤**：Python 在 queries.py 消费端过滤、db 层 SQL
   无谓词；C++ search_assets_sql 把过滤折进函数（SQL 文本保持与 db.py 逐字
   对齐）。行为 parity、位置偏离。
3. **懒开不移植**：无 lazy/warm 状态机、无 _lazy_read_cache；返回形状/排序
   parity 全保。
4. **id/时间生成源**：random_device hex vs uuid4；strftime 本地 ISO-秒 vs
   datetime.now().isoformat(timespec="seconds")——形状 parity，值不同源。
5. **NFKC 折叠缺席**（继承 15-decisions D6）：name_search/LIKE 用 ASCII fold，
   非 ASCII 大小写变体搜索与 Python 分叉（既有偏离，本切片不扩大）。
6. **行形状类型化**：list[dict]+_decode → 类型化结构（DataVersion 等，
   metadata 语义解析保持；list_versions 不挂 members 对齐 Python dict 无
   members 键）。
7. **json_extract 数值 TEXT 化的浮点边缘**：Python str(1e16)='1e+16' vs
   SQLite CAST='1.0e+16' 的不匹配 **Python 自身同样存在**（两侧同错=parity）；
   C++ 参数侧 metadata_search_value 的 dump() 与 Python str() 在治理值域
   （str/bool/int）一致。
8. **json 路径 `$."{key}"` 不转义**：key 含 `"` 的行为两侧一致地"坏"——
   治理词表经 policies 校验，实践不可达；如实记录不修。

---

## ⑥ 风险 / 先例坑

1. **INDEXED BY 必须逐字保留**（#1139/#1043）：去掉后行为"看起来对"但
   planner 回到 idx_versions_trashed 全扫描——性能回归在 100k 规模才显形，
   单测抓不住。索引缺失→nullopt→回退扫描是**特性**（正确性不依赖索引），
   不要把 prepare 失败改成无索引重试。
2. **stage 的两义性**：search_assets 是"任一版本"（JOIN），分页/count 是
   "current 版本"（IN-子查询），aggregates.stages 又是 current（JOIN on
   current_version_id）。三处不可"统一"——各有测试钉住。
3. **revision 污染**：现有 C++ WC 三写 bump revision（②-2 修复 3）；
   不修则 31b 服务核每次 checkout 后 is_fresh 假阴 → sync() 全量 reconcile，
   且 R1 CAS 基线被簿记写打穿。这是本 recon 发现的最重既有偏差。
4. **EXISTS vs JOIN+DISTINCT**：tag 过滤用 EXISTS 是为免扇出；改成
   JOIN+DISTINCT 行为等价但行序/计划变——SQL golden 会碎，且 10k+ 规模
   计划劣化。冻结 EXISTS。
5. **search_assets 无 ORDER BY**：不要"顺手"加排序——Python 消费者不依赖
   行序，加了反而偏离 SQL 文本 parity；需要确定性时组合层排序或经
   get_asset_models。
6. **created_at 秒精度平局**：get_live_for_source 的 LIMIT 1 无并列打破键；
   同秒同源多 live 行未指定（实践不可达：活副本唯一 + register 前置查活）。
   oracle fixture 避免同秒同源双活。
7. **lease 时间格式**：任何精度/时区漂移都会让 TTL 字典序静默失真
   （gc 读侧已冻结本地 ISO-秒）；heartbeat/prune 必须同一 helper 出参。
8. **500/100 分块常量**：SQLite 变量上限（3.45 默认 32766）远高于 500，
   但分块同时是 Python 行为的一部分（IN 块序影响 get_asset_models 输出序）；
   保持 500（实体/端口/成员）与 100（分页 current 批取）原值。
9. **row_mapping 纪律**：惰性读与整文档加载必须共用行解码（Python 44-93
   注释明言 lazy/eager parity 靠单一事实源）；新写 SQL 列出显式列名
   （照 paged_sql.cpp 先例，禁 SELECT * 依赖列位）——`SELECT *` 在
   row_factory 下按名取数，C++ Statement 按位取数，列序漂移即静默错位。
10. **direction 非 "output" 即 input**（_attach_run_ports 的 else）：不要
    "严格化"成仅 "input" ——脏数据（空串方向）会改变分桶行为。

— R2 recon，2026-09-19。未改任何源码；唯一产物为本文件。
