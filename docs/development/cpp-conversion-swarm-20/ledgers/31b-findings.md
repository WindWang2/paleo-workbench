# CONV-31b findings — 契约冻结版 scope ledger（catalog 域 service/db 深核）

Branch `feat/cpp-catalog-service`（worktree `/home/kevin/project/worktrees/cpp-catalog-service`）。
本文是 CONV-31b 的**冻结法**：以 R1-R10 十份 recon（`31b-recon/`）为提案输入，
由契约冻结代理对冲突处终裁。Wave2 实现代理（A1-A8）以本文 + 已冻结头文件为唯一契约；
头文件签名与本文冲突时**以头文件为准**并回改本文。

裁决基准：① 更贴近 Python 语义者胜；② 更贴近 `libs/catalog` 既有风格者胜
（`domain::DataError`/`Result` 无异常通道、自由函数 + context/参数结构体、
save-hook 依赖注入、错误文本字节一致、显式 `ErrorCode::Ok` 哨兵 D3）。

抽查记录：冻结代理对 recon 引用的 Python/C++ 锚点做了 17 处独立复核，全部属实
（含 R2 的三处 repository 既有偏差、R5 的 gc.hpp lease 活读问题——见 §D/§F）。

---

## A. 移植面三列表（Python 源 → 语义要点 → C++ 目标 TU）

以 R1-R8 为基础合并；冲突处按 §D 裁决。所有新 TU 落 `libs/catalog/src/`，挂
`# BEGIN CONV-31B` target_sources 块（R9 ③；只加新 TU 不动既有列表）。

### A-1 db.py 写通道（R1）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `CatalogStaleWriteError`(244) | OSError 子类不被 sync 自愈吞掉；CAS 在 BEGIN IMMEDIATE 事务内 | `apply_changes.hpp`：`is_stale_write()` 谓词（§C-3） |
| `DirtySet`(756-829) | 8 桶插入序；mark 幂等且保持首见位；merge 先 self 后 other；id 不在 document == 删除 | `apply_changes.hpp` `struct DirtySet` |
| `apply_changes`(1951-2177) | 单事务；schema 缺失回退 rebuild；`_ordered` rowid 保序（500-id 批）；每表先删后插；lineage keep-rules（`_run_covers_edge`/`_version_owns_edge`）；三键 sync_state 戳为**文档携带值**；CAS 消息逐字 | `apply_changes.hpp/.cpp`（A2）`apply_changes()` |
| `_reconcile_version_parents`/`_delete_version_keep_run_edges`/`_reconcile_run_edges`/`_delete_run_keep_version_edges`/`_write_run_ports`/`_write_version_members` | 写侧 keep-rules + 无条件 DELETE→INSERT OR IGNORE + 防御性 DDL | `apply_changes.cpp` 私有（不进公共头） |
| `reconcile`(2313-2475) | 六表 `_symmetric_diff` + tags set 漂移 + run io/ports/members drift；lineage 表不 diff（已知限度）；空差异仍刷三键（"同步"消息变体） | `apply_changes.hpp` `reconcile()` |
| `rebuild/_rebuild_once`(1471/2477) / `write_all`(1578) | 两 attempt + reset 自愈；单事务全量重写；`_DELETE_ORDER` 子表先删；tags INSERT OR IGNORE（撞名容忍） | `apply_changes.hpp` `rebuild_once`/`rebuild_store` + `CatalogRepository::write_all`（A1 编排壳，§D-5） |
| `reset`(1042-1054) | close 后删 db + journal/wal/shm，尽力吞错 | `apply_changes.hpp` `reset_store_files()` + `CatalogRepository::reset()`（A1） |
| `sync`(1449-1467) / `is_fresh`(1427-1447) | 仅 DatabaseError 自愈；三键门（index_schema_version **等值** 5） | `apply_changes.hpp` `sync_store()`/`is_fresh()` |
| `revision/_read_sync_state`(1210/1196) | None = 缺失/不可读/损坏统一哨兵 | `apply_changes.hpp` `read_revision()`/`read_sync_state()`（单一来源，§C-6） |

