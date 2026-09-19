# R9 — C++ 面貌与工程约定普查（CONV-31b service/db 深核前置必读）

Branch `feat/cpp-catalog-service`（worktree `/home/kevin/project/worktrees/cpp-catalog-service`）。
范围：`libs/catalog`（22 头 + 23 TU）、`libs/domain` 基座、`tests/cpp/data` 测试 harness、
`libs/data_suite` 编排先例、第三方依赖面。全部只读侦察，2026-09-19。

---

## ① 头文件 / TU 清单与 API 摘要

命名空间一律 `pwb::catalog`；模型/错误在 `pwb::domain`。每个头对应同名 TU
（唯一例外：`row_mapping.hpp` 是 src/ 内部私有头，无独立 TU；run_coordinator 逻辑在
data_suite 的 `run_coordinator.cpp` 但类声明在 `commit_coordinator.hpp`）。

| 头（include/pwb/catalog/） | TU | 导出面摘要 |
|---|---|---|
| models.hpp | models.cpp | 值类型 `DataAsset/DataVersion/DataRun/Tag/WorkingCopy/VersionMember/RunPort/LineageEdge/StagingLease`；聚合根 `CatalogDocument`（含 `find_asset/find_version/find_run` const+mut、`next_version_number`）；常量 `kCatalogSchemaVersion=1`、`kStoreSchemaVersion=5`、`kStageDirs[]`；自由函数 `aggregate_member_sha256` |
| repository.hpp | repository.cpp | `CatalogRepository`（见②）+ `StoreHealth/StoreStatus` + 自由函数 `audit_catalog(document, project_path, bindings)`（跨店一致性子集）+ `WorkspaceBindingRef/AuditFinding` |
| document_index.hpp | document_index.cpp | CONV-31 新增。`DocumentIndex`：不可变快照索引，构造即 `rebuild`；键集 = asset/version/run by id、`versions_of_asset`、`children_of`（parent_version_ids 反向）、legacy bridge（`asset_by_legacy_id`：exact id 优先、legacy_resource_id first-wins）、dedup 键（`managed_raw_for(source_uri,sha256)`、`external_for(path)`）、`version_count()`。自由函数 `managed_raw_dedup_key/external_dedup_key`。指针引用源文档——**任何 mutation 后必须 rebuild** |
| sqlite.hpp | sqlite.cpp | `Database`（RAII、move-only、`open(path,mode)` 工厂返回 `Result<Database>`、`execute/scalar_i64/table_exists/prepare`、`begin_immediate/commit/rollback`、`ensure_schema` 幂等 v5 DDL）；`Statement`（fluent `bind(int,string_view|int64|double)/bind_null`、`step()`→bool、`step_done()`、`text/int64/is_null`）；`Transaction`（RAII：构造 BEGIN IMMEDIATE，析构未 commit 则 ROLLBACK） |
| tags.hpp | tags.cpp | `TagStore(document, save_hook)`——**依赖注入先例**：`using TagSaveHook = std::function<domain::DataError()>`，构造时传入单事务保存缝（对应 service._save(DirtySet)）；#1182 惰性回滚 Journal（`class Journal` 私有前向声明）。API：add/remove/rename/merge/create/bulk_add/bulk_remove_tag、tag_usage、search_tags、delete_unused_tag、prune_unused_tags |
| policies.hpp | policies.cpp | 4 个纯策略层：governance（`GovernanceFieldSpec`/`governance_fields()`/`normalize_governance_value/_patch`/`governance_values/_display/_display_rows`）、intermediate_policy（`ArtifactPolicy`/`artifact_policy_for`/`known_artifact_policies`）、port_roles（`port_role_display`）、model_gates（**结构体注入先例**：`ModelGateFacts/ModelVersionGateFacts` 携带注册表事实，门函数 `can_promote_to_production` 从不 import 模型存储——依赖倒置） |
| trash.hpp | trash.cpp | storage.py 剩余面：`stage_dir_name`、`working_dir_for/trash_dir_for`、`is_safe_entity_id`、`is_cas_path`、`trash_payload/restore_payload`（Result\<string\>）、`purge_trashed_payload`（best-effort void）、`create_working_copy`（全拷贝，绝不硬链） |
| v11_policy.hpp | v11_policy.cpp | V11 纯决策核（无 IO）：常量 `kMaxBundleMembers=64/kMaxRunPorts=256/kRetentionClasses[]`；`coerce_ports/apply_run_ports/ports_for_run/inputs_by_role/runs_consuming/migrate_run_ports`；bundle 名字池 `plan_bundle_members`；pin `is_pinned/apply_pin/apply_unpin`；retention `validate_retention_class/retention_class_of/default_retention_for_stage`；`cleanup_eligibility/version_lifecycle_status`（`live_working_copy` 布尔是调用方注册表探针的注入缝） |
| sources.hpp | sources.cpp | `MissingSource/MissingSourceReport`、`missing_probe_path`（只探第一梯）、`find_missing_sources(cancel)`、`relink_identity_proof`、`relink_external_source(document,index,version_id,new_path,save,actor,now_iso)`——**save hook 注入 + 失败即还原 pre-mutation 字段**的先例 |
| queries.hpp | queries.cpp | `metadata_search_value`、`IntegrityReport`、`verify_integrity(cancel 逐 payload 轮询)`、`AssetSearchQuery`（struct 参数聚合）、`search_assets_scan`、`find_assets_by_tag/find_versions_by_tag` |
| entity_view.hpp | entity_view.cpp | 分页契约：`normalize_search_name/normalize_tag_name`（有界 ASCII fold，**唯一规范化定义点**）、`EntityPageQuery`（20 键行、name keyset cursor）、`asset_page_row/search_assets_page/count_assets` |
| paged_sql.hpp | paged_sql.cpp | `search_assets_page_sql/count_assets_sql(Database&, query)`——SQL 直读深分页，行形状与 entity_view 逐键一致 |
| refs.hpp | refs.cpp | DTO `DataVersionRef/DataRunRef/LineageEdgeRef`（`to_dict/from_dict` 精确键集）、`utc_now_iso()/new_ref_id(prefix)`（uuid4.hex[:16] 形状）、`IntegrityStatus` 枚举、`DisplayContext` + `version_display_payload`（16 键 display 契约，resolve_path 注入） |
| checksum.hpp | checksum.cpp | `CancelPoll = std::function<bool()>`；`sha256_file(path,chunk,cancel)`（1 MiB 流式、取消先于摘要更新）、`sha256_file_or_none`（OSError→nullopt）、`sha256_text`（CRLF/CR→LF，#998） |
| audit.hpp | audit.cpp | `AuditIssue/AuditStats/AuditReport`、`AuditContext{document,index,project_path,resolve_path}`、`audit_catalog(context,deep,stale_run_after_seconds,cancel)`——17 检测类、检测-only、协作取消返回 PARTIAL |
| explain.hpp | explain.cpp | `VersionExplanation`（to_dict）、`ExplainService(document,index)` 组合 `ImpactService`；entity_links 以 `vector<ImpactService::EntityLink>*` 可选注入 |
| impact.hpp | impact.cpp | `ImpactService(document,index)`：`downstream_stale/is_stale/upstream_impact/delete_impact/entity_staleness`；实例级 8 条 LRU 缓存（Python module-level 的对应物）；预算常量 `kMaxImpactNodes=20000/kMaxStaleItems=2000` |
| lineage_graph.hpp | lineage_graph.cpp | `build_lineage_chain(document,index,version_id,direction,max_depth,max_nodes)`（BFS、cycle-safe、诚实截断）、`compute_lineage_summaries`（memoized DFS：to_raw/broken/has_parents） |
| legacy_migration.hpp | legacy_migration.cpp | `LegacyResourceRow::from_json`、`migrate_resources(resources,project_path,document,now)`（now 注入）、`needs_migration`；反向镜像 `legacy_bridge_id/remove_legacy_resources_for_assets/remove_legacy_resources_by_ids/upsert_legacy_resource`（直接操作 .paleo.json 的 Json 树） |
| telemetry.hpp | telemetry.cpp | `catalog_events_path/record_catalog_event/read_catalog_events`——**best-effort IO 先例**：失败返回 false 永不上抛；撕裂行读取时跳过 |
| gc.hpp | gc.cpp | plan/sweep/cleanup_working_copies、`active_staging_targets/default_lease_cutoff`、kind 常量 `kGc*`；`GcContext` 非空指针契约 |
| dedup.hpp | dedup.cpp | CAS blob 店：`blob_dir_for/blob_path_for/has_blob/scan_blobs/place_blob`、GC keep-set `referenced_digests/plan_blob_gc/sweep_unreferenced_blobs`、`blob_metrics`、`place_managed_file`（`PlaceManagedOptions{keep_source,known_sha256,register_blob}`→`PlacedFile{rel_path,size_bytes,sha256}`）——dedup 快路径=调用方摘要+重哈希证明后 copy-free 采用 |

