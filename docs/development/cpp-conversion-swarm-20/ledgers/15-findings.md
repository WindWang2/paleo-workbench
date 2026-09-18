# 15 — Findings：catalog GC / dedup / entity 分页（逐文件原文阅读笔记）

来源约束：本文所有结论均来自本 worktree 中对 §5 清单文件的**全文阅读**（非 grep 摘要）。
路径适配：任务书中的 `/home/kevin/projects/paleo_project/main` 在本机不存在；实际仓库为
`/home/kevin/project/paleo-workbench`，worktree 为
`/home/kevin/project/worktrees/cpp-conv-15-catalog-gc`（BASE = `35987e13`）。
下述 file:line 均相对该 worktree。

---

## paleo_workbench/catalog/gc.py（425 行，全文）

公开符号：`STAGE_ORPHAN/WORKING_ORPHAN/TEMP_ORPHAN/TRASH_ORPHAN/BLOB_ORPHAN/EMPTY_DIR`、
`GcItem`、`GcReport`、`plan_gc`、`sweep_gc`、`cleanup_working_copies`。

- 孤儿类词表（报告用，删除策略在 sweep_gc）：`stage_orphan`（stage 目录里没有任何
  managed 版本引用的 payload）、`working_orphan`（working/ 下首段不是已知 version id 的文件）、
  `temp_orphan`（名字匹配临时模式的文件）、`trash_orphan`（trash/{vid}/ 下 vid 不存在的文件）、
  `blob_orphan`（dedup.plan_blob_gc 判定的不可达 blob）、`empty_dir`（stage+working+trash 树下空目录）。
- 临时名判定 `_is_temp_name`：名字以 `.tmp` 结尾，或以 `.place-` / `.blob-` / `.catalog.json.` 开头。
  输入=文件名字符串；输出=bool。空串 → False（不匹配任何前缀/后缀）。
- `GcItem(kind, path, size=0)`；`GcReport` 提供 `by_kind`（保序列表）、`count(kind=None)`、
  `bytes_for(kind)`、`total_bytes()`、`kinds()`（排序去重）。
- `plan_gc(service, *, explicit=True)`：**永不删除**。explicit=True 走 6 步全量：
  1) stage 孤儿——`referenced = {v.path for v in versions if v.managed}`（版本路径是**项目相对**且含
     `<name>.artifacts/` 前缀），rel = 文件相对 project_dir 的 POSIX 路径；rel ∉ referenced 且不在
     在租 → STAGE_ORPHAN；
  2) working 孤儿——相对 working_root 的首段 ∉ {v.id} → WORKING_ORPHAN；
  3) trash 孤儿——同 2 但对 trash_root；
  4) temp 孤儿——全 artifacts 树扫描临时名，但**跳过 working/ 与 trash/ 子树**（`_temp_scan_roots`），
     且 rel ∈ referenced 的**永不分类**（导入的 payload 可能合法叫 `data.tmp`，#889 回归）；
  5) blob 孤儿——`dedup.plan_blob_gc` 的每个 digest → `blobs/<d[:2]>/<d>`，再过租过滤；
  6) 空目录——stage 四目录 + working + trash 下 `rglob` 目录按**深度降序**（`-len(parts)`）找空目录；
     仅过租过滤，不过 referenced。
  explicit=False（开屏自动）= `_plan_auto_gc`：**只有 temp_orphan + empty_dir**（省三次全树遍历）。
- 租（lease）：`_leased_prefixes` 读 `service._index.active_staging_targets()`（失败→空集）；
  `_is_leased(rel, leased)` = rel 等于某前缀或以 `前缀/` 开头。explicit plan 先
  `prune_stale_staging_leases()`（死租清掉，payload 回归正常分类），失败静默忽略。
- `sweep_gc(service, *, dry_run=True, explicit=False, report=None)`：
  可删集合 `_AUTO_SWEEPABLE = {TEMP_ORPHAN, EMPTY_DIR}`；
  `_EXPLICIT_SWEEPABLE = {STAGE, TEMP, TRASH, BLOB, EMPTY_DIR}`（**永远不含 WORKING**）。
  dry_run=True → 返回过滤后的候选 GcReport。真删：64 一块，**每块在锁内重算 referenced+leased**，
  rel ∈ referenced 或在租 → 跳过（plan→sweep TOCTOU 防护）；目录 rmdir、文件 unlink；
  PermissionError → chmod +S_IWUSR 重试一次；其它 OSError → 跳过。删除后写 telemetry
  `gc.sweep`（candidates/removed/removed_bytes/kinds）。