### A-2 db.py 惰性读 + 查询 + WC/lease 簿记（R2，裁决见 §D）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| 14 个惰性单实体读(1745-1949) | rowid 序 = 文档序；`get_asset_models` 输出序 = 请求 id 首见序；direction 非 "output" 即 input；members/ports 表缺失 → 空 | `queries_sql.hpp/.cpp`（A3） |
| `search_assets`(2631) SQL 路径 | EXISTS-tag / json_extract `$."{key}"` / name_search LIKE ESCAPE；**无 ORDER BY、无 trashed 谓词**（include_trashed 折叠为后置过滤，R2 ⑤-2） | `queries_sql.hpp` `search_assets_sql()` |
| `catalog_aggregates`(2992) | stages 按 current_version_id JOIN（与 search 的任一版本 join 语义不同）；review falsy 跳过 | `queries_sql.hpp` `catalog_aggregates_sql()` |
| `list_versions/lineage_edges/assets_for_tag/versions_for_tag` | ORDER BY version_number / 无 / a.id / v.id | `queries_sql.hpp` |
| `find_managed_raw/find_external_by_path`(3107/3128) | **INDEXED BY 逐字保留**；prepare 失败 → nullopt → 调用方回退扫描 | `queries_sql.hpp` `find_managed_raw_sql()`/`find_external_by_path_sql()` |
| WC CRUD(1335-1425) | register = 裸 INSERT + `wc-`12hex + 本地 ISO-秒双时间戳；update 必刷 updated_at；全部吞错、零错误消息面；**不碰 revision** | `repository.hpp` 增补（A1 实现） |
| lease 写侧(1227-1331) | INSERT OR REPLACE per target、BEGIN IMMEDIATE、失败 → nullopt（保护不是闸门）；TTL 3600；本地 ISO-秒 | `repository.hpp` 增补（A1 实现） |
| `_read_rows`/`_safe` 降级 | 缺文件/无 schema/prepare 失败 → default 永不抛（服务层 warm 回退折叠，R2 ⑤-1） | queries_sql 全族统一口径 |

### A-3 store.py + open 流程（R3）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `store.load`(103-155) | L1-L5 五分支；L3 重晋升 + fsync_dir；L2/L4 消息骨架逐字（括号 detail oracle 掩码） | `repository.hpp` `load_manifest()`（A1；类型化 models，§D-8） |
| `_isolate_corrupt_file`(48-63) | `<name>.corrupt-YYYYmmdd-HHMMSS-<微秒6>`；失败返回原路径 | `repository.hpp` `isolate_corrupt_file()`（A1） |
| `store.save`(157-229) | 五步 + 首存 bak 种子（#372/C14）+ unchanged-skip（digest+mtime #1183） | `repository.hpp` `save_manifest()`（A1） |
| `open()` 健康分流(779-943) | 五值矩阵；error → verbatim CatalogError（防 #411）；corrupt → 隔离+reset；mtime 记账严格大于；lazy 早退（不建 maps 不 sweep） | `service_core.hpp` `open_catalog()`（A4；CatalogSession 并入 core，§D-6） |
| manifest mtime 记账(238-261) | sync_state key `manifest_mtime_ns`；记账永不搞挂 checkpoint | `repository.hpp` `recorded/record_manifest_mtime_ns()`（A1） |

### A-4 service.py 编排核（R4，瘦身后见 §D-7）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `_save/_flush_canonical_locked`(1015-1084) | serial 无条件最先 +1；批内 defer；失败 revision 回退不 reload；#411 pre-check + #1220 事务内 CAS | `service_core.hpp` `CatalogServiceCore::save()`（A4） |
| `_BatchSave`(153-217) | 最外层恰一次 flush；body 失败/空 pending → reload 放弃；overlay（#1139） | `service_core.hpp` `batch()`（BatchBody=std::function，§D-9） |
| `_reload_document_locked`(1086-1108) | 内存永不领先于盘的恢复原语 | service_core.cpp 私有 |
| `_CatalogMaps`(86-775) | 增量维护全套 + 三处不对称（dedup build 首胜/add 末胜；legacy 桥 build 首个 bridged 胜/rebridge 活性优先；单删留空桶键/bulk 删空桶键） | A4 内部实现（公共查询走 `index()`，§D-7） |
| mutation_serial/index_revision | 恒增不回滚；二元缓存键 `(catalog_revision, mutation_serial)` | `service_core.hpp` 访问器 |
| `_maybe_checkpoint_manifest_locked`(1110-1126) | 节流：manifest 不存在且 ≤1 突变才补写 | `service_core.hpp` `checkpoint_manifest_throttled()` |

### A-5 working-copy 生命周期（R5）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| 状态机(1335-1425+2270-2643) | checked_out/dirty/committing；committed/abandoned = 行删除；登记全部 best-effort | `working_copy.hpp/.cpp`（A5） |
| `create_working_copy`(2270) | 复用判定序 1-6（活行复用/死行删/盘上 fail-closed #1211/Permission 重试 4 次） | `working_copy.hpp` `create_working_copy()` |
| `recover_working_copies`(2465-2523) | 判定顺序 = 缺文件先于 committing；source_uri 命中；telemetry 事件 | `working_copy.hpp` `recover_working_copies()` |
| `commit_working_copy`(2525-2643) | 两段式；#1218 新资产无锁窗口 + `_pending_commit_assets`；W3 崩溃窗 parity 保留 | `working_copy.hpp` `commit_working_copy()` |
| `_payload_staging_lease`(1644) / `_staging_target`(1623) | RAII lease；键 = 磁盘目录名（outputs 非 output） | `working_copy.hpp` `StagingLeaseGuard`/`staging_target()`（单一来源，§D-10） |
| gc.hpp lease 活读修复 | active_staging_targets 现读文档快照（gc.cpp:178-183）≠ Python 直查 sqlite（db.py:1289-1308）——**已复核属实** | A5 在 gc.hpp/gc.cpp 增 `active_staging_targets_live()`（§F-2） |

