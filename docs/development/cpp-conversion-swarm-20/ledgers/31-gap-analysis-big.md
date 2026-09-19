# CONV-31 差距分析：catalog 大文件 vs libs/catalog C++

对照对象：`paleo_workbench/catalog/{db,service,service_v11,adapter,lifecycle,audit,storage,store}.py`
↔ `libs/catalog/include/pwb/catalog/{models,repository,dedup,gc,entity_view,paged_sql,sqlite}.hpp` + `libs/catalog/src/*.cpp`。

C++ 侧服务层编排在 `libs/data_suite`（`ingest_exec.cpp`、`commit_coordinator.cpp`、`run_coordinator.cpp` 消费 `repository.hpp` 的事务函数）——本报告以 libs/catalog 为覆盖基准，data_suite 只作参照。

结论速览：C++ 已覆盖**存储层核心**（v5 schema/健康分类/整文档加载/写入事务核/分页谓词/blob 放置/GC/manifest 写侧）。缺口集中在：① db.py 的通用 `apply_changes`/DirtySet/revision-CAS 与 reconcile；② service.py 的服务层状态机（open 流程、maps、batch_save、trash/restore/purge、working-copy 生命周期、模型注册表、tags、审计委托）；③ service_v11.py 全部语义层；④ adapter.py 的 dedup/legacy 桥；⑤ audit.py 的完整检查集；⑥ storage.py 的 trash/restore/bundle 放置。

---

## 1. db.py（3142 行）

**角色**：canonical SQLite 存储层——`CatalogIndex`（每线程连接池 + v5 schema DDL + 健康分类 + 整文档加载 + dirty-set 增量写 + reconcile/rebuild + 惰性单实体读 + 分页查询）。

**Public API 面**
- 模块级：`CatalogStaleWriteError`(244)、`DB_FILENAME`、`metadata_search_value`(253)、`like_escape_literal`(268)、`normalize_asset_search_name`(280)、`INDEX_SCHEMA_VERSION/STORE_SCHEMA_VERSION=5`(311)、`_SCHEMA_DDL`(356)、`DirtySet`(756, mark_*/merge/is_empty)
- `CatalogIndex`(921)：连接池 `open/connect/session/prune_dead_threads/close/drop_current_connection/reset`(949-1054)；`revision`(1210)；staging lease `acquire/release/heartbeat/active_staging_targets/prune_stale`(1227-1331)；working-copy CRUD `register/get_by_path/get_live_for_source/list/update_state/remove`(1335-1425)；`is_fresh`(1427)/`sync`(1449)/`rebuild`(1471)/`prime`(1489)/`store_version`(1500)/`store_health`(1510)/`write_all`(1578)/`load_document`(1588)；惰性读 `get_asset_model(s)/get_version_model/get_run_model/list_asset_models/list_asset_identity_rows/list_run_models/list_version_models_for_asset/list_all_version_models/child_version_models/list_tag_models/tags_for_version/tag_ids_for_asset`(1745-1949)；`apply_changes`(1951)；`reconcile`(2313)；查询 `search_assets`(2631)/`search_assets_page`(2822)/`count_assets`(2938)/`catalog_aggregates`(2992)/`list_versions`(3044)/`lineage_edges`(3055)/`assets_for_tag`(3079)/`versions_for_tag`(3093)/`find_managed_raw`(3107)/`find_external_by_path`(3128)
- 线程设施：`ThreadSafeCatalogSession`(832)、`native_thread_alive`(865)