- `cleanup_working_copies(service)`：显式用户动作。working/ 下首段 ∉ {v.id} 的文件 unlink
  （report size 记 **0**），随后按深度降序 rmdir 空目录。live 版本的工作副本绝不触碰。
- 与 C++ 核的关系：CatalogDocument 已有 versions(path/managed/id) + staging_leases(heartbeat_at)
  读模型；文件系统遍历用 std::filesystem。缺 telemetry（不属存储契约，见 decisions）。
- 测试缺口（Python 已测、C++ 需补）：六个孤儿类各一例、referenced temp 名存活、auto sweep 不碰
  stage/working/trash/blob、开屏 sweep 真删 temp、plan 永不删、外部文件不动、租前缀挡分类、
  死租不挡、explicit 真删 stage/trash/blob。

## paleo_workbench/catalog/dedup.py（253 行，全文）

公开符号：`BLOBS_DIRNAME`、`blob_dir_for`、`blob_path`、`has_blob`、`blob_size`、`place_blob`、
`referenced_digests`、`scan_blobs`、`plan_blob_gc`、`sweep_unreferenced_blobs`、`blob_metrics`、`blob_report`。

- 布局：`<project>.artifacts/blobs/<digest[:2]>/<digest>`；blob 只读、内容寻址、幂等放置
  （temp `.blob-*` + fsync + rename + 目录 fsync；已存在→直接返回不覆盖）。
- `blob_path(project, digest)`：分片=摘要前 2 字符；digest 空串时前 2 字符为空 → 根目录拼接
  （实际调用方保证非空：`has_blob` 先 `bool(digest)` 短路）。
- `has_blob` = 非空 digest 且 blob 文件存在；`blob_size` = 存在返回 st_size 否则 0。
- `place_blob(project, source, digest=None)` → `(newly_placed, digest)`：digest 缺省时流式 SHA-256
  （CHUNK_SIZE=1 MiB）；已有 → (False, digest) O(1) 零拷贝。
- `referenced_digests(document)` = {v.sha256 for managed 且 sha256 非空} —— GC keep-set。
- `scan_blobs(project)` = {文件名: st_size}，只遍历 blobs/ 根下的**目录**分片（根上的
  `.blob-*` crash 残留被跳过——place_managed_file 的 blob temp 特意放在根上，就是靠这条规则豁免）。
- `plan_blob_gc` = scan_blobs − keep（返回 digest 列表，dry-run 安全）；
  `sweep_unreferenced_blobs` = 逐个 unlink，FileNotFoundError→跳过（已删），PermissionError→
  chmod 重试（Windows 语义；POSIX 直接成功），其它 OSError→跳过；成功后 fsync 父目录。
- `blob_metrics`：`blobs_on_disk`/`bytes_on_disk`（在盘事实）、`referenced_digests`=|keep ∩ blobs|、
  `unreferenced_blobs`=|blobs − keep|、`bytes_deduped` = Σ size×(refs−1)（refs = **managed 且
  sha256 ∈ blobs** 的版本数；注意只对在盘 blob 计数）。
- `blob_report` = {metrics, unreferenced(排序), referenced(排序)} JSON 摘要。
- 空/退化：document 无版本 → keep 空 → 全部 blob 不可达；blobs/ 不存在 → 空 map。
- 并列/NaN 类：无（纯集合运算 + 字节计数）。
- 与 C++ 核的关系：domain::Sha256 已有流式实现；CatalogDocument.versions 提供 keep-set；
  需要新增的只有 blob 目录布局 + 原子放置（std::filesystem rename + POSIX fsync）。
- 测试缺口：幂等放置、只读位、存在性检查、scan/metrics 计数、不可达清扫、可达 blob 永不清、
  bytes_deduped 语义、版本身份≠blob 身份。

## paleo_workbench/catalog/entity_views.py（379 行，全文）