内部私有头 `src/row_mapping.hpp`：`pwb::catalog::rows::asset_from_row/version_from_row/parse_json_column`
——assets/versions 的行→模型映射唯一定义点（loader 与 SQL 分页共用；SELECT 列序是契约，注释里列死了）。

---

## ② repository.hpp 完整签名清单

```cpp
enum class StoreHealth { Canonical, Legacy, Missing, Corrupt, Unreadable };
struct StoreStatus { StoreHealth health; int index_schema_version; int catalog_revision; std::string detail; };

class CatalogRepository {
public:
    explicit CatalogRepository(std::filesystem::path sqlite_path);
    StoreStatus status() const;                       // 只读探针：sync_state 严格可读 + index_schema_version>=5 → Canonical
    domain::Result<CatalogDocument> open_read_write();  // 建父目录+建 schema+幂等种子 sync_state；Corrupt 报错绝不静默重建
    domain::Result<CatalogDocument> open_read_only() const;  // 无 schema 创建、无 WAL 切换；Missing → NotFound
    const std::filesystem::path& path() const;
    void close();                                     // 提前释放可写句柄（save-as 删除旧 artifacts 树前）

    domain::DataError export_manifest(const std::filesystem::path& manifest_path) const;
    // ↑ schema 1 全表 dump + catalog_revision；原子 tmp+rename；旧 manifest→.bak；
    //   models/model_versions 行原样透传（无域读模型，绝不丢注册表内容）

    // ---- 5 个固定形状单事务写（每个 = 1 事务 + revision bump）----------
    domain::DataError upsert_asset(const DataAsset&);
    domain::DataError upsert_version(const DataVersion&);
    domain::DataError upsert_run(const DataRun&);
    domain::DataError commit_version_transaction(const DataVersion&, const domain::AssetId&, const std::optional<domain::RunId>&);
    domain::DataError publish_result_transaction(const std::optional<DataAsset>& new_asset, const DataVersion&, const domain::RunId&);
    domain::DataError import_raw_transaction(const DataAsset&, const DataVersion&);
    domain::DataError finish_run_transaction(const domain::RunId&, const std::string& status, const domain::Json& extra_parameters);

    // ---- working copy 三件套 ------------------------------------------
    domain::DataError insert_working_copy(const WorkingCopy&);
    domain::DataError remove_working_copy(const std::string& working_id);
    domain::DataError set_working_copy_state(const std::string& working_id, const std::string& state);

    domain::DataError set_current_version(const domain::AssetId&, const domain::VersionId&, const std::string& updated_at);
    int rebase_artifact_paths();                      // save-as 后重写 <name>.artifacts/ 首段（含 trash original_path、model_versions artifact_uri）；返回重写数
    int current_revision() const;

private:
    // 复用件：upsert_asset_in_transaction / upsert_version_rows / upsert_run_rows
    // （行 + 派生表 lineage/version_members/run_inputs/run_outputs/run_ports 全量重写）
    // load_document(mode) / load_document_from(db) / bump_revision()
    std::filesystem::path sqlite_path_;
    Database db_;   // open_read_write 后驻留；const 方法内临时开只读连接
};
```