### A-6 resolve 阶梯 + trash 状态机（R6）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `resolve_path`(1502-1544) + `_fallback_identity_ok`(1546) | 七梯；R4-R6 身份门失败 = 继续降梯；sha256 梯→size 梯→fail-closed（#1140/#1221）；docstring 与代码分歧以**代码**为准 | `resolve.hpp/.cpp`（A6） |
| trash/restore/purge(3251-3661) | 锁内两段序（tombstone→save#1→搬移→save#2）；tombstone 四键形状；`_active_current_candidate` = 文档序末位；purge refcount+僵尸+二分资产；回滚矩阵 | `trash_service.hpp/.cpp`（A6；save 钩子带 DirtySet，§D-11） |
| `_probe_trash_payload`(3304) | trash/{vid} 顶层排序后第一个**文件**；对目录树 payload 无效（契约，非偏离） | `trash_service.hpp` `probe_trash_payload()` |

### A-7 模型注册表 + 治理 + promote（R7）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `Model/ModelVersion` DTO | 15 列；status 双默认（DTO "production" / 注册 "demo"）；JSON 列 ensure_ascii=False | **models.hpp 已完整实装**（本代理交付，含 JSON codec） |
| register/get/list(2815-3035) | 刷新规则矩阵（truthy 门、force_status、provenance 键级合并、no-op 不 save）；锁外哈希 | `model_registry.hpp/.cpp`（A7） |
| `promote_model`(3043) | 门禁 → 三元突变 → 单事务双行 | `model_registry.hpp` `promote_model()` + `repository.hpp` `promote_model_transaction()`（A1） |
| `find_production_model`(3090) | 淘汰链 + 门禁重验（require_input_schema=False 读豁免不可修） | `model_registry.hpp` |
| `update_asset_metadata`(3205) | governance 规范化（policies.hpp 已有）+ None/"" 删键 + no-op 不 save + 快照回滚 | `asset_metadata.hpp/.cpp`（A7） |
| `promote_version`(3665) | run 形状/metadata 形状冻结；#849-1 锁内重分配；payload 复制不移动 | `version_promote.hpp/.cpp`（A7，纯形状）+ `repository.hpp` `commit_promote_transaction()`（A1） |

### A-8 v11 bundle 编排（R8）

