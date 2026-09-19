# R1 recon — db.py 通用写通道（DirtySet / apply_changes / reconcile / rebuild / sync）

CONV-31b 切片侦察与契约冻结（R1）。基线：worktree `feat/cpp-catalog-service`；
Python 源 `paleo_workbench/catalog/db.py`（3142 行，行号锚点均指本 worktree 当前版本）；
C++ 侧 `libs/catalog`（CONV-31 已交付 document_index/refs/tags/v11_policy 等 22 个 TU）。
对照文档：`31-decisions.md` D6（31b 范围）、`31-gap-analysis-big.md` §1（db.py 差距清单，
其中 storage/service_v11/audit 的"未覆盖"已过时，db.py 部分经本次逐行核实仍准）。

范围：① DirtySet 数据结构；② apply_changes 通用单事务写 + 事务内 revision CAS；
③ reconcile/_symmetric_diff；④ rebuild/_rebuild_once；⑤ sync/is_fresh/reset；
⑥ 明确不移植：每线程连接池。不含：14 个惰性读（R2）、open 流程（R3）、batch_save 编排（R4）。

---

## ① 语义契约（逐函数逐分支）

### 1. `CatalogStaleWriteError`（db.py:244-248）

`class CatalogStaleWriteError(OSError)`。docstring 契约原文：另一进程/会话在本会话
baseline 之后提交过 canonical store（#411）。事务化抛出：比对发生在写事务
（BEGIN IMMEDIATE）**内部**，不存在 check-then-act 窗口——至多一个冲突写者提交成功。

关键类型事实：它继承 `OSError` 而**不是** `sqlite3.DatabaseError`，因此 `sync()`
（1449-1467）里 `except sqlite3.DatabaseError` 的自愈分支**不会**吞掉它——CAS 冲突
穿过 sync 向上传播。C++ 移植必须保持这一点（见⑤-8）。

### 2. `DirtySet`（db.py:756-829）

- 8 个集合，全部是**插入序 dict[str, None]**（ OrderedDict 语义）：
  `assets / versions / runs / tags / models / model_versions / asset_tags / version_tags`。
  `asset_tags`/`version_tags` 存的是**OWNER id**（asset_id/version_id），其 tag 关联发生了变化。
- `mark_*`（775-797）：`self.X[entity_id] = None` —— **幂等**，且重复 mark **不改变位置**
  （dict 语义：已存在的 key 再赋值保持首次插入位）。id 的顺序 = 文档变更顺序，
  `apply_changes._ordered` 依赖这一点让同事务插入的新行保持文档顺序。
- `merge(other)`（799-815）：逐字段 `update`；若 incoming 不是 dict（调用方可能传裸
  set）先 `dict.fromkeys` 归一，防止把 id 字符串误读为 (key, value) 对。合并后仍是
  先 self 后 other 的首见序。
- `is_empty()`（817-829）：8 个集合全空才 True。
- 不变量：**id 不在 document 中 == 删除**（docstring 763），判定发生在 apply_changes 里。

### 3. `_symmetric_diff(db_rows, doc_rows)`（db.py:738-752）

- 输入两个 `{id: row_tuple}`；输出 `{id: None}`（插入序）。
- 分支一（747-749）：doc 有而 db 无，**或** db 行 tuple != doc 行 tuple → changed。
  迭代按 **doc_rows 的构建序**（文档序）。
- 分支二（750-751）：`set(db_rows) - set(doc_rows)`（db 独有 → 删除）。
- row tuple 的类型对齐是隐含契约：db 侧 `tuple(row[1:])` 来自 `SELECT *`（INTEGER 列
  得 int，TEXT 得 str，NULL 得 None），doc 侧由 `_asset_row`(569) / `_version_row`(603) /
  `_run_row`(639) / `_tag_row`(660) / `_model_row`(676) / `_model_version_row`(702)
  生成（bool→int、None→None、JSON→str）。即比较是**逐列类型敏感**的。
- docstring 契约：重插行保持 rowid == 文档序不变量（`_ordered` 依赖）。

### 4. `CatalogIndex` 连接模型（db.py:930-1168）——不移植部分

不移植（31-gap §1 已有先例结论，本次确认）：
- `ThreadSafeCatalogSession`（832-848）、`_ConnEntry`/ident 回收（851-868/1153-1168）、
  `native_thread_alive`（865-918，/proc 与 Win32 探活）、`prune_dead_threads`（961-987）、
  全池 `close` 的 interrupt 语义（989-1019）、`_drop_current_connection`（1021-1040）。
  **理由**：这些全部服务于"sqlite3 连接不可跨线程 + Python 线程生命周期不可靠"两个
  Python 特有问题；C++ sqlite3 C 句柄本身线程安全模式可配，且 31b 服务层是单写者
  （服务锁串行化保存，db.py:1134-1136 注释自述）。
- **C++ 等价物**：`sqlite.hpp` 的 `Database`（RAII 单连接，move-only）+ `Transaction`
  （BEGIN IMMEDIATE，析构未 commit 则 ROLLBACK）。跨进程互斥由 BEGIN IMMEDIATE +
  事务内 CAS 承担（与 Python 的跨进程语义完全同源）；同进程多线程由上层
  （31b service）持锁串行——正是 Python service 的模型。`reset()`/`rebuild()` 需要
  "关连接再删文件"，RAII 下由调用方先 `db.close()`（repository.hpp 已有 `close()`
  先例，save-as 迁移用过）。