**已覆盖（C++ 对应物）**
- v5 DDL / WAL / busy_timeout / 事务：`sqlite.hpp Database::open/ensure_schema/begin_immediate/Transaction`（sqlite.cpp）
- `store_health` → `repository.hpp status()`（Canonical/Legacy/Missing/Corrupt/Unreadable ≈ canonical/legacy/absent/corrupt/error）；`load_document` floor 语义（≥5）→ `open_read_only/open_read_write`
- rowid 保序 upsert（ON CONFLICT 非 REPLACE）→ `repository.cpp upsert_asset_in_transaction/upsert_version_rows/upsert_run_rows`
- `_search_assets_page/_count_assets/_paged_predicates/_PAGE_ORDER_COLUMNS` → `paged_sql.hpp search_assets_page_sql/count_assets_sql`（含 LEFT JOIN 仅 stage/size/version、100-id 批取 current_*）
- `normalize_asset_search_name/normalize_tag_name` → `entity_view.hpp normalize_search_name/normalize_tag_name`（有界 ASCII fold，NFKC 有意不移植，15-decisions D6）
- `active_staging_targets` + TTL cutoff → `gc.hpp active_staging_targets/default_lease_cutoff`
- run_ports/version_members 写侧序列化（103-241）→ `repository.cpp upsert_run_rows/upsert_version_rows`（models.hpp RunPort/VersionMember）
- `store_version` → `StoreStatus.index_schema_version`

**未覆盖（重点，行号）**
- `apply_changes`(1951-2177)：通用 dirty-set 单事务写 + **事务内 revision CAS**（`CatalogStaleWriteError` 比对在 BEGIN IMMEDIATE 内, 2036-2051）——C++ 只有 5 个固定形状的 `*_transaction`，无通用增量写
- `DirtySet`(756-829) 数据结构
- `reconcile`(2313-2475) 全量对账 + `_symmetric_diff`(738)；`rebuild/_rebuild_once`(1471/2477-2604)；`reset`(1042)；`sync`(1449)；`is_fresh`(1427)
- 每线程连接池全套：`ThreadSafeCatalogSession`(832)、`native_thread_alive`(865)、`prune_dead_threads`(961)、全池 `close` 语义(989)、`_disown_recycled_entry`(1153)——C++ 为单连接 RAII，**建议不移植**（连接模型不同）
- staging lease 写侧：`acquire_staging_lease`(1227)、`release`(1265)、`heartbeat`(1275)、`prune_stale_staging_leases`(1310)
- working-copy CRUD（表级语义：UNIQUE path、state IN 过滤、created_at 排序）：1335-1425（models.hpp 有 WorkingCopy 结构、repository 有 insert/remove/set_state 三个窄写，**读写 API 面不齐**）
- 惰性单实体读全套 1745-1949（14 个方法，lazy open #1212 依赖）
- 查询缺口：`search_assets`(2631, EXISTS-tag + json_extract metadata 过滤)、`catalog_aggregates`(2992, 浏览器徽章 group-by)、`list_versions`(3044)、`lineage_edges`(3055)、`assets_for_tag`(3079)、`versions_for_tag`(3093)、`find_managed_raw`(3107, INDEXED BY dedup 查询)、`find_external_by_path`(3128)
- `metadata_search_value`(253)/`like_escape_literal`(268)——LIKE 转义与 metadata 值规范化无 C++ 对应
- 连接期幂等 DDL + 单条失败 continue 的容错（1085-1133）

**依赖**：sqlite3/threading/uuid/datetime（无 Qt）；catalog.models、catalog.storage.catalog_dir_for。

**移植建议**：部分移植。优先级：① `apply_changes`+`DirtySet`+CAS（服务层移植前置）；② `find_managed_raw`/`find_external_by_path`（导入 dedup）；③ `catalog_aggregates`+`search_assets`；④ lease 写侧 + working-copy CRUD 补齐；⑤ reconcile/rebuild。线程池/native_thread_alive 不移植。

---

## 2. service.py（4711 行）

**角色**：`DataCatalogService`——唯一写入口；持锁、维护 id/dedup/legacy 索引（`_CatalogMaps`）、batch_save 合批、payload 放置编排、trash/restore/purge、模型注册表、tags、分页/聚合读。