| Python | 语义要点 | C++ 目标 |
|---|---|---|
| `place_managed_tree`(storage.py 542-615) | T1-T8 分支序；逐成员原子放置；全成员或无；**不走 CAS**；Path 元组排序（§E-7） | `dedup.hpp` 追加声明 `place_managed_tree()`（A8 实现） |
| `register_bundle_version`(216-402) | Phase A-E；A7 交错命名池；copy-then-delete（P1-2）；version_dir_rel 从布局推导（P1-1）；回滚阶梯 | `v11_bundle.hpp/.cpp`（A8） |
| `_validate_member_rel_path`(408) / `member_path` | 绝对/`..`/空三拒；POSIX `\` 不是分隔符（逐字保真） | `v11_bundle.hpp` `validate_member_rel_path()`/`bundle_member_path()` |
| `verify_bundle_integrity`(425) | verified<unknown<modified<missing；尾部聚合校验；仅 modified 带 actual_sha256 | `v11_bundle.hpp` |
| bundle working-copy(463-586) | 复用 R5 状态机；`source_size_bytes=None` 防 dirty_hint 误报 | `v11_bundle.hpp`（复用 `WorkingCopyContext`，§D-12） |
| `migrate_run_ports` 持久化半段 | 决策面已在 v11_policy；补 DirtySet.mark_runs + save | v11_bundle.cpp（A8） |

---

## B. 文件所有权地图（Wave2 八个实现代理，零交集）

冻结代理已写：models.hpp/models.cpp（完整实装）、repository.hpp（仅追加声明）、
dedup.hpp（仅追加声明）、10 个新头（签名冻结）。**实现代理只写自己的 .cpp 与
下表列出的既有文件**；公共头再有改动需回冻结代理。

| 代理 | 独占文件（写权限） | 交付内容 |
|---|---|---|
| **A1** | `src/repository.cpp`、`src/row_mapping.hpp` | ① `load_manifest`/`save_manifest`/`isolate_corrupt_file`/`catalog_manifest_file`/`catalog_manifest_bak_file`（R3）；② `write_all`/`reset`/`recorded_manifest_mtime_ns`/`record_manifest_mtime_ns`；③ WC CRUD 补齐（get_by_path/get_live_for_source/list/register）；④ lease 写侧四函数；⑤ model 事务四函数（upsert_model/upsert_model_version/promote_model_transaction/commit_promote_transaction）+ `commit_working_copy_transaction` + `load_document` 增读 models/model_versions（**ORDER BY rowid**，R7 ⑥-1）+ `writable_database()`；⑥ **R2 三处既有偏差修复**：`insert_working_copy` INSERT OR REPLACE→裸 INSERT、`set_working_copy_state` 补 updated_at、三窄写去 bump_revision；⑦ row_mapping.hpp 增补 `run_from_row`/`tag_from_row`/`model_from_row`/`model_version_from_row`（A3/A2 共用，单一事实源） |
| **A2** | `src/apply_changes.cpp` | apply_changes.hpp 全部函数体（DirtySet/mark/merge、CAS、rebuild_once/rebuild_store/reset_store_files/sync_store/is_fresh/read_revision/read_sync_state、写侧 keep-rules 私有件） |
| **A3** | `src/queries_sql.cpp` | queries_sql.hpp 全部（14 惰性读 + 8 查询；like_escape_literal file-local 同文复制，R2 ②-1） |
| **A4** | `src/service_core.cpp` | service_core.hpp 全部（open_catalog 编排 = R3 矩阵逐行；CatalogServiceCore：save/flush/batch/serial/maps 增量维护/reload/checkpoint/export/close；内部 CatalogEntityStore+CatalogMaps 不进公共头） |
| **A5** | `src/working_copy.cpp`、`include/pwb/catalog/gc.hpp`、`src/gc.cpp` | working_copy.hpp 全部（状态机/recover/commit/StagingLeaseGuard/staging_target）+ **gc lease 活读修复**：gc.hpp 增 `active_staging_targets_live(Database&, cutoff_iso)`（或等价重载），sweep 复验路径改用活读 |
| **A6** | `src/resolve.cpp`、`src/trash_service.cpp` | resolve.hpp + trash_service.hpp 全部 |
| **A7** | `src/model_registry.cpp`、`src/asset_metadata.cpp`、`src/version_promote.cpp` | model_registry.hpp + asset_metadata.hpp + version_promote.hpp 全部 |
| **A8** | `src/v11_bundle.cpp`、`src/dedup.cpp`（仅追加 place_managed_tree） | v11_bundle.hpp 全部 + dedup.hpp 的 place_managed_tree 实现 |

共享文件协议（追加式，非独占）：
- `libs/catalog/CMakeLists.txt`：唯一 `# BEGIN CONV-31B … # END CONV-31B` 块（R9 ③ 格式），各代理**只追加自己的 src 行**，不改他人行。
- `tests/cpp/data/CMakeLists.txt`：Wave3 验证阶段统一挂（R10 ⑥-2），Wave2 不动。
- `models.hpp`/`repository.hpp`/`dedup.hpp`/10 个新头：冻结代理独占；Wave2 期间冻结（发现缺口 → 回冻结代理，不自行改签名）。

---

## C. 共享面接口契约

### C-1 DirtySet（apply_changes.hpp，A2 实现）

8 桶 `std::vector<std::string>`（assets/versions/runs/tags/models/model_versions/
asset_tags/version_tags）。`mark_*` **幂等且保持首见位**（Python dict 语义，
`_ordered` 的 rowid/文档序依赖）；`merge` 先 self 后 other 首见序；`is_empty`。
asset_tags/version_tags 桶存 OWNER id。"id 不在 document == 删除"。
内部去重策略（伴随 set 与否）归 A2，序语义是验收线。

### C-2 SaveHook 家族（统一命名）

`apply_changes.hpp` 冻结唯一别名：

```cpp
// 模块自知脏集（service.py _save(DirtySet) parity）：非 Ok 返回触发模块内内存回滚。
using SaveHook = std::function<domain::DataError(const DirtySet&)>;
```

trash_service / model_registry / asset_metadata / v11_bundle(BundleSeams.save)
全部消费 `SaveHook`（裁决 §D-11）。已交付的 `tags.hpp TagSaveHook`（零参）保持
不动——TagStore 内部自知脏集，零参即足；记录为风格例外，不要求回改。

### C-3 ErrorCode 策略（采纳 R1，驳回 R4 新增枚举）