- `_connect` 的连接期幂等 DDL + 单条失败 continue（1085-1133）在 C++ 的对应物是
  `Database::ensure_schema()`（sqlite.cpp:163-320，同一份语句表）——但注意 Python
  版**逐条容错 continue**，C++ 版**遇错即返回**。对 apply_changes 无影响（写路径的
  防御性 DDL 见 §6/§7），open 流程（R3）需另行决策，不在本切片冻结。

### 5. `_schema_present` / `_read_sync_state` / `revision`（db.py:1172-1218）

- `_schema_present`（1172-1185）：`sqlite_master` 有 `sync_state` 表才算 schema 在。
  `_connect` 会在文件被删后重建空库，此时表不存在。
- `_read_sync_state(key)`（1196-1208）：文件不存在 → 先 `_drop_current_connection()`
  （C++ 等价：调用方废弃句柄重开）再返回 None；读失败（DatabaseError/OSError）同样
  丢弃连接返回 None。**None 是"缺失/不可读/损坏"的统一哨兵**。
- `revision()`（1210-1218）：`int(raw)`，ValueError → None。注意 None 与 0 语义不同
  （is_fresh 里 None != 任何 int → False）。

### 6. `apply_changes(document, dirty, *, lookups=None, expected_revision=None)`（db.py:1951-2177）

总契约：把 dirty 中每个 id 落库——在 document 中 → upsert；不在 → 删除（连带依赖行）。
lineage 按 touched version/run 用与全量 rebuild 相同的 keep-rules 逐个对账
（run 派生边在 version 清除后存活）。结果 == `write_all` 限定在 dirty 集上的效果。
**一个事务**。

分支顺序（逐条）：

1. **schema 缺失回退**（1977-1983）：`_schema_present` 为假 → `write_all(document)`
   （即 `rebuild`，1586）后 return。发生在任何事务之前。
2. **lookups 归一**（1989-1999）：`lookups or {}`；`lookups.get("assets") or {a.id: a for a in document.assets}`
   ——注意 Python `or`：传入**空 dict 也回退**全扫（不可观测差异，见⑤-9）。tags 与
   models/model_versions **永远**从 document 现扫（小集合）。
3. **`_ordered(ids, table)`**（2001-2026）：对每个表的 dirty id 求"库内既有行按
   rowid 升序 + 新 id 按 mark 序尾接"。rowid 查询按 500 个 id 一批
   `SELECT id, rowid FROM {table} WHERE id IN (...)`，**在已开的事务内**执行。
   目的：既有行保 rowid（ON CONFLICT DO UPDATE 不动 rowid），新行按 mark 序 append，
   两者都与 `load_document` 的 `ORDER BY rowid` 恢复序一致。
4. **事务与 CAS**（2032-2051）：
   - `if conn.in_transaction: conn.rollback()`（2032-2033）——防御池化连接残留事务。
     C++：RAII `Transaction` 天然不残留；无需等价分支（列入⑤）。
   - `BEGIN IMMEDIATE`（2034）——先取写锁再读任何东西。
   - `expected_revision is not None` 时（2036-2051）：事务内
     `SELECT value FROM sync_state WHERE key = 'catalog_revision'`；行缺失 →
     `stored_rev = None`；`int()` 失败（TypeError/ValueError）→ None；
     **`stored_rev != expected_revision` → raise CatalogStaleWriteError**。注意：
     `expected_revision=0` 且库里无行（stored_rev=None）也算冲突。
   - 冲突消息**逐字**（2047-2051，中文，UTF-8）：
     `数据目录元数据已被其他实例修改（事务内比对失败）；为避免覆盖他人提交，本次保存已中止。请重新打开工程后重试。`
5. **表处理顺序**（2052-2162，每个表先删后插、id 按 `_ordered`）：
   - **assets**（2052-2062）：在 doc → `_ASSET_UPSERT_SQL`（588，ON CONFLICT DO
     UPDATE，保 rowid）；不在 → `DELETE FROM assets WHERE id=?` +
     `DELETE FROM asset_tags WHERE asset_id=?`。**不级联 versions/runs/lineage**
     （文档是权威，删除的级联由 doc 中那些 version 自身的 dirty 标记驱动）。
   - **versions**（2063-2072）：在 doc → `_VERSION_UPSERT_SQL`（623）+
     `_reconcile_version_parents`（2179）+ `_write_version_members`（199）；
     不在 → `_delete_version_keep_run_edges`（2209）。
   - **runs**（2073-2096）：在 doc → `_RUN_UPSERT_SQL`（650）→ DELETE run_inputs →
     DELETE run_outputs → INSERT OR IGNORE inputs（按 `run.input_version_ids` 序）→
     INSERT OR IGNORE outputs → `_write_run_ports`（136）→ `_reconcile_run_edges`（2233）。
     不在 → `_delete_run_keep_version_edges`（2264）。
   - **tags**（2097-2125）：在 doc → 先 `DELETE FROM tags WHERE name = ? AND id <> ?`
     （预-#884 遗留文档可能有两 tag 在当前 normalizer 下撞名，tags.name UNIQUE；
     document 的对象是幸存者）→ `_TAG_UPSERT_SQL`（668，name 存
     `normalize_tag_name(tag.name)`）；不在 → DELETE tags + DELETE asset_tags（按
     tag_id）+ DELETE version_tags（按 tag_id）。
   - **asset_tags**（2126-2134）：**不排序**（不调 `_ordered`，直接按 dict 序）：
     DELETE 该 asset_id 全部关联 → INSERT OR IGNORE 按
     `document.asset_tags.get(asset_id, ())` 的列表序。
   - **version_tags**（2135-2146）：同上，owner 是 version_id。
   - **models**（2147-2152）：`_ordered`；在 doc → `_MODEL_UPSERT_SQL`（690）；
     不在 → DELETE（无级联）。
   - **model_versions**（2153-2162）：`_ordered`；在 doc → `_MODEL_VERSION_UPSERT_SQL`
     （721）；不在 → DELETE（无级联）。