事务形态统一为（repository.cpp:847-853 先例）：

```cpp
Transaction transaction(db_);                       // BEGIN IMMEDIATE
auto error = upsert_asset_in_transaction(asset);
if (error.code != ErrorCode::Ok) return error;      // 早退 → 析构 ROLLBACK
bump_revision();
transaction.commit();
return DataError(ErrorCode::Ok, "");
```

**revision 语义**：`bump_revision()` = `catalog_revision` 自增（upsert 冲突时
`CAST(CAST(value AS INTEGER)+1 AS TEXT)`），并幂等种子 `schema_version='1'`、
`index_schema_version='5'`；open_read_write 也调它一次使"建库→重开"可用。
`current_revision()` 经 `status()` 读，不经驻留句柄。

`audit_catalog` 子集（自由函数版，repository.hpp:135）：orphan_version、dangling_current、
run_missing_input/run_missing_output、run_incomplete、missing_payload（managed+live 第一梯）、
binding_unknown_asset/binding_stale_version（WorkspaceBindingRef 由调用方从 project 文档填充）、
duplicate_version_number、working_copy_missing_source。17 类全量版在 audit.hpp（AuditContext 形态）。

**注意**：写路径全量重写派生表（DELETE+INSERT OR IGNORE），upsert 用
`ON CONFLICT(id) DO UPDATE`（保持 rowid 插入序）。没有批量/DirtySet 通道——这正是 31b
要补的 `apply_changes` 面；新增写 API 请沿用上述 5 形状先例 + 私有 `*_in_transaction` 复用件模式。