**不新增 `domain::ErrorCode` 成员**。`CatalogStaleWriteError` → 
`DataError{ErrorCode::ConflictBaseVersion, <中文消息逐字>, detail["stale_write"]=true}`，
配 `apply_changes.hpp` 的 `inline bool is_stale_write(const domain::DataError&)`。
五处 Python catch 面（open error 分流/export_manifest/flush/ensure_index_fresh/
rebuild_index）全部以谓词判别。理由：(a) 不动共享枚举避免波及其他 swarm；
(b) ConflictBaseVersion 语义即 #411 基线冲突的 catalog 同类；(c) detail 标记
使 service 层可编程识别而不依赖消息文本。消息本体逐字（两条变体：保存/同步）。

WC register 的 UNIQUE path 冲突（Python IntegrityError）用
`DuplicateOperation` + `detail["working_copy_path"]`（与 stale-write 区分；组合层
吞掉 = Python service.py:2351 pass）。

### C-4 事务内 CAS 纪律

CAS 比对发生在 `Transaction`（BEGIN IMMEDIATE）构造后、第一条写语句前；
`expected_revision=0` 且键缺失/解析失败（stored=None）也算冲突；冲突路径零写放大。
open/export 面只**读**基线，不得私建 revision 比较（R3 ⑥）。

### C-5 成功哨兵（继承 31-decisions D3）

所有 `DataError` 出口显式 `DataError(ErrorCode::Ok, "")`；本波新面逐处核对。

### C-6 revision 读单一来源

`read_revision(Database&)`/`read_sync_state(Database&, key)`（apply_changes.hpp，
A2）是唯一 revision 读；repository 既有 `current_revision()` 保持兼容不改语义；
service_core/queries 组合层一律经 read_revision。`CatalogRepository::writable_database()`
（A1）暴露连接给 apply_changes/queries_sql 自由函数族（db.py 模块级算法单连接模型）。

### C-7 staging target 键单一来源（裁决 §D-10）

`working_copy.hpp` 的 `staging_target(project_path, stage, asset_id)` +
`blob_staging_target(project_path)`（A5 实现）；version_promote/v11_bundle/
gc 键格式全部消费它。键 = `<proj>.artifacts/<磁盘目录名>/<asset_id>`
（OUTPUT→"outputs"，非 stage.value）。

### C-8 stage 目录名双源收敛（R8 ⑥-2）

place_managed_tree 引入第三处 stage→目录映射时必须收敛到单一来源
（models.hpp `kStageDirs` 或 trash.cpp `stage_dir_name` 二选一提为共享），A8 落地时
在 dedup.cpp 注明选择；禁止第三份字面量表。

### C-9 WC 注册表真相 = sqlite（裁决 §D-13）

working_copies 行的读判定（live_for_source/by_path/list）走 repository 读 API
（sqlite 直读）；`document.working_copies` 只是 load 时快照，**不得**作为注册表
判定依据（与 lease 活读同理）。

### C-10 行映射单一来源

`row_mapping.hpp`（A1 独占写）承载 asset/version/run/tag/model/model_version
六 mapper；queries_sql.cpp / repository.cpp / apply_changes.cpp 共用，禁止各自
file-local 复制。列出显式列名（禁 SELECT * 按位取数依赖）。

---

## D. 裁决记录（两轨冲突终裁）