6. **sync_state 戳**（2163-2170）：`INSERT OR REPLACE` 三行：
   `("schema_version", str(document.schema_version))`、
   `("catalog_revision", str(document.catalog_revision))`、
   `("index_schema_version", str(INDEX_SCHEMA_VERSION))`（=5，db.py:311）。
   注意 catalog_revision 是**文档携带值**（service 在内存先自增再保存），不是库内自增——
   与 repository.cpp `bump_revision()` 的库内 +1 模式不同（见⑥-2）。
7. **COMMIT / 异常**（2171-2177）：COMMIT；任何异常 → 尽力 ROLLBACK（吞 sqlite3.Error）
   后 re-raise。CAS 冲突发生在任何写语句之前，所以冲突路径**零写放大**。

依赖子程序（写侧 keep-rules 核心，全部在事务内执行）：

- `_reconcile_version_parents(conn, version)`（2179-2207）：旧 parent 边集合
  （`SELECT parent_version_id FROM lineage WHERE child_version_id=?`）与新
  `set(parent_version_ids)` 比；`old - new` 中**若 `_run_covers_edge` 则保留**，否则删；
  `new` 全部 INSERT OR IGNORE。
- `_delete_version_keep_run_edges(conn, version_id)`（2209-2231）：DELETE versions →
  DELETE version_tags → **防御性 `_VERSION_MEMBERS_DDL`**（2214，容忍 connect 期 DDL
  中断的库）→ DELETE version_members；run_inputs/run_outputs **不删**（run 记录拥有，
  保留被清除 version 的 id 作历史溯源；注释 2218-2221）；lineage 旧 parent 边逐条判
  `_run_covers_edge`，不被 run 覆盖才删。
- `_reconcile_run_edges(conn, run)`（2233-2262）：新对集合 = inputs × outputs 叉积；
  旧对集合来自 `run_inputs JOIN run_outputs`（该 run）；`old - new` 中若
  `_version_owns_edge` 则保留否则删；new 全部 INSERT OR IGNORE。
- `_delete_run_keep_version_edges(conn, run_id)`（2264-2287）：先取 io 对快照 →
  DELETE runs/run_inputs/run_outputs → **防御性 `_RUN_PORTS_DDL`**（2278）→ DELETE
  run_ports → io 对中不被 `_version_owns_edge` 覆盖的 lineage 边删除。