公开符号：`AssetSummary`、`RoleSlot`、`WorkingCopyLite`、`WellDataView`、`SurveyDataView`、
`WellIndexEntry`、`EntityViewService`（well_index/survey_index/well_view/survey_view）。

- 这是 **project 实体视图装配层**：输入 = ProjectDocument（wells/seismic_surveys/
  entity_asset_links）+ DataCatalogService（resolve_asset_models/_ensure_maps/list_working_copies/
  impact）。它自己**无存储**（V11 §6.2 D5：读穿两个权威，不建第二副本）。
- 排序契约（可移植到 C++ 的部分）：slot.members.sort(key=(not is_primary, ordinal, name))；
  slot.unresolved.sort(key=name)；未知 role 不丢弃，落到合成 slot（display = role_definition.display
  or role）；link 的 asset 不在 catalog → 名字 `<未注册资产 {id}>`、type="unknown"、unresolved=True。
- 未注册资产/缺失源探测 `_probe_missing_members`：仅对视图自身成员做第一梯 existence 探测
  （managed → project_dir/path；external → 绝对或 project_dir join），trashed/current 缺失 → 跳过。
- scale 契约：well_index O(W)（wells+links 内存聚合，绝不 list_assets()）；stale 计数走 impact
  服务（asset→wells 反查）。
- 与本切片的关系：**实体列表分页的可执行契约在 service.search_assets_page / count_assets**
  （paged fallback 与 SQL 页面被 test_catalog_paged_query 钉死等价），而 EntityViewService 的
  wells/surveys 输入模型（pydantic ProjectDocument 实体）在 C++ catalog 库中不存在（C++ 侧
  entity 绑定模型在 data_suite 的 EntityAssetLinkV1 快照投影里，属 A 线消费面）。
  因此本切片把「entity view 分页」落在 **catalog 文档上的稳定分页查询**（见 decisions D5），
  RoleSlot/视图装配的 UI 层不在 C++ catalog 库的职责内。
- 测试缺口：Python 侧有 view enrichment/快照测试；C++ 本切片以分页 oracle 对账覆盖列表稳定性。

## paleo_workbench/catalog/storage.py（644 行，全文）

公开符号（本切片相关）：`BLOBS_DIRNAME`、`STAGE_DIRS`（RAW→"raw"、DERIVED→"derived"、
INTERMEDIATE→"intermediate"、OUTPUT→"outputs"——**OUTPUT 目录名是 outputs 不是 output**）、
`EXTRA_DIRS=["working","metadata","trash"]`、`catalog_dir_for`（=artifacts/metadata）、
`is_safe_entity_id`（非空、非点开头、仅 [A-Za-z0-9._-]、无斜杠）、`ensure_catalog_layout`、
`working_dir_for`、`trash_dir_for`、`blob_dir_for`、`blob_path`、`is_cas_path`、`has_blob`/`blob_size`/
`place_blob`（与 dedup.py 同布局的镜像实现）、`trash_payload`/`restore_payload`/`purge_trashed_payload`
（blob 永不移动；purge 尊重 shared refcount）、`safe_unlink`、`fsync_dir`、`place_managed_file`、
`place_managed_tree`、`create_working_copy`。

- `place_managed_file(source, project, stage, asset_id, version_id, *, keep_source=True,
  known_sha256=None, register_blob=False, _sha256_verified=False) -> (rel_path, size, sha256)`：
  1) id 安全门禁（asset 与 version 都是路径段，#1175）；
  2) **dedup 快路**：known_sha256 命中已有 blob 且 source 尺寸==blob 尺寸且（`_sha256_verified`
     或 重哈希 source == known_sha256）→ 直接引用 blob（rel = blob 相对路径，size = blob 尺寸）；
     keep_source=False 时顺带 safe_unlink(source)（工作副本 move 语义不留孤儿）；
     source 不可读（OSError）→ 落回普通拷贝路径；
  3) 普通路径：`{stage_dir}/{asset}/{version}/{source.name}`，已存在 → FileExistsError；
     temp `.place-*` + 单遍流式 hash+size+写盘 + fsync + rename + 目录 fsync + 只读位；
     register_blob 时同一读同时写 blobs 根上的 `.blob-*` temp（**注意放在 blobs 根**，scan_blobs
     只扫描分片目录，crash 残留不进 blob 清单），完成后 `_commit_blob_temp`（目标已存在→丢弃
     temp；否则 rename + fsync + 只读）；
  4) 诚实校验和：known_sha256 ≠ 实际 → 删目标（和 blob temp）+ CatalogError
     `"Checksum mismatch for {source}: caller reported {known}, actual {actual}"`；
  5) keep_source=False → safe_unlink(source)。