| # | 冲突 | 裁决 | 理由 |
|---|---|---|---|
| D-1 | StaleWrite 编码：R1（复用 ConflictBaseVersion+detail）vs R4（新增 ErrorCode 成员） | **采 R1** | §C-3；不动共享枚举、语义同源、可编程判别 |
| D-2 | DirtySet 容器：R1 vector 保序 vs R4 "vector+并存 set" | **冻结 8×vector + 幂等保序 mark 契约**；set 伴随是 A2 内部优化 | 序语义才是契约；容器细节非公共面 |
| D-3 | apply_changes 归属：R1 自由函数（apply_changes.hpp）vs R4 CatalogRepository 成员 | **采 R1 自由函数**，repository 增 `writable_database()` 桥接 | db.py 是模块级算法；repository.cpp 已 51K 行；自由函数对 db.py 可 grep |
| D-4 | reconcile 空差异三键戳：R1 单列（并入 reconcile） | 采 R1（消息"同步"变体） | Python 同一函数两变体 |
| D-5 | write_all 归属：R1 `rebuild_store(path,doc)` vs R3 `repository.write_all(doc)` | **两者都冻结、分层**：`rebuild_once(Database&,doc)`（A2 原语）；`CatalogRepository::write_all(doc)`（A1 编排壳 = close→rebuild_store 两 attempt 语义） | R3 的编排需要成员形态（close 前置）；R1 的原语需要连接形态（apply_changes schema 回退复用） |
| D-6 | open 产物：R3 `CatalogSession` 结构体 vs R4 `CatalogServiceCore` 类 | **合并**：`open_catalog()` 直接返回 `Result<CatalogServiceCore>`；CatalogSession 消解，report 经 `core.open_report()` | 二者本就是同一服务面的种子与终态；少一个中间类型，seam 模块不受影响 |
| D-7 | service_core 公共面：R4 三类（EntityStore/Maps/Core）全公开 vs 瘦身 | **只冻结 CatalogServiceCore 公共面**（document()/index()/维护 API/save/batch/serial/checkpoint）；EntityStore+Maps 为 A4 cpp 内部（R4 设计为内部基线，DocumentIndex 复用谓词、作重建等价 oracle） | DocumentIndex 已公开提供查询面；少冻结即少风险；R4 的不对称语义仍由 A4 增量实现保真（oracle 钉） |
| D-8 | ManifestLoad 的 models 载体：R3 Json 透传 vs R7 typed DTO | **typed**（`CatalogDocument.models/model_versions` + `Model/ModelVersion` codec 本代理已交付） | 透传是"无域读模型"的临时妥协；DTO 已一次到位，load/save 均走类型化；repository.cpp 既有 export passthrough 不回归（R7 ⑥-7 维持） |
| D-9 | batch 形态：R4 template batch(F&&) vs 库无异常纪律 | **`batch(const BatchBody&)`，BatchBody = std::function<DataError()>**；begin/end 配对不作公面 | 库风格无异常（R9 ③）；std::function 可落 .cpp，模板不能 |
| D-10 | staging target 双提案：R5 `staging_target(project_path,…)` vs R7 `promote_staging_target(artifacts_dir_name,…)` | **采 R5**，version_promote.hpp 不再声明同名物 | R5 形态自含（Python `_staging_target` 同构）；R7 形态把 artifacts 名推导推给调用方 |
| D-11 | save 钩子签名：R6 零参（TagSaveHook 先例）vs R7 typed saver | **统一 DirtySet 携带式 `SaveHook`**（§C-2）；tags.hpp 零参例外保留 | 零参使 trash/purge 的脏集无法告知调用方（被迫全量 reconcile，语义弱于 Python）；DirtySet 本波即冻结，"先零参后升级"的理由消失 |
| D-12 | R8 `WorkingCopyRegistrySeam` 虚接口 vs R5 `WorkingCopyContext` | **采 R5 context**，v11_bundle 直接收 `WorkingCopyContext&` 调 A5/A1 原语 | 单一注册表实现；虚接口五方法与 repo CRUD 一一重复；GcContext 先例 |
| D-13 | WC 读侧：R5 文档过滤 vs R2 repository 读 API | **采 R2**（sqlite 为真相） | Python WC 读全走 sqlite；document.working_copies 快照会因本进程 register/update 而陈旧（与 lease 活读同构的一致性论据） |
| D-14 | prune_stale_staging_leases 参数：R5 cutoff_iso vs R2 ttl_seconds | **采 R2**（`optional<double> ttl`，默认 3600） | Python `prune_stale_staging_leases(ttl=None)` 同构；cutoff 内部算 |
| D-15 | gc.hpp 修改权：冻结代理不写 gc.hpp（任务书文件清单外） | A5 独占 gc.hpp/gc.cpp 的 lease 活读修复 | 修复与 working_copy.cpp 同代理交付，避免跨代理协调 |
| D-16 | row_mapping.hpp 增补权：R2 提案让 A3 加 mapper，但任务书 A1 独占 row_mapping.hpp | mapper 增补归 **A1** 交付清单（B 表 A1-⑦）；A3 只消费 | 保持文件所有权零交集 |

---

## E. 有界偏离总表（各轨合并去重，实现代理不得超出此表）

编号 `B-n`；来源轨标注。oracle 掩码/断言策略随条目。