**Public API 面（按方法组）**
- 会话：`open`(779, 类方法：健康流/legacy JSON 迁移/懒开)、`close`(958)、`export_manifest`(987)、`sweep_temp_on_open`(945)、`batch_save`(1128)、`ensure_index_ready`(1169)、`rebuild_index`(1173)、`index_revision`(1196)、`mutation_serial`(348)、`is_warm/require_warm/warm_document`(407-427)
- GC：`plan_gc/sweep_gc/cleanup_working_copies`(1201-1234, 委托 gc.py)
- 读：`get_asset/get_version/get_run`(1326-1375)、`list_assets/list_asset_identities/get_trashed_assets/list_runs/list_versions/list_all_versions`(1377-1471)、`resolve_asset_models`(1473)、`resolve_path`(1502)、`asset_id_for_legacy`(1390)
- 注册：`register_version/…_intermediate/…_output`(1729-1847)、`register_result_asset`(1849)、`register_derived_store`(1933)、`import_raw`(2055)、`link_external`(2145)、`materialize_external`(2208)、`create_derived`(2645)、`register_run`(2734)、`update_run_status`(2770)
- 缺失源：`find_missing_sources`(2232)、`relink_external_source`(2249)
- 工作副本：`create_working_copy`(2270)、`list_working_copies`(2396)、`working_copy_state`(2404)、`discard_working_copy`(2433)、`recover_working_copies`(2465)、`commit_working_copy`(2525)
- 模型注册表：`register_model/register_model_version/get_model*/list_models/list_model_versions/promote_model/find_production_model`(2821-3124)
- lineage：`get_lineage`(3128)、`get_lineage_chain`(3167)、`lineage_summaries`(3185)
- 治理：`update_asset_metadata`(3205)
- 回收站：`trash_version`(3365)、`trash_asset`(3403)、`restore_version`(3455)、`restore_asset`(3481)、`purge_trashed`(3536)
- 提升：`promote_version/promote_asset`(3665/3742)
- 校验：`verify_integrity`(3763)、`repair_ghost_runs`(3780)、`audit`(3815)
- tags：17 个委托方法(3841-4073)
- 搜索/分页：`search_assets`(4077)、`search_assets_page`(4120)、`count_assets`(4187)、`cached_/catalog_aggregates`(4233/4253)
- 其它：`rebase_artifact_paths`(4538)、`migrate_legacy_resources`(4585)、`_WARM_REQUIRED_METHODS` 包装(4616-4711)

**已覆盖**
- `register_version`/`register_result_asset`/`import_raw`/`update_run_status`/`rebase_artifact_paths` 的**事务核**（无锁/无回滚编排）→ `repository.hpp commit_version_transaction/publish_result_transaction/import_raw_transaction/finish_run_transaction/rebase_artifact_paths`（payload 放置归 data_suite `ingest_exec`）
- `plan_gc/sweep_gc/cleanup_working_copies` → `gc.hpp`（`sweep_temp_on_open` ≈ `sweep_gc(explicit=false)`）
- `_paged_rows_from_document/_asset_page_row`（文档回退路径）→ `entity_view.hpp search_assets_page/count_assets/asset_page_row`
- `_build_version` 的放置调用 → `dedup.hpp place_managed_file`
- `aggregate_member_sha256`（models.py，V11 用）→ `models.hpp`