- 失败分支清单：unsafe asset/version id（CatalogError）；目标已存在（FileExistsError）；
  校验和不符（CatalogError）；size/digest 双伪造（快路重哈希拒绝）。
- 与 C++ 核的关系：这是「写入重复 payload 的两个版本」验收流的落盘核心，C++ 需要一个
  单文件 parity（place_managed_tree 本切片不需要，bundle 属 V11 未迁移清单）。

## paleo_workbench/catalog/service.py（4711 行，全文分窗读完）

与本切片相关的公开符号：`plan_gc`/`sweep_gc`/`cleanup_working_copies`（薄委托到 gc.py）、
`import_raw`（**每个 managed RAW 导入必 register_blob=True**——同读双写 stage 副本+blob；
known_sha256 快路；`_sha256_verified` 免二次证明）、`link_external`（不拷贝不哈希，
metadata.external_stat 记 size+mtime_ns）、`register_version`/`_build_version`（staging lease
包住 place→commit 窗口：`_staging_target(stage, asset)` = `<artifacts 名>/<stage 目录名>/<asset>`，
blob 路径再加 `<artifacts 名>/blobs`；版本号 commit 时分配）、`trash_version`/`trash_asset`
（tombstone 先持久化、payload 后移动、path 更新再持久化；**blob-backed path 不变**）、
`restore_version`、`purge_trashed`（先保存后 unlink；surviving_digests 决定 shared）、
`search_assets_page`/`count_assets`/`catalog_aggregates`/`_query_index_if_current`/
`_paged_fallback_rows`/`_asset_page_row`/`_paged_rows_from_document`、`sweep_temp_on_open`
（= sweep_gc(explicit=False) 开屏自动，异常静默）。

- 分页文档回退路径语义（C++ 对账的权威口径）：
  - 过滤：trashed_only → 只 trashed；否则 include_trashed=False → 排 trashed；
    text → `needle ∈ normalize_asset_search_name(name)`（NFKC+casefold；C++ 有界 ASCII 折叠）；
    stage → **current 版本**的 stage 等于给定值（SQL 是
    `current_version_id IN (SELECT id FROM versions WHERE stage=?)`，回退是
    `version_by_id[asset.current_version_id].stage`——两者同语义）；
    type；tags（normalize 后按 name，and=超集 / or=交集非空）；asset_id 精确；asset_ids 集合。
  - 排序（`order_by` 白名单，恒以 id 收尾）：name→(name,id)；name_desc→(name desc,id asc)
    （两趟稳定排序实现）；type→(type,name,id)；modified→(updated_at,name,id)；
    stage/size/version→(NULL 标志, 值, name, id)，**NULL 在前（SQLite ASC NULLs first）**；
    未知 order → name。
  - keyset：仅 order∈{None,"name"}，`(name,id)` 严格大于（`name > c or (name == c and id > c2)`）。
  - 分页：`rows[max(0,offset) : max(0,offset)+max(0,limit)]`；limit 默认 500。
  - 行形状（20 键）：id,name,name_search,type,description,current_version_id,legacy_resource_id,
    metadata(JSON TEXT),created_at,updated_at,trashed(1/0),trashed_at + current_stage,
    current_version_number,current_size_bytes,current_sha256,current_managed(1/0),current_format,
    current_path,current_created_at。SQL 行与文档回退行同键（Python 测试钉死相等）。
- `_managed_raw_dedup_key` = (source_uri, sha256) 仅 managed+RAW+非 trash+两者非空；
  `_external_dedup_key` = path 仅 unmanaged+非 trash+非空。
- 与 C++ 核的关系：C++ CatalogDocument（assets/versions/tags/asset_tags 齐备）→ 分页可在
  库内实现为纯函数；service 的 index/revision/fallback 分歧在 C++ 单存储模型下不存在，
  只实现「同一文档上的确定页」。