| # | 偏离 | 来源 |
|---|---|---|
| B-1 | 连接池/懒开/线程探活不移植：单连接 RAII `Database` + service 锁 + BEGIN IMMEDIATE 跨进程 | R1/R2/R4 |
| B-2 | `_safe`/warm 回退折叠：读函数缺文件/表/prepare 失败统一静默 default（锁死窗口 nullopt 无法区分 miss，接受） | R2 |
| B-3 | include_trashed 后置过滤折进 search_assets_sql（SQL 文本保持无谓词） | R2 |
| B-4 | ASCII fold（无 NFKC）：name_search/LIKE/tag 归一（继承 15-D6/31-D4，本波不扩大） | R1/R2 |
| B-5 | JSON 文本字节序：nlohmann dump 无空格 vs Python `", "`/`": "`——同侧自洽；混库 reconcile 一次漂移后收敛；oracle 对 JSON 列解析后比 | R1 |
| B-6 | set 迭代序→确定序（mark/文档序）；PK 去重下终态等价，oracle 不依赖插入序 | R1 |
| B-7 | `rebuild_once` DDL 裹进事务（严格更原子，幂等不可观测） | R1 |
| B-8 | lookups 空值：nullptr 回退 == Python 空 dict `or` 回退（不可观测） | R1 |
| B-9 | sync 自愈捕获面：仅 SQLITE_CORRUPT*/NOTADB/READONLY 家族；is_stale_write 永远穿透 | R1 |
| B-10 | 惰性读退化为普通点查（无 lazy/warm 状态机、无单槽缓存）；返回形状/排序 parity 全保 | R2/R4 |
| B-11 | id/时间生成源：random_device hex vs uuid4；strftime 本地 ISO-秒（形状 parity） | R2/R5 |
| B-12 | 错误通道折叠：异常类型→DataError code+detail（映射表 §C-3）；GovernanceError→InvalidArgument+逐字消息 | R1/R4/R7 |
| B-13 | status() 探针 sqlite_master vs Python 强制数据页 count（坏页漏检由 path B 兜底） | R3 |
| B-14 | 错误消息括号 detail：解析器文本差异，骨架逐字、括号内 oracle 掩码 | R3 |
| B-15 | pydantic 宽松校验 vs C++ 严格类型解析：字段缺/型错走 corrupt 同分支；fixture 留共同子集 | R3 |
| B-16 | mtime 记账 POSIX st_mtim ns（Windows 100ns tick 映射）；禁秒级 stat | R3 |
| B-17 | mkstemp 随机中缀/双微秒隔离覆盖/Windows gc 重试环：模式保留、值与平台细节不逐帧 | R3 |
| B-18 | RLock→std::mutex+`*_locked` 分层；ensure_index_ready 由无锁改持锁（更强） | R4 |
| B-19 | 上下文管理器→callable batch（异常传播/重载语义逐条保持） | R4 |
| B-20 | 节点存储：稳定地址实体图替代 Python 对象引用；CatalogDocument 值形态只在 materialize 边界 | R4 |
| B-21 | mutation_serial 用 uint64；revision 域 int→通道 long long | R4 |
| B-22 | maps 不对称语义（build 首胜 vs add 末位胜等三处）：A4 须按 Python 增量语义实现（若实现为 rebuild-on-mutation，三处不对称与 Python 分叉需另行登记——默认要求增量保真） | R4 |
| B-23 | W3 崩溃窗（copy-then-unlink 与元数据提交间）parity 保留，不引入反转 | R5 |
| B-24 | 登记表吞错→Result+日志（可观测性更强，行为等价） | R5/R8 |
| B-25 | resolve：`Path.resolve()` ↔ `weakly_canonical`（POSIX 存在前缀下等价）；绝对 join 替换语义断言钉住 | R6 |
| B-26 | probe 对目录树 payload 无效 = Python 原行为（契约，非偏离——写明防"修复"） | R6 |
| B-27 | purge 计数不含僵尸；`_rollback` 三分支语义冻结但不在此实现 | R6 |
| B-28 | register_model_version 重复检查收窄进提交窗（更严）；model 存在性检查时点镜像 Python | R7 |
| B-29 | 路径串 Linux 形态先行（Windows 分隔符差异沿用既有先例） | R7 |
| B-30 | Path 元组排序 vs 原生串比较：place_managed_tree 须显式实现组件向量比较（**保真要求**；若实现为字符串序则升级为已声明偏离——仅影响 ordinal 展示序） | R8 |
| B-31 | safe-id 非 ASCII 超集（15-D14）；Windows 分支不移植（fsync_dir 保 best-effort 语义） | R8 |
| B-32 | `register` 内部兜底断言（成员名不唯一）无回滚——保逐字，不加 Python 没有的 rmtree | R8 |
| B-33 | `json_extract` 大数 TEXT 化边缘（Python 自身同样错，两侧 parity）；`$."{key}"` 不转义（治理词表实践不可达） | R2 |
| B-34 | R2 三处既有偏差修复（INSERT OR REPLACE→裸 INSERT、updated_at、bump_revision 去除）与 gc lease 活读修复属**纠偏**不入偏离表——修复后与 Python 对齐 | R2/R5 |

---

## F. 不移植边界（31b 定案）

1. **db.py 连接设施**：`ThreadSafeCatalogSession`/`_ConnEntry`/`native_thread_alive`/
   `prune_dead_threads`/全池 close interrupt/`_drop_current_connection`——Python
   线程生命周期 × check_same_thread 问题在 C++ 不存在（R1 §4；31-gap §1 同判）。