---

## ③ 工程约定 checklist（从代码归纳）

### 错误处理
- [ ] 一律 `domain::DataError{code, message, detail(ordered_json)}` + `domain::Result<T>`（expected 形状，`is_ok()/value()/error()`）；**不抛异常**（`DataException` 存在但仅边界用）。
- [ ] **成功哨兵必须显式 `DataError(ErrorCode::Ok, "")`**——`DataError()` 默认 code=Unknown，成功路径写默认构造就是 bug（31-decisions D3；repository.cpp 30+ 处先例）。检查错误用 `error.code != ErrorCode::Ok` 或 `.ok()`。
- [ ] ErrorCode 全集：Ok/InvalidArgument/NotFound/ConflictBaseVersion/ImmutableVersion/DuplicateOperation/UnsafeId/PathEscape/IoError/CorruptJson/CorruptDatabase/FutureSchema/RecoveryRequired/Cancelled/Unknown；`to_string(ErrorCode)` 提供 snake_case 文本。
- [ ] 错误消息对 Python **字节一致**是硬契约（多处头注释明示 "byte-identical"）；中文消息原样保留（如 governance 的中文报错、ingest_exec 的"导入失败 DataError: "前缀）。
- [ ] sqlite 错误统一 `make_error(context, db, rc)` → `CorruptDatabase` + detail{"sqlite_code":rc}（sqlite.cpp:15）。
- [ ] best-effort IO（telemetry、purge、sweep）返回 bool/void 或收集 issues，**永不把辅助 IO 失败传染主操作**。