## paleo_workbench/catalog/queries.py（220 行，全文）

公开符号：`IntegrityReport`、`verify_integrity`、`search_assets`。
- verify_integrity：逐版本 resolve→stat→哈希比对；trashed 跳过；无 sha256 → unknown；
  cancel 协作中断（statuses 部分但不错）。本切片不移植（完整性校验属另一 M4 项）。
- search_assets（非分页全量）：index 失效/批内 → 回退文档扫描；text 用同一 NFKC+casefold
  归一；metadata 相等比较经 metadata_search_value（bool→"1"/"0"）；stage 过滤是
  **版本集合**（any version of asset in stage，与分页的 current 版本过滤**不同**——注意区分）。
- 对本切片的价值：确认归一化与 tag 词表入口 `normalize_tag_name`（NFKC+casefold+空白折叠）。

## paleo_workbench/catalog/lifecycle.py（1141 行，全文）

- 业务→CatalogPort 胶水（register_resource_input / factor_map / prediction / export /
  map_compile / qc / finalize / manual_edit 等）。与本切片直接相关的只有
  `register_resource_input`：checksum 缺失时惰性计算；**只有绝对路径算出的新哈希**才标记
  `_checksum_fresh`（= dedup 快路的内容证明），相对路径哈希不可信必须重证明。
  其余均为 run 线 provenance 组装，不改写 GC/dedup/分页语义。C++ 侧无 adapter 层，
  该约束以 place_managed_file 的「digest 必须重证明或调用方显式声明已验证」承载。

## paleo_workbench/catalog/db.py（3142 行，相关段全文）