2. **gc.hpp lease 活读修复不是新功能**：`active_staging_targets_live()`（A5）只是把
   Python 直查 sqlite 的原语义找回来；文档快照版本保留给无连接调用方（向后兼容）。
3. **懒开/warm/方法包装**：`_lazy/_warm/require_warm/_lazy_read_cache/_WARM_REQUIRED_METHODS`
   全家（Python GUI 性能形态）；`CatalogOpenOptions.lazy` 仅保留"空文档+基线+早退"语义。
4. **聚合/分页单槽缓存本体**：`(revision, serial)` 二元键语义经访问器暴露，缓存归调用方。
5. **edit_session.py / lifecycle.py / adapter.py / runtime.py / port.py**：31-findings A3
   既有定案不变；adapter 三级 dedup 梯的**宿主**是 service_core 的 dedup 查询面
   （R4 ③），协议壳不移植。
6. **`_rollback`（service.py 1569-1608）**：语义已冻结（R6 §1.6；R5 补偿链），实现散入
   A4/A5/A7 的失败路径，不设独立公共 API。
7. **register_version/register_result_asset/register_derived_store/import_raw/
   link_external 的完整服务编排**：事务核已由 repository 5 形状 + data_suite 承接；
   31b 只补 `_save` 通道与 maps 地基，编排壳不在本波（后续消费方切片）。

---

## G. 验证口径（Wave3，引 R10 手册）

- **fixture**：新文件 `tools/oracle/generate_catalog_service_fixtures.py` →
  `tests/cpp/data/fixtures/catalog_service/oracle.json`（不动 31 的生成器/oracle；
  真实 import 冻结；{ROOT} 占位一次全局 replace；随机 id/时间注入或两侧 regex 掩码）。
- **replay**：`tests/cpp/data/catalog_service_test.cpp`，注册
  `pwb_data_test(data_catalog_service catalog_service_test.cpp data.catalog_service)`；
  PWB_CASE 自注册 + `expect_json`（compare_json 语义比较）+ **negative self-check
  5 篡改必备**；`N cases, 0 failures` ×2。
- **挂载点**：`libs/catalog/CMakeLists.txt` 的 CONV-31B target_sources 块（Wave2 各代理
  追加）；tests CMakeLists 一行（Wave3）。
- **本机无 cmake**：g++ 16.2.1 直连（sqlite3.c C 单编 -fvisibility=hidden；55+ TU 闭包
  命令与 include 目录清单见 R10 ④；二进制只落 /tmp）。
- **冻结代理已做**：/tmp 聚合 TU `-fsyntax-only` 零 error（全部新头 + models.cpp 实装）。
- **行为面必钉**（各 recon ④ 节选）：CAS 冲突两条消息逐字 + 零写放大；rowid 保序
  （mark 序 = 新行序）；删除级联矩阵（run 覆盖边/version 拥有边）；惰性/急切 parity
  逐实体序敏感；search 双路径 sorted 集合相等 + golden SQL；WC 全程 revision 不变；
  crash 恢复矩阵 8 case + 判定顺序；trash 两段 save 失败回滚矩阵（W1/W2 窗）；
  register/promote 门禁矩阵 9 行 reason 逐字；bundle 命名池冲突矩阵 + copy-then-delete
  崩溃窗注入。

---

## H. 冻结交付物清单（本代理产物）

1. `docs/development/cpp-conversion-swarm-20/ledgers/31b-findings.md`（本文）。
2. `libs/catalog/include/pwb/catalog/models.hpp`：Model/ModelVersion 完整 DTO +
   CatalogDocument 增 `schema_version`/`models`/`model_versions` 三字段 +
   find_model（const+mut ×3）+ JSON codec（to_dict/from_dict，键序 = Python 声明序）；
   `src/models.cpp` 对应实现。
3. `libs/catalog/include/pwb/catalog/repository.hpp`：仅追加声明（A1 实现，
   注释标 `CONV-31b: implemented in Wave2-A1`）。
4. 新头 10 个（签名冻结，函数体归实现代理）：`apply_changes.hpp`、`queries_sql.hpp`、
   `service_core.hpp`、`working_copy.hpp`、`resolve.hpp`、`trash_service.hpp`、
   `model_registry.hpp`、`asset_metadata.hpp`、`version_promote.hpp`、`v11_bundle.hpp`。
5. `dedup.hpp`：追加 `place_managed_tree` 声明（A8 实现）。
6. `/tmp/pwb-31b-freeze/`：聚合 TU 编译自检产物（不入库）。

未创建任何 `src/*.cpp`（归实现代理）；未 commit。