- `_version_owns_edge`（2289-2301）：child 的 `versions.parent_ids` JSON 含 parent。
- `_run_covers_edge`（2303-2311）：任意 run 的 input=parent 且 output=child（LIMIT 1）。
- `_write_run_ports`（136-145）/**`_write_version_members`（199-208）**：无条件
  DELETE 该 owner 全部行再 INSERT OR IGNORE——**即使新集合为空也先 DELETE**
  （清空语义）；各自先执行防御性 CREATE TABLE IF NOT EXISTS。

不变量汇总（oracle 可钉）：
- I1 事务原子性：任何分支失败 → 库回到调用前（含 CAS 冲突路径）。
- I2 rowid 序：apply 后 `SELECT ... ORDER BY rowid` == 既有行原序 + 新行 mark 序。
- I3 `apply_changes(doc, 全量 dirty) == rebuild(doc)` 的行集等价（lineage 因 keep-rules
  也等价，rebuild 的边集 = parents ∪ run-io，apply 的增量对账收敛到同一并集）。
- I4 sync_state 三键在每次成功提交后被重戳为文档值 + 5。

### 7. `reconcile(document, *, expected_revision=None)`（db.py:2313-2475）

总契约：O(N) 全量对账（无 dirty-set 知识时的安全回退）：读全库 → 求差 → 走
**同一个** `apply_changes`。因为全量 diff 在外来提交下会把别人行 DELETE 掉，
所以 `expected_revision` 与 apply 相同地 CAS 运行（docstring 2317-2323）。

分支：

1. schema 缺失（2326-2332）→ `write_all(document)` return（与 apply 相同回退）。
2. 六表行 diff（2340-2357）：`rows(table)` = `SELECT *` → `{id: tuple(row[1:])}`；
   doc 侧同名 row builder；`_symmetric_diff` 赋给 dirty.assets/versions/runs/tags/
   models/model_versions。**列序 == 表定义序 == row builder 序**（隐含契约）。
3. asset_tags diff（2359-2370）：db 侧 `group_concat(tag_id)` 按 asset_id 分组 → 拆回
   set（丢弃空串）；对 `set(db) | set(document.asset_tags)` 的每个 owner 比较
   set(db_ids) != set(doc list) → mark。**set 比较（group_concat 序不保证）**。
4. version_tags diff（2371-2382）：同上，owner 是 version_id。
5. run io drift（2389-2400）：一次分组 JOIN 读出每 run 的 (input, output) 对集合；
   doc 侧期望 = 叉积；不等 → mark_runs。
6. run_ports drift（2405-2421）：表存在则读全表按 run 分组成 7 元组集合；doc 侧
   `_run_port_rows(run)` 的去 run_id 列集合；**表不存在但 doc 有 ports → mark**
   （库需要修复，写路径会防御性建表）；否则集合不等 → mark。
7. version_members drift（2422-2435）：同 6，8 元组（sha256/size_bytes 的 None 参与
   相等比较）。
8. **已知限度（docstring 2384-2388）**：lineage 表本身**不** diff——边从 parent_ids/
   run-io 重推导，两个来源都不覆盖的外注 lineage 行不会被修复。
9. **dirty 为空分支（2437-2474）**：仍然刷新三键戳（caller 已 bump revision）——
   同一 CAS 契约：`BEGIN IMMEDIATE` → expected_revision 比对（同 §6-4 语义，含
   行缺失/解析失败 → None → 冲突）→ 冲突消息**逐字**（2454-2458）：
   `数据目录元数据已被其他实例修改（事务内比对失败）；为避免覆盖他人提交，本次同步已中止。请重新打开工程后重试。`
   （与 §6 的差别仅在"保存/同步"二字）→ 成功则三键 REPLACE → COMMIT。
10. 非空 → `self.apply_changes(document, dirty, expected_revision=expected_revision)`
    （2475）——**不带 lookups**（diff 本身已 O(N)，无意义）。

### 8. `rebuild(document)` / `_rebuild_once(document)`（db.py:1471-1487 / 2477-2604）

- `rebuild`（1471-1487）：`self.close()`（C++ 等价：调用方 `db.close()`）→ 两次尝试：
  attempt 0 `_rebuild_once`，`sqlite3.DatabaseError` → `reset()`（删文件）后 attempt 1；
  attempt 1 再败 → raise。自愈语义：损坏文件被删除重建（可重建库保证）。
- `_rebuild_once`（2477-2604）：`with conn:`（提交/回滚上下文）：
  1. 跑全量 `_SCHEMA_DDL`（356-540，幂等 IF NOT EXISTS）；
  2. 按 `_DELETE_ORDER`（543-560，子表先删：run_ports → version_members →
     working_copies → staging_leases → lineage → version_tags → asset_tags →
     run_outputs → run_inputs → versions → runs → tags → assets → model_versions →
     models → sync_state）全表 DELETE；
  3. 插入顺序：assets（upsert）→ versions（upsert）→ version_members（OR IGNORE，
     按 document.versions 序展开）→ tags（**INSERT OR IGNORE 而非 upsert**——遗留文档
     两 tag 撞 normalizer 时迁移必须容忍而不是 brick open，2503-2507）→ asset_tags
     （OR IGNORE，按 dict 序）→ version_tags → runs（upsert）→ run_ports（OR IGNORE）
     → run_inputs → run_outputs → models（upsert）→ model_versions（upsert）；
  4. lineage 物化（2576-2595）：先全部 versions 的 parent 边（文档序，seen 去重），
     再全部 runs 的 input×output 叉积（seen 去重）→ INSERT OR IGNORE；
  5. 三键 sync_state REPLACE（2597-2604，同 §6-6）。
- 注意 `_rebuild_once` **不做 CAS**（重建本来就是要覆盖）；但 service 侧
  `rebuild_index`（service.py:1173-1190）在外面用自己的 pre-check + 文档快照。
- `write_all`（1578-1586）== `rebuild` 的别名（legacy JSON 迁移与恢复用：一次原子
  删-重写，崩溃时 SQLite 回滚保旧库，不动 catalog.json）。

### 9. `sync(document)`（db.py:1449-1467）

1. `is_fresh(document)` 为真 → return False（未变更）。
2. `reconcile(document)`；**仅** `sqlite3.DatabaseError` 被捕获 → 自愈：
   `reset()` + `rebuild(document)`（可重建库保证不变）。**CatalogStaleWriteError
   是 OSError，不被捕获，穿透 sync**（§1 的类型事实）。
3. return True。调用序注意：无 dirty-set 知识的调用方走 sync；热路径走 apply_changes。

### 10. `is_fresh(document)`（db.py:1427-1447）

三键门，任一失败 → False：
1. `self.revision() != document.catalog_revision`（None != int → False）；
2. `schema_version` 键缺失/解析失败 → False；`int(raw) != document.schema_version` → False；
3. `index_schema_version` 键缺失/解析失败 → False；`int(raw) == INDEX_SCHEMA_VERSION`
   （**等值**，非 ≥；但对比的是 Python 侧常量 5，与 load_document 的"≥5 下限"是
   两个不同门——db.py:292-310 注释钉过两者混淆的数据丢失坑）。

### 11. `reset()`（db.py:1042-1054）

`close()` 后删 `db_path` + `""`/`"-journal"`/`"-wal"`/`"-shm"` 四个后缀文件，
`FileNotFoundError/OSError` 全吞（尽力删除）。随时可调：库完全可从 canonical document
重建；清损坏文件后再 rebuild 用。

### 12. `load_document()`（db.py:1588-1609）——入口语义（深读属 R2/R3，此处只冻结门）

- 文件不存在 → None；`store_version()`（= `index_schema_version` 键，None/解析失败 →
  None）`< STORE_SCHEMA_VERSION(5)` → None；`_load_document_once` 抛
  DatabaseError/OSError/ValueError/TypeError → None。调用方回落 legacy JSON 路径。
- **floor 语义（≥5，非等值）**：`index_schema_version` 也会因纯索引布局变化而动，
  等值门会让健康 canonical 库被误判为外来库并从过期 manifest 重建（潜在数据丢失，
  db.py:1595-1599 注释钉过）。C++ 侧 `CatalogRepository::status()`（repository.cpp:262）
  已实现同语义。
- `_load_document_once`（1611-…）用 `BEGIN`（deferred 读快照）；V11 表缺失 → 空集合
  （不设防 SELECT 会抛 → load_document None → 误降级）。

---

## ② 冻结 C++ API 提案

风格基线：`libs/catalog` 现有命名（Python 名保留优先：DirtySet/Tag/DocumentIndex 先例；
自由函数 + 参数结构体：`audit_catalog(document, path, bindings)` 先例；错误通道
`domain::DataError`/`domain::Result`，无异常）。C++20、Qt-free、不触 AppContext。

**新文件**：`libs/catalog/include/pwb/catalog/apply_changes.hpp` + `libs/catalog/src/apply_changes.cpp`
（加入 pwb_catalog target_sources，CMake 先例同 D2）。`apply_changes` 这名字对 db.py
可 grep，是本切片的主动词。

```cpp
// apply_changes.hpp — db.py 通用写通道移植（DirtySet / apply_changes /
// reconcile / rebuild / sync / is_fresh / reset；CONV-31b R1 契约冻结）。
#pragma once
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/sqlite.hpp"
#include "pwb/domain/errors.hpp"
#include <filesystem, optional, string, vector, unordered_map>

namespace pwb::catalog {

// ---- DirtySet（db.py:756-829）-------------------------------------------
// 8 个插入序 id 列表：mark 幂等且保持首见位（Python dict 语义）；重复 mark
// 不移动位置。asset_tags/version_tags 存 OWNER id。"id 不在 document == 删除"。
struct DirtySet {
    std::vector<std::string> assets, versions, runs, tags,
        models, model_versions, asset_tags, version_tags;

    void mark_asset(std::string_view id);        // 其余 7 个 mark_* 同型
    ...
    void merge(const DirtySet& other);           // 先 self 后 other 首见序
    bool is_empty() const;
};

// CAS 冲突的可编程识别（Python 用异常类型；C++ 走 DataError + detail 标记）。
inline bool is_stale_write(const domain::DataError& e);   // code==ConflictBaseVersion
                                                          // && detail["stale_write"]

// ---- apply_changes（db.py:1951-2177）-------------------------------------
struct ApplyLookups {   // O(Δ) id→对象映射（service _ensure_maps parity）；
                        // 空指针 → 从 document 全建（Python `or {}` 回退）
    const std::unordered_map<std::string, const DataAsset*>*   assets   = nullptr;
    const std::unordered_map<std::string, const DataVersion*>* versions = nullptr;
    const std::unordered_map<std::string, const DataRun*>*     runs     = nullptr;
};

struct ApplyChangesOptions {
    ApplyLookups lookups;
    std::optional<long long> expected_revision;  // 事务内 CAS；nullopt = 不比对
};

// 一事务提交 dirty（BEGIN IMMEDIATE → CAS → 各表删/插 → 三键戳 → COMMIT）。
// 冲突 → ConflictBaseVersion + 逐字中文消息 + detail{"stale_write":true}。
// schema 缺失（sqlite_master 无 sync_state）→ 内部转 rebuild_store 并返回其结果。
domain::DataError apply_changes(Database& db, const CatalogDocument& document,
                                const DirtySet& dirty,
                                const ApplyChangesOptions& options = {});

// ---- reconcile（db.py:2313-2475）------------------------------------------
// O(N) 对账 + 差异集走 apply_changes；空差异 → 仅三键戳（同一 CAS 契约，
// 消息用"同步"变体）。lineage 表不 diff（docstring 已知限度）。
domain::DataError reconcile(Database& db, const CatalogDocument& document,
                            std::optional<long long> expected_revision = std::nullopt);

// ---- rebuild 家族（db.py:1471-1487 / 2477-2604 / 1578-1586 / 1042-1054）----
// 单次全量重写：ensure_schema → _DELETE_ORDER 全删 → 按文档序全插 → 三键戳。
// 一个事务；无 CAS。
domain::DataError rebuild_once(Database& db, const CatalogDocument& document);

// 删 db + "-journal"/"-wal"/"-shm"（ENOENT/OS 错误全吞，尽力语义）。调用方
// 必须先 db.close()（RAII 等价 Python close()）。
void reset_store_files(const std::filesystem::path& db_path);

// rebuild 的两次尝试编排：attempt0 rebuild_once；CorruptDatabase → reset_store_files
// 后 attempt1；再败上抛。**要求传入的 db 处于关闭状态**（函数自开自关一个
// Database(Create)）——等价 Python rebuild 的 close() 前置。write_all == rebuild_store。
domain::DataError rebuild_store(const std::filesystem::path& db_path,
                                const CatalogDocument& document);

// ---- sync / is_fresh / revision（db.py:1449-1467 / 1427-1447 / 1210-1218）--
// 返回是否发生了变更。CAS 冲突（is_stale_write）与参数错误原样上抛，
// 仅 CorruptDatabase 触发 reset+rebuild 自愈。
domain::Result<bool> sync_store(Database& db, const std::filesystem::path& db_path,
                                const CatalogDocument& document);

// 三键门：revision==document.catalog_revision && schema_version==document.
// schema_version && index_schema_version==5（kStoreSchemaVersion，等值非下限）。
bool is_fresh(Database& db, const CatalogDocument& document);

// None 语义：文件/键缺失、int 解析失败 → nullopt（"缺失/不可读/损坏"统一哨兵）。
std::optional<long long> read_revision(Database& db);
std::optional<long long> read_sync_state(Database& db, std::string_view key);

}  // namespace pwb::catalog
```

错误通道决策（冻结）：`CatalogStaleWriteError` → `DataError{ErrorCode::ConflictBaseVersion,
<逐字中文消息>, Json{{"stale_write", true}}}`，配 `is_stale_write()` 谓词。
理由：(a) 不新增 domain::ErrorCode 成员（不动共享枚举，避免波及其他 swarm）；
(b) `ConflictBaseVersion` 语义就是"#411/#1220 基线冲突"的 catalog 同类；(c) detail
标记让 service 层（R4）可编程识别而不依赖消息文本。消息本体逐字保留（用户可见行为，
service.py:1005/1064 的 service 级 pre-check 消息属 R4，不在本切片）。

前置模型补齐（**接口冻结的一部分**，落地属 31b 实现期）：
- `models.hpp` 增 `struct Model` / `struct ModelVersion`（Python `Model`/`ModelVersion`
  1:1；`id/model_id/model_name/model_type/capability/provider/status/Json metadata/
  created_at/Json provenance` 与 13 列对应），`CatalogDocument` 增
  `std::vector<Model> models; std::vector<ModelVersion> model_versions;`（additive，
  默认空——对齐 models.py:289-291 "旧文档无此二列表也能加载"）与
  `int schema_version = kCatalogSchemaVersion;`（apply/reconcile 三键戳需要）。
  既有 `export_manifest` 的 passthrough_rows 可后迁到 typed 行（不阻塞本切片）。
- 行序列化单一来源：apply/reconcile/rebuild 共用一套 `*_row` 序列化 + upsert SQL
  常量（Python 569-735 的 "ONE serialization per table" 纪律）；与 R2 惰性读共用
  `row_mapping.hpp` 的行→模型方向。列序 = 表定义序（reconcile 的 `SELECT *` diff 依赖）。

实现要点（.cpp 内部，不进公共头）：`ordered_ids(db, table, ids)`（500-id 批、事务内、
既有按 rowid 升序 + 新 id mark 序尾接）；`reconcile_version_parents` /
`delete_version_keep_run_edges` / `reconcile_run_edges` / `delete_run_keep_version_edges` /
`version_owns_edge` / `run_covers_edge` / `write_run_ports` / `write_version_members`
（后两者**无条件先 DELETE 再 INSERT OR IGNORE**，且先跑防御性 CREATE TABLE IF NOT EXISTS）。

事务纪律：复用 `sqlite.hpp Transaction`（BEGIN IMMEDIATE + 析构 ROLLBACK）。CAS 在
Transaction 构造之后、第一条写语句之前执行。COMMIT 前 `sqlite3_changes` 无关紧要；
成功返回一律显式 `DataError(ErrorCode::Ok, "")`（⑥-1）。

---

## ③ 与其他轨道的依赖与接口点

- **R2（14 个惰性读）**：共享 `row_mapping.hpp` 行→模型单一序列化来源；R1 的写路径
  决定行形状（含 run_ports/version_members 的防御性 DDL 确保表总在），R2 的
  `get_*/list_*` 依赖"表缺失 → 空集合"读语义与 R1 的建表语义互补。R2 的
  `revision()` 惰性 baseline 读取直接用 `read_revision`。
- **R3（open 流程）**：`store_health` 已有（repository.hpp `status()`）；R3 的
  canonical-open 用 `load_document`（floor ≥5 已实现）；legacy 迁移/损坏恢复用
  `rebuild_store`（== Python `write_all`）；corrupt 流程的"隔离字节 + reset"用
  `reset_store_files`；R3 的单连接模型 = R1 §4 的 RAII 等价物结论。
- **R4（batch_save/service 深核）**：flush 缝（`_flush_canonical_locked` parity，
  service.py:1050-1084）= `read_revision` pre-check + `apply_changes(db, doc, dirty,
  {.lookmaps, .expected_revision=_flushed_revision})`；reconcile 回退路径 = `reconcile(
  db, doc, _flushed_revision)`。`ApplyLookups` 的三个 map 即 service `_ensure_maps`
  的增量维护物——**需要 DocumentIndex 暴露 map 访问器或 service 自持**（冻结建议：
  service 自持三个 `unordered_map<string, const T*>`，DocumentIndex 不改；R4 决定）。
  tags.hpp 的 `TagSaveHook = std::function<domain::DataError()>` 与 apply_changes 的
  返回类型已对齐（hook 内部调 apply_changes）。
- 上游依赖：`models.hpp` 的 Model/ModelVersion/schema_version 补齐（②）；不改
  sqlite.hpp / domain 头。

---

## ④ oracle 冻结场景建议（fixtures 候选）

按"行为面值得钉"排序（沿用 D2 的真实 import 冻结法，扩展
`generate_catalog_domain_fixtures.py`）：

1. **CAS 冲突（apply）**：expected_revision=5、库存 6 → 中止、消息逐字、库零变更
   （行数与三键不变）。含 expected_revision=0 且键缺失 → 也冲突的边界。
2. **CAS 冲突（reconcile 空差异）**：同上但走 reconcile，消息"同步"变体。
3. **CAS 成功 + 三键戳**：apply 后 sync_state == 文档 revision/schema_version + 5。
4. **rowid 保序**：mark 既有 A(老) + 新 B + 新 C + 既有 D(更老) → apply 后
   `ORDER BY rowid` = [D, A, B, C]（既有按 rowid、新按 mark 序）。
5. **删除分支级联矩阵**：asset 删（连带 asset_tags，不动 versions）；tag 删（连带
   两张关联表 + 撞名幸存者规则：预-#884 双 tag 撞 normalizer）；version 删 +
   run 覆盖边保留（_run_covers_edge 真/假两支）；run 删 + version 拥有边保留
   （_version_owns_edge 真/假两支）。
6. **derived 集合清空语义**：version members 变空 → 行被清（钉 C++ 现有
   `if (!members.empty())` 跳过清除的偏差不能进入本通道，见⑥-2）；ports 同理。
7. **reconcile 差异集**：六表各造 row-changed / db-only / doc-only；asset_tags/
   version_tags set 漂移；run io 漂移；ports/members 漂移；**表缺失但 doc 有
   ports/members → mark**（防御性建表分支）。
8. **reconcile 空差异 → 仅戳**：diff 后只有 revision 前进。
9. **rebuild 等价性**：`rebuild_store(doc)` 全量 dump == 逐批 `apply_changes` 的
   最终状态（I3）；_DELETE_ORDER 全清（含 working_copies/staging_leases——注意这
   两表 rebuild 会清空，apply 永不触碰）。
10. **sync 自愈**：健康+fresh → false；损坏文件 → reset+rebuild 后 true；
    CAS 冲突穿透（不被自愈吞掉）。
11. **is_fresh 三门**：每键单独致 stale。
12. **_ordered 500 边界**：>500 个 dirty id 的批取正确性（可选，行为面同构）。

掩码注意：revision/随机 id 段沿用 D2 两侧掩码；中文错误消息进 oracle 时按字节比对
（UTF-8）。

---

## ⑤ 有界偏离清单（如实）

1. **每线程连接池不移植**（§4）：C++ = 单连接 RAII `Database` + service 锁串行 +
   BEGIN IMMEDIATE 跨进程。`interrupt()`/探活/ident 回收全部无对应物——它们解决的
   问题（Python 线程生命周期 vs sqlite3 check_same_thread）在 C++ 不存在。`session()`
   上下文管理器 → 调用方作用域持有 `Database`。
2. **事务回滚路径**：Python 手写 try/except ROLLBACK + 池化连接残留防御
   （`if conn.in_transaction: rollback()`，2032-2033）；C++ `Transaction` 析构回滚，
   RAII 下不存在残留事务分支。
3. **`_rebuild_once` 的 DDL 位置**：Python `with conn:` 传统隔离级下 CREATE TABLE
   跑在隐式事务外；C++ 统一裹进一个 BEGIN IMMEDIATE——严格更原子，不可观测
   （DDL 全部 IF NOT EXISTS 幂等）。
4. **name_search 折叠**：ASCII fold（`search_fold` 先例，31-decisions D4；NFKC+
   casefold 不带）→ 非 ASCII cased 字母（Ü 等）与 Python 字节级不同，行为面同判。
5. **JSON 文本字节序**：Python `json.dumps(..., ensure_ascii=False)`（`", "`/`": "`
   分隔）vs nlohmann `dump()`（无空格）。同侧自洽；**混库**（Python 写过、C++
   reconcile）会因 metadata 字节差 mark dirty → 重写为 C++ 形状后收敛（值相等，
   字节不同）。oracle 对 metadata 列比较需解析后比（或接受一次漂移）。
6. **reconcile 的 group_concat 拆分**：tag_id 含 "," 时两边同样误判（共同偏离，
   原样保留以保同构）；集合比较两侧一致。
7. **set 迭代序**：Python `_reconcile_run_edges`/rebuild 的 `INSERT OR IGNORE`
   按 set 序（不确定性）；C++ 用确定序（mark/文档序）。PK 去重下终态等价，oracle
   不得依赖插入序。
8. **错误通道**：异常类型 → DataError code+detail（②）；`sync` 只自愈
   CorruptDatabase（对应 sqlite3.DatabaseError 的可映射子集：SQLITE_CORRUPT/
   NOTADB/READONLY 等），CAS 冲突穿透——语义等价，映射表需在实现期钉死。
9. **lookups 空值语义**：Python 空 dict 经 `or` 回退全建；C++ nullptr 回退——非空
   map 时行为相同，空 map 传参语义差异不可观测（结果同为全建）。
10. **`DirtySet.merge` 的 duck-typing**：Python 接受裸 set；C++ 只收 `const DirtySet&`。
11. **`_read_sync_state` 的连接丢弃自愈**：RAII 下调用方重建 `Database` 即等价；
    库内不再有"丢弃池条目"动作。

---

## ⑥ 风险 / 先例坑

1. **DataError 成功哨兵（D3）**：`DataError()` 默认 code=Unknown——apply_changes
   有 ~15 个返回点（每表错误早退 + 尾部成功），全部必须显式
   `DataError(ErrorCode::Ok, "")`；31 期三处踩坑先例（apply_run_ports 尾返回、
   port_error 初值、save hook 默认）。
2. **不要继承 repository.cpp 现有固定形状事务的三个偏差**（它们是 CONV-15/26 时代
   的简化，31b 通用通道必须以 db.py 为准）：
   a. `upsert_version_rows` 仅在 `!members.empty()` 时清 version_members
      （repository.cpp:723）——Python 无条件清（db.py:199-208），成员清空会留脏行；
   b. `upsert_version_rows` 无条件 `DELETE FROM lineage WHERE child_version_id=?`
      （repository.cpp:710-713）——Python 有 `_run_covers_edge` 保留规则；
   c. `upsert_run_rows` 的 run_ports 写入以 `table_exists` 为门（repository.cpp:800）
      ——Python `_write_run_ports` 防御性 CREATE（db.py:138）。
   同理 `bump_revision()` 的库内 +1 与本通道的"文档携带值戳"（§6-6）是两种 revision
   模型，不可混用（service flush 契约是后者）。固定形状函数是否退役/改造归 R4 决策，
   本切片只保证新通道不自它们复制代码。
3. **宏双重求值假阳性**：oracle replay 的 fixture 宏（27c-findings 先例）在断言
   表达式里二次求值会翻动计数——CAS/rowid 断言先落到局部变量再进宏。
4. **BEGIN IMMEDIATE 嵌套**：`Transaction` 不可嵌套（SQLite 报
   "cannot start a transaction within a transaction"）；apply_changes 内部转
   `rebuild_store` 时必须先结束当前事务再另开连接重建（Python 是顺序调用，无嵌套）。
5. **中文消息字面量**：源文件需 UTF-8 无 BOM；本机 g++ 16 直连编译无碍，MSVC CI
   侧需确认 /utf-8（或改运行时从常量表取）。消息必须逐字（含全角括号与分号）。
6. **`reset_store_files` 的前置 close**：WAL 模式下未关闭句柄时 unlink 在 Windows
   失败（Python reset 先 close 的原因）；契约已把"调用方先 close"写进签名注释，
   oracle 需要一个"句柄未关 → reset 尽力失败"的可跳过分支（平台相关，不做断言）。
7. **reconcile 的 `SELECT *` 列序耦合**：diff 与序列化共用列序常量，models.hpp 加
   Model/ModelVersion 列时必须同步（建议单一 `kModelColumns` 表驱动）。
8. **sync 自愈的捕获范围**：C++ 侧 DatabaseError 只有 sqlite 返回码，没有 Python
   异常类的粒度——映射过宽会把 CAS 冲突/参数错误吞进 reset+rebuild（数据丢失级
   偏差）。冻结：仅 SQLITE_CORRUPT* / SQLITE_NOTADB / SQLITE_READONLY 家族触发自愈，
   且 is_stale_write 永远优先穿透。
9. **事务内 DDL**：`_write_run_ports`/`_write_version_members`/删除路径的防御性
   CREATE TABLE 在事务内执行——SQLite 支持，但会使 schema cookie 前进、预备语句
   重编译；性能面（非正确性）注意 prepare 缓存策略别假设 schema 不变。
10. **`apply_changes` 的 lookups 指针存活**：map 指向 document 内对象，调用期间
    document 不可变——写进签名注释（service 在锁内调用，天然满足；测试侧易踩）。

---

R1 完，未改任何源码；仅新增本文档。