- `STORE_SCHEMA_VERSION = INDEX_SCHEMA_VERSION = 5`；`STAGING_LEASE_TTL_SECONDS = 3600.0`。
- `normalize_asset_search_name` = NFKC + casefold（#897）；`metadata_search_value`：bool→"1"/"0"，
  其余 str()；`like_escape_literal` 转义 `%_\`。
- schema：assets(12 列含 name_search)、versions(16 列含 parent_ids JSON)、tags、asset_tags、
  version_tags、runs、run_inputs/outputs、lineage、models/model_versions、sync_state、
  **staging_leases**（(lease_id,target) PK，kind 'register'，acquired_at/heartbeat_at ISO 秒精度）、
  working_copies、run_ports、version_members。v6 索引（name_id 复合、live 部分索引等）纯布局不 bump。
- staging lease 三 API：acquire（BEGIN IMMEDIATE + INSERT OR REPLACE，失败→None 不挡注册）、
  release、heartbeat；`active_staging_targets(ttl=None)` = heartbeat_at **字符串比较** > now−ttl
  的 DISTINCT target（ISO 秒字典序=时间序）；`prune_stale_staging_leases` 删除 ≤ cutoff。
- 分页 SQL：`_paged_predicates`（trashed 过滤、name_search LIKE ESCAPE、stage 经子查询、
  type、tag and/or EXISTS/IN、asset_id、asset_ids 500 一块）；
  `_PAGE_ORDER_COLUMNS`：name/name_desc/type/stage/size/modified/version（version 列序需
  LEFT JOIN versions）；ORDER BY {order}, a.id LIMIT/OFFSET；after 仅 name 序
  `(a.name > ? OR (a.name = ? AND a.id > ?))`；第 2 步按 PK 批取 current 版本列（100/块）。
- `_asset_row` 的 metadata 列 = `json.dumps(asset.metadata, ensure_ascii=False)`（Python 默认分隔符
  `, `/`: `，与 service 回退路径一致）——C++ 无法字节级复刻 nlohmann dump 的差异，
  oracle 对账按解析后 JSON 语义比较（decisions D7）。

## paleo_workbench/catalog/models.py（294 行，全文）+ checksum.py（59 行，全文）

- DataStage 词表 raw/derived/intermediate/output；DataVersion.path 项目相对 POSIX（managed）/
  绝对（external）；managed 版本必有 sha256 源于 place_managed_file。
- CatalogDocument：assets/versions/runs/tags/models/model_versions + asset_tags/version_tags 映射。
- `aggregate_member_sha256`：按 (ordinal,name) 序 `rel_path:sha256` 行 join "\n" 再哈希（C++
  models.cpp 已有 parity）。
- checksum：CHUNK_SIZE=1 MiB 流式 sha256；sha256_file_or_none；sha256_text（LF 归一）。
  C++ domain::Sha256::of_file(chunk=1<<20) 已对齐。

## docs/development/cpp-data/（baseline/contracts/schema-map/test-plan/handoff/ledger/
## verification/v3-contracts/v3-handoff/v3-ledger/v3-verification，全部）

- SQLite 是 canonical（v5 store）；catalog.json 只是 checkpoint；C++ 读侧必须
  `index_schema_version ≥ 5` 地板判定（`CatalogRepository::status` 已实现）。
- v3-verification §7「仍未迁移」清单**点名本切片**：GC/dedup 全套（plan_gc/sweep_gc、blob
  去重写路径、trash 恢复流）、全部 entity view/分页/name_search（现为恒等投影 →
  repository.cpp `search_fold` 的有界 ASCII 折叠已是既定边界，非本片新造）。
- oracle 约定：fixture 由真实 Python 生成入库（`tools/oracle/`，主解释器只读）；
  CTest 前缀 `data.`；0 测试/全 skip 不算通过；无 Qt/QGIS/Python 链接（data.build_hygiene 守护）。
- 未对账表清单如实申报纪律（不扩大声称）：本切片新增对账覆盖 gc/dedup/分页行为层，
  `models/model_versions/sync_state` 仍不对账（无读模型）。

## docs/development/catalog-scale-v5/（00/01/02/04/05，全部）

- 分页 API 是 service 门面（D-01），keyset 优先 offset 兜底（D-02），ORDER BY 恒以 id 收尾；
  FTS5 决策=不引入（LIKE + name_search 复合索引够用）。
- 04-verification 已实测：page0 4.31ms@100k、深偏移 7.45ms；NULL 排序回退对齐
  SQLite NULLs-first 是 Review1-P2 修复项——C++ 实现必须保留该语义（有测试）。
- 实体集合 >5000 诚实回退物化路径（分块谓词上限）——C++ 纯文档实现无此 SQL 限制，
  但保留「集合参数即可大」的语义即可。
- Review 3 的教训：分页行必须自携带 current_* 事实字段，消费方不得再回查——C++ 行形状
  20 键全量返回即为此。

## C++ 现状（libs/catalog 全部 + tests/cpp/data 代表性文件，全文已读）

- `models.hpp/.cpp`：CatalogDocument（assets/versions/runs/tags/asset_tags/version_tags/
  working_copies/lineage/staging_leases）+ find_asset/find_version + aggregate_member_sha256。
  **staging_leases 已在读模型里**——GC 的租守卫可直接消费。
- `sqlite.hpp/.cpp`：RAII Database（WAL、busy 5000、immutable 只读零足迹）、Statement、
  Transaction、ensure_schema（v5 全表 DDL，含 staging_leases）。
- `repository.hpp/.cpp`：status 地板判定、open_read_only/read_write、v5 行加载（rowid 序）、
  export_manifest（ADR 0056 checkpoint + .bak 轮换 + models 透传）、写事务组
  （commit_version_transaction / publish_result_transaction / finish_run_transaction）、
  `search_fold`（ASCII 有界折叠，注释声明非 ASCII 边界——本切片分页 text 过滤沿用同一口径）、
  audit_catalog。既有函数签名**零改动**，本切片只新增 TU + 追加方法（无需追加方法：
  GC/dedup/分页均为自由函数，document 已可加载）。
- 测试基建：`pwb_test.hpp`（注册宏 + PWB_CHECK + 退出码）+ 每测试一可执行文件 + 
  `pwb_data_test()` CMake 函数 + TIMEOUT 300；fixture 目录经 PWB_DATA_FIXTURE_DIR 注入；
  oracle_compare/readback 已建立「Python 生成 → C++ 对账」的范式。
- 缺口：无 gc/dedup/paged 任何实现；name_search 写侧为 ASCII 折叠（有测试）；
  无 blob 写路径。本切片全部补齐行为层，oracle 由真实 Python 服务冻结。