### JSON
- [ ] 唯一类型 `domain::Json = nlohmann::ordered_json`（键序保持，Python 声明序 round-trip）。库名 nlohmann，vendored 单头 `libs/data_suite/third_party/nlohmann/json.hpp`。
- [ ] 解析容错：`Json::parse(text, nullptr, false)` + `is_discarded()` 检查，坏 TEXT 列回退 fallback（`parse_json_column(text,"{}")`）。
- [ ] Python 兼容 dump：`dump_json_python_compatible`（indent=2、ensure_ascii=false、尾部 \n）、`dump_json_compact_header`；telemetry 行则需 `sort_keys=true` 的 ", "/": " 分隔形状（telemetry.cpp 内实现）。
- [ ] 语义比较：`json_semantically_equal/json_semantic_diff`（int≠float 是类型差；missing key ≠ null）。

### 时间 / id / 路径
- [ ] UTC 时间戳：`domain::now_iso8601()`（微秒 + "+00:00"，support.cpp）；refs 侧另有 `pwb::catalog::utc_now_iso()`（types.py _now_iso 同形）。测试注入时钟：可空 `std::function<std::string()> now` 参数（migrate_resources）或 `now_iso` 尾参（relink_external_source）。
- [ ] id 生成：`domain::make_id("asset_"/"ver_"/"run_")` → `{prefix}{12 hex}`；`seed_id_generator_for_tests` 可定种。refs 的 `new_ref_id` = prefix+16 hex。
- [ ] 路径帮助：`pwb::project::project_dir_for / catalog_sqlite_for`（paths.hpp）；存库路径统一 project-relative POSIX（`generic_string()`）；报告路径同形（gc.hpp 明示）。Windows u8 转换走 `pwb::project::path_from_u8`。

### 字符串规范化
- [ ] **有界 ASCII fold 是唯一先例**：'A'-'Z'→小写、非 ASCII 原样（repository.cpp `search_fold`、entity_view.cpp `normalize_search_name/normalize_tag_name`；tag 版多一个空白折叠）。不携带 NFKC（15-decisions D6 / 31-decisions D4 声明的偏离）。31b 新代码需要 fold 时**复用 entity_view 的导出函数**，不要在 service 层再写一份。