**未覆盖（重点）**
- `open()` 全流程：健康分流、corrupt 隔离重命名、manifest mtime 记账（`_recorded/_record_manifest_mtime_ns` 238-261）、legacy JSON 事务迁移(779-943)
- 懒开/warm 机制：`_lazy/_warm/require_warm/warm_document/_lazy_*`(404-489, 1290-1324) + 方法包装(4692-4711)
- `_CatalogMaps` 维护索引全套（含 `managed_raw_by_key/external_by_path/assets_by_legacy_id`）与 `_add_*/_remove_*/_rebridge_legacy_keys`(86-775)
- `_save/_flush_canonical_locked/_reload_document_locked/_maybe_checkpoint_manifest_locked` + `_BatchSave`(153-217, 1015-1142)——revision 只在 flush 成功后前进、#411/#1220 双层 CAS
- `resolve_path`(1502-1544) + `_fallback_identity_ok`(1546-1565, #1140/#1221 fail-closed basename 回退)——**C++ 无路径解析语义**
- `_rollback`(1569-1608)、`_payload_staging_lease`(1644-1668)、`_staging_target`(1623)
- `register_derived_store`(1933-2037, 目录负载 + store_fingerprint)、`link_external`(2145-2206, external_stat 指纹)、`materialize_external`(2208)
- working-copy 生命周期全组(2270-2643)：复用/allow_replace、`committing` 状态机、crash 恢复(2465-2523)、`_pending_commit_assets` 僵尸防护(#1218)
- 模型注册表全组(2815-3124)：promote 安全门（`model_gates.can_promote_to_production`）、`find_production_model` 重验
- lineage：`get_lineage/get_lineage_chain/lineage_summaries`(3128-3201, 委托 lineage_graph.py)
- `update_asset_metadata`(3205-3247, governance 词表规范化)
- trash/restore/purge 状态机(3251-3661)：tombstone→持久化→搬移→路径回写的两段序、`_probe_trash_payload` 崩溃窗恢复、僵尸资产清理、共享 blob refcount
- `promote_version/promote_asset`(3665-3759, promote run + 锁内重分配版本号 #849-1)
- `repair_ghost_runs`(3780)、`verify_integrity/audit` 委托(3763/3815)
- tags 全组（委托 tags.py，C++ 完全无 tag 写语义）、`search_assets`（委托 queries.py）
- `_query_index_if_current`(4324)/聚合缓存(4233-4322)
- `migrate_legacy_resources`(4585, 委托 migration.py)

**依赖**：无 Qt（threading.RLock）；重度内部协作：audit/lineage_graph/queries/sources/tags/gc/model_gates/governance/telemetry/migration/checksum + service_v11/store/db/storage + `project.models._now_iso`、`project.paths.artifact_dir_for`。

**移植建议**：部分移植、按切片推进（这是主战场）。事务核已由 repository 承接。下一批建议：`resolve_path` + trash/restore/purge + working-copy 状态机 + `_save`/batch/revision-CAS（需要先做 db.py ①）。懒开/方法包装/单槽缓存是 Python UI 性能形态，不 1:1 移植。

---

## 3. service_v11.py（782 行）

**角色**：V11 Data Fabric API mixin——挂进 `DataCatalogService`（`service.py:80` `from …service_v11 import DataFabricV11Mixin`；`class DataCatalogService(DataFabricV11Mixin)`）。

**引用者（非死代码）**：`paleo_workbench/catalog/service.py`（mixin 组合）；surface 消费者 `adapter.py`(set_run_ports)、`lifecycle.py`(_annotate_*_port)、`explain.py`、`port.py`（协议声明）、`ui/project_controller.py`、`tests/fakes/inmemory_catalog.py`；测试 `test_v11_core/invariants/review1_fixes/scale/services`、`test_v13_domain_contracts.py`。

**Public API 面**：常量 `RETENTION_CLASSES`(52)、`MAX_BUNDLE_MEMBERS=64/MAX_RUN_PORTS=256`(63)；typed ports `set_run_ports`(74)/`_apply_run_ports`(105, ports⊆flat 不变量+预算)/`_coerce_ports`(149)/`inputs_by_role`(167)/`runs_consuming`(176)/`ports_for_run`(199, 匿名端口合成)；bundle `register_bundle_version`(216, 统一命名池+copy-then-delete)/`member_path`(417)/`verify_bundle_integrity`(425)/`create_bundle_working_copy`(463)/`commit_bundle_working_copy`(522)/`_validate_member_rel_path`(408)；pin `pin/unpin/is_pinned`(592-615)；retention `set_retention_class`(621)/`retention_class`(636)/`cleanup_eligibility`(650, 双门)/`version_lifecycle_status`(696)；`migrate_run_ports`(745, 操作→角色回填表 732)。

**已覆盖**：仅数据层——`models.hpp RunPort/VersionMember/aggregate_member_sha256`；`repository.cpp upsert_run_rows/upsert_version_rows` 会持久化 ports/members 行。

**未覆盖**：上述**全部语义层**——ports⊆flat 维护、端口预算、bundle 原子放置编排（`place_managed_tree` 调用）、成员名唯一池、pin/retention 词表、eligibility 双门、lifecycle status 聚合、migrate 回填。C++ 零对应。

**依赖**：shutil/pathlib；db(DirtySet)/models/storage + service 基类设施。无 Qt。

**移植建议**：部分移植——`_apply_run_ports`（单一写入核）、`register_bundle_version` 不变量、pin/retention/`cleanup_eligibility` 是值得移植的行为语义（库层）；`inputs_by_role/runs_consuming/migrate_run_ports/verify_bundle_integrity` 随 UI/工具需求。

---

## 4. adapter.py（903 行）

**角色**：`CoreCatalogAdapter`——把 `DataCatalogService` 适配到 `CatalogPort` 协议（唯一生产后端；业务模块经 `runtime.get_catalog` 消费）。

**Public API 面**：`service`(65)、`batch_save`(69)、`register_input`(239, 幂等导入 + legacy 桥 + dedup)、`begin_run`(505)/`set_run_ports`(533)/`complete_run`(544)、`register_intermediate/output/derived/derived_store`(658-733)、`attach_lineage`(736, 拒绝自环)、`query_lineage`(799, BFS 防环)/`direct_ancestors`(827)、`resolve_version/run/legacy_resource`(842-862)、`add_tags`(865)、`verify_integrity`(868)、`list_versions`(878)/`list_runs`(899)。关键私有：`_version_ref/_run_ref`(141/161, 保留键 `__domain_task_id` 等剥离)、`_tag_by_id` 缓存(80)、dedup `_find_managed_raw`(365)/`_scan_managed_raw`(421)/`_find_external_by_path`(439)/`_scan_external_by_path`(492)/`_batch_overlay_fresh`(348)、`_domain_task_asset`(188, 同任务重跑追加版本 #373)、`_bridge_legacy_id`(219)、`_register_produced`(551, 短锁两段式)。

**已覆盖**：本质无（`register_input` 的**放置**走 dedup.hpp；事务走 repository，但幂等/dedup/桥接判定全在 Python）。

**未覆盖**：上列全部；尤其 dedup 三级策略（当前索引→batch overlay→线性扫描自愈）、legacy 桥一次绑定、同 domain-task 资产复用、`_run_ref` 参数键约定。

**依赖**：无 Qt；service/checksum/types(DataVersionRef 等，C++ 无对应类型)。

**移植建议**：部分移植——dedup 查找与 legacy 桥语义应随 db 查询落 C++；协议适配层（DataVersionRef/Port）等 C++ 域类型建好后整体重写。不能退役（幂等/桥接是行为语义，不是纯胶水）。

---

## 5. lifecycle.py（1141 行）

**角色**：业务域操作（import/factor-map/prediction/export/finalize/QC/interpretation/manual-edit）→ `CatalogPort` 调用的唯一翻译层，含失败补偿（不留幻影 RUNNING run）与端口注解。

**Public API 面**：`register_resource_input`(56)/`resolve_resource_version`(112)/`migrate_project_resources`(124)/`resolve_input_versions`(147)；`register_factor_map_run`(169)/`register_persisted_factor_grids`(303)；`register_horizon_interpretation_run`(344)；`register_prediction_run`(461)；`resource_ids_for_paths`(523)；`register_export_run`(598)/`register_export_output`(632)；`register_map_compile_run`(679)；`register_qc_run`(731)；`register_finalize_run`(786)；`register_stratigraphic_correlation_run`(845)；`register_fault_interpretation_run`(902)；`register_modeling_run`(963)；`port_role_for_business_role`(1038)/`register_manual_edit_run`(1046)/`complete_manual_edit_run`(1096)。核心私有：`_versions_for_domain_tasks`(408, 最新 complete run 优先、有输出优先、排除 trashed)、`_fail_run`(246)、`_annotate_*_ports`(258/278)。

**已覆盖**：无（纯编排层）。

**依赖**：`project.models`（FactorMapTask/PredictionTask 等，TYPE_CHECKING）、port_roles、logging。无 Qt。

**移植建议**：**不移植/退役**（相对 catalog 库）：绑定 Python 域模型与 Port 协议，属应用层；C++ 侧由 data_suite 编排层按需重写。唯一值得提取的算法是 `_versions_for_domain_tasks` 的 run-graph 解析规则（新鲜度选择语义，若 C++ 有对应消费者）。

---

## 6. audit.py（696 行）

**角色**：结构一致性审计（只检测不修复）：`AuditReport/AuditIssue` + 17 类检查 + deep 重哈希 + 协作取消。

**Public API 面**：`AuditIssue`(72)/`AuditReport`(83, by_kind/by_severity/counts_by_kind/statistics/ok)、`audit_catalog`(122)；检查器 `_check_current_versions`(182)/`_check_lineage`(220, 三色 DFS 环检测)/`_check_run_links`(270)/`_check_run_outputs`(296)/`_check_science_run_inputs`(330)/`_check_provenance`(359)/`_check_stale_runs`(376)/`_check_output_claims`(416)/`_check_run_lineage_divergence`(450)/`_check_governance_metadata`(487)/`_check_tags`(517)/`_check_paths`(576)/`_check_payloads`(631, deep→verify_integrity、orphan 集成 plan_gc)。常量 `STALE_RUN_AFTER_SECONDS=24h`(69)。

**已覆盖**：`repository.cpp audit_catalog`(1154) 是**另一子集**（源自 queries/审计交叉检查）：orphan_version/dangling_current/run_missing_input/run_missing_output/run_incomplete/missing_payload/binding_*/duplicate_version_number/working_copy_missing_source——与 audit.py 仅 payload_missing/broken_run_link 两类语义重叠。

**未覆盖**：severity 三级、`AuditReport` 形状（checked 统计/cancelled/ok）、`invalid_current_version` 的 trashed/foreign 分支(199-217)、`lineage_cycle`(236-267)、`orphan_completed_run`(296)、`science_run_without_inputs`(330)、`unprovenanced_version`(359)、`stale_running_run`(376)、`multi_claimed_output`(416)、`run_lineage_divergence`(450)、`invalid_metadata_value`(487, governance 词表)、`dangling_tag_ref/unused_tag`(517)、`path_mismatch`(576, 布局校验 + trash 窗豁免)、`external_path_missing`(644)、`orphan_<kind>`(671)、`integrity_mismatch`(681)、cancel 协作(641)。

**依赖**：gc/models/storage/governance/project.paths；无 Qt；仅依赖 service 的 `_lock/document/resolve_path/project_path` 四点，易参数化。

**移植建议**：**整文件移植**（库层纯函数、无 UI 依赖）——与 repository.cpp 现有 `audit_catalog` 合并为一个语义完整模块是清晰的后续切片；注意 severity/cancel 契约需一并钉死。

---

## 7. storage.py（644 行）

**角色**：磁盘布局与原子放置：stage 目录、blob 内容寻址、managed file/tree 放置、trash/restore、working copy 复制。

**Public API 面**：`catalog_dir_for`(39)、`is_safe_entity_id`(44)、`ensure_catalog_layout`(70)、`working_dir_for`(85)/`trash_dir_for`(89)、`blob_dir_for`(100)/`blob_path`(105)/`is_cas_path`(111)、`has_blob`(130)/`blob_size`(135)、`place_blob`(179)、`trash_payload`(216)/`restore_payload`(255)、`safe_unlink`(296)、`purge_trashed_payload`(311, shared refcount)、`fsync_dir`(345)、`place_managed_file`(378)、`place_managed_tree`(542)、`create_working_copy`(618)；常量 `STAGE_DIRS/EXTRA_DIRS/BLOBS_DIRNAME`。

**已覆盖（dedup.hpp/cpp）**：`blob_dir_for/blob_path_for/has_blob/blob_size/place_blob/scan_blobs` ≈ 100-197；`place_managed_file`（单文件子集：safe-id 门、目标已存在拒绝、caller-digest 诚实拒绝、dedup 免拷贝采纳 re-hash 证明、错误串字节一致 D9）≈ 378-517；`fsync_dir/_make_readonly` ≈ `fsync_path_best_effort/make_read_only`；`ensure_catalog_layout` 隐含在放置内。

**未覆盖**：`catalog_dir_for`(39)（repository 由调用者传 sqlite 路径）；显式 `ensure_catalog_layout`(70)；`working_dir_for/trash_dir_for`(85/89)；`is_cas_path`(111)（dedup.cpp 内部有等价判定但**未导出**，trash/purge/audit 都需要它）；`trash_payload`(216-253, 原子搬移 + blob 豁免 + 目录树搬移)；`restore_payload`(255-293)；`safe_unlink`(296, Windows 只读属性处理)；`purge_trashed_payload`(311-337, shared refcount)；`_prune_empty_ancestors`(205)；`place_managed_tree`(542-615, V11 bundle 全成员放置)；`create_working_copy`(618-644)；`_sha256_verified` 免重哈希通道（C++ 有意偏差：总是 re-hash，D9）。

**依赖**：checksum.CHUNK_SIZE/models/project.paths；无 Qt。

**移植建议**：部分移植——下一批补 `is_cas_path`（导出）、`trash_payload/restore_payload/purge_trashed_payload`（trash 状态机前置）、`place_managed_tree`（V11 bundle 前置）、`create_working_copy`、`safe_unlink`。

---

## 8. store.py（229 行）

**角色**：`catalog.json` 便携清单（checkpoint/export manifest）：原子写 + `.bak` 回退 + corrupt 隔离。

**引用者**：`paleo_workbench/catalog/__init__.py:68`、`service.py:81`（`CatalogStore`、`catalog_file_for`）；测试 14 个文件：tests/{test_audit_catalog, test_catalog_sqlite_canonical, test_catalog_resolve_path_safety, test_catalog_lazy_open, test_catalog_manifest_guards, test_issue848_arch_hygiene, test_catalog_crash_safety, test_round3_convergence, test_catalog_lifecycle_acceptance, test_catalog_models, test_catalog_service, test_v11_invariants, test_v11_migration, test_catalog_scale, perf/test_catalog_scale}.py（非死代码）。

**Public API 面**：`catalog_file_for`(32)、`catalog_bak_file_for`(43)、`CatalogStore.load`(103, bak 回退→canonical 重晋升→双损坏隔离并 raise)、`CatalogStore.save`(157, 五步崩溃安全 + 首存种子 bak #372/C14 + unchanged-skip #1183)；私有 `_isolate_corrupt_file`(48)、`_seed_initial_backup`(66)。

**已覆盖**：写侧 → `repository.hpp export_manifest`（schema 1 全表 dump + revision、tmp+rename、`.bak` 保留、models/model_versions 透传）。`catalog_file_for` 的路径推导由调用者承担。

**未覆盖**：`load()` 全部——`.bak` 回退与重晋升(131-154)、canonical 损坏且无 bak 时的 `_isolate_corrupt_file` + CatalogError(120-130)、双损坏路径(136-146)；`save` 的 unchanged-skip（digest+mtime, 194-199）与首存 bak 种子(66-87)；`_last_write` 实例状态。

**依赖**：hashlib/json/os/tempfile；models/storage。无 Qt。

**移植建议**：部分移植——补 `load`（含 bak 回退）供 C++ open 流程对齐；unchanged-skip 是纯性能可缓；首存 bak 种子语义（防无备份窗口）建议随 load 一起做。

---

## 附：优先级汇总（建议切片序）

1. **db.apply_changes + DirtySet + revision-CAS**（服务层一切写路径的地基）
2. **audit.py 整文件**（合并 repository 现有子集）
3. **storage trash/restore/purge + is_cas_path 导出 + place_managed_tree**
4. **service: resolve_path、trash/restore/purge 状态机、working-copy 生命周期**
5. **service_v11 语义核（_apply_run_ports、bundle 不变量、pin/retention/eligibility）**
6. **db 查询补齐（find_managed_raw/find_external_by_path/aggregates/search_assets）+ adapter dedup/桥接语义**
7. **store.load（bak 回退）**；不移植：db 连接池/线程探活、lifecycle.py（应用层）、service 懒开/方法包装。