### 命名与文件组织
- [ ] 自由函数 snake_case；参数超 3 个或带默认行为→**struct 参数聚合**（`EntityPageQuery/PlaceManagedOptions/IngestExecuteOptions/AuditContext/DisplayContext` 先例）；服务类小、构造注入 `(document, index)` 引用（ImpactService/ExplainService/TagStore）。
- [ ] 常量 `inline constexpr` 放头文件（`kMaxRunPorts`、`kSeverityHigh`、`kGcStageOrphan`…），声明序=错误文本序的地方有注释锁定。
- [ ] 头注释 = 移植契约文档：首行「模块（conv-XX；Python 文件 parity）」+ 行为不变量 + 有界偏离声明。所有对 Python 的偏差必须在头注释 + 31-decisions 里登记。
- [ ] include 顺序：自身头 → 项目内 pwb/*（按依赖）→ 同目录私有头（"row_mapping.hpp"）→ std。TU 顶部 `using pwb::domain::DataError;` 等四个 using 是惯例。
- [ ] 匿名 namespace 放 TU 内部帮助函数；跨 TU 共享的内部件放 src/ 私有头（row_mapping.hpp、coordinator_detail.hpp、path_text_util.hpp 先例）。
- [ ] C++20（`target_compile_features ... cxx_std_20`）；MSVC /utf-8 /W4 /permissive- 与 GCC 双目标。

### cancel / 进度
- [ ] 取消 = `std::function<bool()>` 可空尾参（`CancelPoll`，checksum.hpp 定义；audit/queries/sources 同形）；每 chunk/每 payload 轮询，取消返回 PARTIAL/`cancelled=true` 报告而非错误码（#1056 协作契约）。
- [ ] 进度 = `ProgressFn = std::function<void(int,int)>`（ingest_plan.hpp 定义）。data_suite 另有 `CancelFn` 同形 typedef——新代码用 catalog 侧 `CancelPoll` 命名。

### CMake target_sources 块惯例
新增 TU **绝不改 add_library 初始清单**，只追加带标记的 `target_sources` 块。CONV-31 块原文
（libs/catalog/CMakeLists.txt:62-87）：

```cmake
# BEGIN CONV-31
# Catalog domain core (conv-31): document indexes, seam value types,
# checksum, policy layers (governance / artifact policy / port roles /
# model gates), telemetry, lineage walks, impact/staleness, explain,
# missing-source scan + relink, queries, tags collaborator, legacy
# migration/projection, structural audit, V11 policy core and the trash /
# working-copy storage surface. New TUs only — the existing lists above
# are untouched.
target_sources(pwb_catalog PRIVATE
    src/document_index.cpp
    src/refs.cpp
    src/checksum.cpp
    src/policies.cpp
    src/telemetry.cpp
    src/lineage_graph.cpp
    src/impact.cpp
    src/explain.cpp
    src/sources.cpp
    src/queries.cpp
    src/tags.cpp
    src/legacy_migration.cpp
    src/audit.cpp
    src/v11_policy.cpp
    src/trash.cpp
)
# END CONV-31
```

31b 应新增 `# BEGIN CONV-31B ... # END CONV-31B` 块（service_core 等 TU），照抄
"New TUs only" 注释格式。若建**新库**（而非并入 pwb_catalog）：参照
`add_library(pwb_x STATIC ...) + ALIAS Pwb::X + target_compile_features cxx_std_20 +
target_link_libraries PUBLIC Pwb::Domain ... + install(TARGETS ... EXPORT PwbDataTargets)`
模板（catalog/CMakeLists.txt:7-41），并在根 CMakeLists.txt 的 add_subdirectory 区
（现有 CONV 块序列之后）加自己的 `# BEGIN CONV-XX` 块。测试注册见④。

---

## ④ 测试 harness 结构

- **无外部框架**。`tests/cpp/data/pwb_test.hpp`：`PWB_TEST(name)` 静态注册宏 + `PWB_CHECK(cond)`；
  `test_main.cpp` 共享 main（无缓冲 stdout，crash 不吞 PASS 行；exit 0/1）。断言计数
  "N cases, M failures"。crash_recovery 例外（自带 main）。
- **oracle replay 形态**（catalog_domain_test.cpp，CONV-31 样板）：
  - fixture 目录经编译宏 `PWB_DATA_FIXTURE_DIR`（CMake 传入）或 `getenv` 回退到源码树 fixtures/；
  - `ensure_init()` 惰性加载 `fixtures/catalog_domain/oracle.json` 进 `g_oracle` + `mkdtemp`
    建 `{ROOT}` 临时根；
  - `rooted()` 把 oracle 文本里的 `{ROOT}` 占位替换为临时根；随机 id 段两侧掩码后比较；
  - `expect_json(section, actual, expected)` 用 `compare_json.hpp` 的 `json_compare`
    （语义比较：int/float 类型差、missing≠null、数组序保持），返回 "$"-rooted diff 路径；
  - 本地增强宏：`PWB_TEST_ASSERT(cond,msg)` / `PWB_TEST_ASSERT_EQ(a,b,msg)` / `PWB_CASE = PWB_TEST`；
  - **negative self-check 必备**：`PWB_CASE(negative_self_check)` 篡改 oracle 5 处
    （值、布尔、删键、int↔float 类型、加幽灵键），断言比较器全部检出——证明 replay 本身有效；
  - case 命名按域分组（governance/artifact_policy/port_roles/model_gates/checksum/lineage/
    impact/v11_policy/queries_and_sources/tags/migration/audit_and_explain/negative_self_check 共 13）。
- **行为型测试**（catalog_write_test.cpp 样板）：`fresh_store(tag)` 帮助函数（temp dir +
  remove_all + CatalogRepository），直接断言 `error.code == ErrorCode::Ok` 与
  `repository.current_revision()` 递增；还能直接 `Database::open` + 裸 SQL 探内部列
  （name_search 折叠断言，catalog_write_test.cpp:89）。
- **fixture 型测试**（catalog_read_test.cpp 样板）：只读打开 `fixtures/typical/typical.paleo.json`，
  断 StoreStatus Canonical / 计数 / 优雅降级（missing → NotFound）。
- **注册**：tests/cpp/data/CMakeLists.txt 的 `pwb_data_test(target source ctest_name)` 函数
  （链接 `Pwb::Data Pwb::Catalog Pwb::Project Pwb::Workspace Pwb::Domain`，TIMEOUT 300）。
  新测试加一行 `pwb_data_test(data_xxx xxx_test.cpp data.xxx)`，放自己的
  `# BEGIN CONV-XX ... # END CONV-XX` 块（CONV-15/26 先例，见 :114-134）。注意
  `data.catalog_domain` 已存在（:50）——31b replay 若扩 case 就地加，别建重名可执行文件。

---

## ⑤ 依赖可用面

- **sqlite**：amalgamation vendored 于 `libs/data_suite/third_party/sqlite/{sqlite3.c,sqlite3.h}`，
  由 pwb_catalog 直接编入（catalog/CMakeLists.txt:26），include 目录 `PWB_VENDOR_DIR` 公开
  给所有消费者。GCC/Clang 侧 `-fvisibility=hidden`（防止抢占 QGIS/GDAL 的系统 libsqlite3），
  MSVC 侧 /W0。头文件直接 `#include <sqlite3.h>`（sqlite.hpp 先例）。
- **JSON**：nlohmann 单头 `libs/data_suite/third_party/nlohmann/json.hpp`，经 Pwb::Domain
  （`pwb/domain/json.hpp`）间接可用；约定只用 `ordered_json` 别名 `domain::Json`。
- **sha256**：自研 `libs/domain/src/sha256.cpp`（FIPS 180-4 流式，无 OpenSSL 依赖——
  "no QGIS/GDAL/PROJ builds" 预算），`pwb/domain/sha256.hpp` 提供 `Sha256` 类与
  `of_bytes/of_file` 一次性帮助；catalog 包装在 checksum.hpp（取消/文本规范化语义）。
- **无 Qt / 无 Boost / 无加密库 / 无网络**。可链接基座：`Pwb::Domain`（errors/json/ids/
  stage/diagnostics/sha256）、`Pwb::Project`（paths/document/manager）、`Pwb::Catalog`、
  `Pwb::Workspace`、`Pwb::Data`（data_suite facade 层）。

---

## ⑥ data_suite 编排先例（31b service_core 设计参照）

- **WritableSession**（`libs/data_suite/include/pwb/data/session.hpp`）：服务层"整箱移动"形态——
  `Impl{manager, repository, document, coordinator}` 以 `unique_ptr` 装箱，coordinator 持兄弟
  引用在构造时绑定，session 只能 move 不能重组。**31b 的 service_core 若要挂
  DocumentIndex/TagStore 等有引用成员的组件，这是唯一可行形态**（引用成员使类不可移动，
  必须装箱）。`WritableSession::open(path)` 是 fail-fast 入口（读不了/坏店/只读项目直接拒绝开）。
- **CommitCoordinator**（commit_coordinator.hpp + run_coordinator.cpp 拆 TU）：编排 =
  `validate → journal → place payload → catalog transaction → project save → rebind`，
  journal 阶段机 `JournalPhase` 枚举驱动 crash recovery；**FaultHook 注入**（`set_fault_hook`）
  是恢复测试的故障注入先例。时间戳 `now() = domain::now_iso8601()`。
- **对 repository 的消费方式**（ingest_exec.cpp:205-259 样板）：place_managed_file 先落盘 →
  组 DataAsset/DataVersion（`domain::make_id`、`now_iso8601` 打戳）→
  `session.repository().import_raw_transaction(asset, version)` 单事务落地 →
  失败则**调用方负责删刚放置的 version 目录**（共享 blob 留给 GC）→ issue 收进 report 继续。
  即：repository 只管 catalog.sqlite 事务，payload 回滚归编排层——31b 的 service 层照此分工。
- run_coordinator.cpp 消费 `publish_result_transaction`（run 翻 terminal 前先 durable
  payload+catalog+bindings，:558）与 `finish_run_transaction`（:240/:622/:724）。
- ingest_exec 头注释明示事务边界偏离：Python batch_save 64/批，C++ 每条一事务
  （更细粒度、部分进度更安全）——31b 做 apply_changes/batch 通道时要回头对齐这个已登记的缝。

---

## ⑦ 对 R1–R8 各轨道的"可用缝"提示

（按 31-decisions D6 的 31b 拆分面对应；轨道号以任务书为准）

- **service.py open 流程 / status 门控** → `CatalogRepository::status()/open_read_write()/
  open_read_only()` 已是完整底座（StoreHealth 五态、种子 sync_state、Corrupt 绝不重建）。
  service_core 只需编排：status 分流 + 文档装载 + index 构建，**别在 service 层重复 sqlite 探测**。
- **db.py apply_changes + DirtySet 通道 / 14 个惰性读** → 现有 5 事务形状 + `*_in_transaction`
  私有复用件是扩展点；DirtySet 落地时可把 upsert_*_rows 泄为内部头（参照 row_mapping.hpp
  的 src 私有头先例）。惰性读先例：load_document_from 的分表懒 attach（run_inputs/outputs/
  ports 仅在表存在时读，repository.cpp:385）+ paged_sql 的"不物化整文档"哲学。
- **模型注册表（models/model_versions）** → export_manifest 的 `passthrough_rows` 已处理
  透传（含 JSON TEXT 列探测）；model_gates 的 `ModelGateFacts/ModelVersionGateFacts`
  就是注册表读模型的注入形状——建读模型时直接产出这两个 struct。
- **working-copy 生命周期** → repository 的 insert/remove/set_working_copy_state 三件套 +
  trash.hpp 的 `create_working_copy`（全拷贝原子放置）已齐；v11_policy 的
  `live_working_copy` 布尔参数是"注册表探针"留的缝，service 层填真探针。
- **resolve_path 完整搬迁梯** → 现有两处"第一梯"实现：repository audit 子集
  （project-join/absolute/naive-join）与 sources.hpp `missing_probe_path`（注释明示
  扫描只允许第一梯）。31b 建统一 ladder 函数后，audit.hpp `AuditContext::resolve_path`、
  queries.hpp `verify_integrity` 的 resolve 参数、refs.hpp `DisplayContext::resolve_path`
  三处注入缝现成，替换默认值即可。
- **store.py manifest load** → export_manifest 已固定 schema-1 写侧（原子 tmp+rename+.bak）；
  load 侧照写并复用 `parse_json_column`/rows:: 映射。manifest_export_test 是回归锚。
- **service_v11 bundle 放置编排** → 纯决策核 `plan_bundle_members`（统一名字池 + ~N 后缀）
  已就绪，编排层只管 IO 顺序：place_managed_file 逐成员 → 单事务版本落地（沿
  commit_version_transaction 形状新增 bundle 变体）→ 失败回滚 staged 目录（ingest_exec 样板）。
- **_save(DirtySet) 服务缝** → TagStore 的 `TagSaveHook`（tags.hpp:29）+ sources 的
  save-then-restore 是两个已验证的注入形态；31b 的 service._save 等价物建议同为
  `std::function<DataError()>`，让 document 持有者（WritableSession）提供实现，
  失败语义 = 非 Ok 触发调用方回滚。

通用红线：成功路径显式 `DataError(ErrorCode::Ok,"")`；错误文本与 Python 字节一致；
新 TU 走 `# BEGIN/END` target_sources 块；头注释声明 parity 与偏离；replay 测试必带
negative self-check；任何 mutation 后 DocumentIndex 必须 rebuild（快照指针失效）。
