# 01 — Current State（V11 开发前的深度现状）

基于 main @ `6c08fb7d` 的全量代码阅读。引用格式 `file:line`（可点击）。

## 1. 三层数据体系现状

### 1.1 遗留资源层：`ResourceItem` + `project.resources`

- 定义：`paleo_workbench/project/models.py:56`。字段：`id(res_*)/name/path/type/format/crs/status/tags/source/parsed_summary/checksum/external/artifact_role`。
- 持久化：`ProjectDocument.resources` 进 `*.paleo.json`（`project/manager.py` save 流程，保存时外置 factor grids）。
- **生产代码仅 4 处构造**：`resources/import_service.py:186`（导入）、`resources/scanner.py:50`（扫描）、`ui/data_lifecycle_controller.py:814`（catalog DERIVED 的伴随行）、`ui/data_lifecycle_controller.py:1463`（回收站伴随行）。
- ADR 0056 之后 catalog 是权威，`resources[]` 是投影镜像（`catalog/legacy_projection.py` 负责镜像方向）。

### 1.2 目录层（Catalog Core）

- **模型**（`catalog/models.py`）：`DataAsset`（身份 + current_version_id + legacy_resource_id 桥 + trashed 墓碑）、`DataVersion`（不可变，stage RAW/INTERMEDIATE/DERIVED/OUTPUT、managed、path、sha256、parent_version_ids、run_id）、`DataRun`（input/output version ids、parameters、generator、model_ref）、`Model`/`ModelVersion`（模型注册表）、`Tag`、`CatalogDocument`。
- **存储**（`catalog/db.py`）：SQLite 是 **canonical** 元数据存储（`<project>.artifacts/metadata/catalog.sqlite`，WAL，`apply_changes` 行级事务由 service 脏集驱动）；`catalog.json` 降级为 checkpoint/导出清单（`catalog/store.py`）。含 `staging_leases`（#1222，payload 落盘→元数据提交窗口的 GC 保护）与 `working_copies`（#1211，checkout→dirty→committing→committed 状态机）。
- **服务**（`catalog/service.py`，4625 行）：`DataCatalogService` 单写者；关键 API：
  - 输入：`import_raw`（managed RAW 落盘）、`link_external`、`materialize_external`、`find_missing_sources`、`relink_external_source`；
  - 版本：`register_version`（move/copy 语义 + 原子回滚）、`register_result_asset`、`register_derived_store`（zarr 等 store 目录收养）、`create_derived`（源文件→新 DERIVED 资产+版本+可选 run，单事务原子）；
  - working copy：`create_working_copy`（真实拷贝；live 副本复用不覆盖 #1211；磁盘证据 fail-closed）、`commit_working_copy`（move 语义→新不可变版本）、`discard_working_copy`、`recover_working_copies`（committing 崩溃恢复）；
  - lineage：`get_lineage`/`get_lineage_chain`（ancestors/descendants）、`lineage_summaries`；
  - 治理：trash/restore/purge（`_tombstone_version`…）、`promote_version`/`promote_asset`、`repair_ghost_runs`、`verify_integrity`、tags 全套、`migrate_legacy_resources`（打开时 ResourceItem→DataAsset+unmanaged RAW 版本投影，asset id 复用 res_* id）；
  - 规模：`search_assets_page`/`count_assets`/`catalog_aggregates`（分页 SQL 直通）、lazy 实体读（`get_asset_model` 等，warm 前可查）、`warm_document`。
- **端口**（`catalog/port.py` + `adapter.py`）：`CatalogPort` 协议 = 业务面契约（register_input/begin_run/complete_run/register_intermediate|output|derived/attach_lineage/query_lineage/resolve_legacy_resource/…），生产后端 `CoreCatalogAdapter`。
- **领域方言**（`catalog/lifecycle.py`，929 行）：`register_resource_input`、`register_prediction_run`、`register_persisted_factor_grids`、`register_horizon_interpretation_run`、`register_export_run/output`、`register_map_compile_run`、`register_qc_run`、`register_stratigraphic_correlation_run`、`register_fault_interpretation_run`、`register_modeling_run` 等各工作流的注册 helper。
- **GC/治理**：`catalog/gc.py`（孤儿 payload 清扫，尊重 staging lease）、`catalog/governance.py`、`catalog/audit.py`、`catalog/dedup.py`（RAW 按 sha+size 去重、external 按 path 去重）。

### 1.3 领域实体层（WorkArea domain，schema v2）

- `paleo_workbench/project/domain.py`：`WorkArea`（1 工程 = 1 工区，CRS 投影自 `coordinate` 权威）、`WellEntity`（稳定身份：name/uwi/aliases + match_keys 归一化索引；surface/project 坐标 + coordinate_status；spatial_scope workarea/reference）、`SeismicSurveyEntity`（bin grid 冻结）、`DomainEntity`（地质/辅助轻实体）、`EntityAssetLink`（entity_type/entity_id/asset_id/role/is_primary/unresolved/note —— **asset_id 引用 catalog DataAsset id**）。
- 角色词表：`WELL_ROLES = (well_head, well_log, trajectory, tops, time_depth, interpretation, other)`；`SURVEY_ROLES = (seismic_volume, geometry, velocity, horizon, fault, interpretation, other)`。**当前只是词表 —— 无 cardinality 约束、无 per-role active 版本语义、无排序。**
- `WellRegistry`/`SurveyRegistry`：O(1) 索引、歧义键返回 None（防静默合并）。`resolve_well` 五级链：persisted_id → uwi → canonical_name → alias → explicit_mapping（`workarea.metadata["well_identity_overrides"]` 治理覆盖）。歧义永不静默合并。
- 绑定管线（`catalog/domain_binding.py`）：`stage_resources`（worker 线程纯解析：SMI DAT/XML 井位头、SEG-Y 角点、LAS 井名、地质类型图）→ `bind_staged`（GUI 线程纯解析/链接）。井位头 DAT 走 geo-viz-engine `GeoVizEngine.prepare`。**井日志 LAS 目前只提取井名绑定 well_log 角色，one LAS → one well link，无多 LAS 语义。**
- 迁移（`project/domain_migration.py`）：schema v1→v2 打开时确定性幂等迁移；late-binding 补挂载。
- 身份适配器（`project/well_identity_adapter.py`）：遗留 5 种井 id 命名空间的统一查询面。

### 1.4 陈旧性/依赖体系（已存在的 Stage 9）

- `workflow/dependency_graph.py`：从 `CatalogPort.list_runs()` 构建 runtime DAG（`version→producing_run`、`version→dependent_runs`、run 输入输出），含环检测。
- `workflow/freshness.py`：`FreshnessService` —— "freshness = 相对当前工程选择是否最新"，**永不写 stale 标记进版本**，总是由 lineage + `CurrentProjectVersionContext` 重算。图缓存按 (document id, catalog_revision, mutation_serial) 键控。
- `workflow/recompute_plan.py`：最小重算计划（requires_compute/reuse_existing/skip_display_only/blocked 拓扑排序）。
- `workflow/current_context.py`：当前工程选择上下文（当前井/当前曲线选择→版本）。
- **缺口**：这些都是"当前选择"视角的 freshness；没有 (a) 实体视角（这口井的哪些成果过期）(b) 删除影响分析 (c) nearest-changed-ancestor 解释 (d) pin 显式豁免语义（V9 CompilationInputSet 有 pin 但只在编修域）。

## 2. 工作流写入面清点（按管理方式分类）

关键结论（全仓搜索 `project.resources` / `.resources.append` / `ResourceItem` / 直接 artifact 写盘 的结果）：

| 工作流 | 分类 | 说明 |
|---|---|---|
| 井日志导入（Data Manager） | **双写** | import_service 建 ResourceItem → data_page:1078 extend → catalog 批量注册 RAW（data_lifecycle_controller.register_imported_resources） |
| 井日志重扫 | **双写** | scanner 重建 ResourceItem + catalog 注册 |
| 曲线操作/解释 | catalog | temp LAS → create_derived，RAW 不动 |
| 井图导出 | ExportArtifact+catalog | record_export / register_export_output |
| 地震摄取/转码/属性 | catalog | seismic_lifecycle register_run / register_derived_store（zarr 收养+搬迁） |
| 预测推理 | catalog | register_result_asset / register_derived_store；**输入选择面仍是 project.resources 遍历**（prediction/adapters.py、input_contract.py，经 resolve_legacy_resource 桥接到版本） |
| 因子单因素图 | catalog（保存时） | FactorGridResult 内存 LRU → 保存时外置 npz → register_persisted_factor_grids |
| 因子融合 | catalog | temp → create_derived |
| 层位解释/断层解释/地层对比/TD 标定 | catalog | 各自 lifecycle helper，temp 文件收养模式 |
| 井震联合分析 | 混合读/catalog 导出 | 输入 resolve 走 project.resources + data/ 回退（joint_asset_resolver, wayfinder D） |
| 制图约束 | catalog | constraint_versions（版本列表/回滚走 catalog） |
| 成图编译/MapProduct | catalog | register_map_compile_run / register_result_asset OUTPUT；评审/冻结/发布/退位阶梯 + promote_version |
| QC | catalog | register_qc_run |
| 导出 choke point | ExportArtifact+catalog | project/artifacts.py record_export |
| 3D 建模 | catalog(run) | register_modeling_run；真实数据才有版本 |
| onboarding 向导 | 双写 | doc.resources.extend → 后续 catalog 注册 |
| pipeline bootstrap（CLI） | 双写 | scan → resources=[…] → register_resource_input 循环 |
| recipe 文档/DAG run store/composition panel 保存 | **非管理**（设计如此/待决策） | composition_panel._save_json 无 record_export（V11 需收编） |

**总结**：双写集中在**导入/浏览面**（data_page + data_lifecycle_controller + onboarding + bootstrap）；生产链路已 catalog 化；`project.resources` 的存留意义是 (a) 遗留表格显示 (b) 输入选择面 (c) 遗留桥。

## 3. Data Manager 现状（`ui/pages/data_page.py` + `ui/data_lifecycle_controller.py`）

- 小工程：表格模型 = `[*project.resources, *project.export_artifacts, *catalog_only_rows]`（catalog 有而 ResourceItem 无的资产行，data_lifecycle_controller.catalog_only_rows）。
- 大工程：超过阈值切 SQL 分页模式（`_try_paged_catalog_mode`，cached_catalog_aggregates / catalog_aggregates）。
- 导入异步流：worker 建 ResourceItem → GUI extend → _RegisterWorker 分块注册 catalog → 域绑定（stage/bind）→ 地震自动转码。
- 回收站：catalog trash + legacy 投影伴随行重建。
- 工作副本/物化/提升/新版本：catalog-only 操作。
- **已知缺口**（open issue #1269，owner PR #1277）：分页模式下仍有 GUI 线程 list_assets() 全量物化。V11 以实体树 + 轻量身份查询覆盖同一诉求。
- 导航树（workstation 侧）已有井/调查分组显示，但 Data Manager 主表仍是"文件列表"语义，无 per-well role 分组。

## 4. 已有的关键不变式（V11 必须保持）

1. committed `DataVersion` 不可变（`catalog/models.py:9-13` 声明，service 全程 move/copy 语义）。
2. RAW managed 版本不可原地修改。
3. catalog 单写者（service 锁 + SQLite BEGIN IMMEDIATE CAS #411/#1027）。
4. 井身份：文件名永远不是身份；歧义不静默合并（resolve_well）。
5. `EntityAssetLink.asset_id` 引用 DataAsset id（非 ResourceItem id）。
6. trash 是软删除（payload 进 trash/，lineage 保留，可恢复）。
7. freshness/staleness 永不写入版本 —— 总是从 lineage + 上下文重算。
8. 打开工程永远成功（迁移每步独立守卫，解析失败变 issue 不抛异常）。
9. SQLite canonical、catalog.json checkpoint、损坏可重建（store_health 分类 corrupt/error/legacy）。
10. 10 万级：分页 SQL、lazy 实体读、warm-up 守卫、图缓存。

## 5. V11 面向的具体缺口（现状 → 目标差距）

| # | 缺口 | 现状证据 |
|---|---|---|
| G1 | 一井多文件是"能力"不是"产品"：多 LAS/多 trajectory/多 TD 各自为政，无 per-role cardinality、无 primary/alternatives、无有序成员 | WELL_ROLES 只是词表；bind 只 upsert link |
| G2 | 无实体数据视图 API：想知道"这口井当前各角色用什么版本"需要自己拼 links+assets+versions | 无 WellDataView/SurveyDataView 等价物 |
| G3 | 无复合资产：多文件组成的逻辑资产（shapefile family、seismic geometry sidecar、bundle）无正式表达，最多 metadata 里塞 paths | DataVersion.path 单值 |
| G4 | lineage 无类型：input_version_ids 是无角色扁平列表，答不了"sonic 用的是哪个版本" | DataRun.input_version_ids: list[str] |
| G5 | 生命周期四阶段是枚举不是策略：无 retention/cleanup-eligibility/pinned/recomputable 语义 | DataStage 仅 RAW/Derived/INTERMEDIATE/OUTPUT；无策略字段 |
| G6 | working copy 有注册表但只有单文件语义；无"编辑会话"层概念（哪些业务对象在编辑中） | working_copies 表按 source_version_id 单文件 |
| G7 | staleness 只有"当前选择"视角；无实体视角/删除影响/上游影响查询/nearest-changed-ancestor/pin 豁免 | freshness.py 的 CurrentProjectVersionContext 单上下文 |
| G8 | 导入无 plan：目录批量导入直接执行，无 classification→matching→role→duplicate→plan→confirm 管线（onboarding.analyze_data_folder 是雏形但一次性） | onboarding.py:244 |
| G9 | Data Manager 是文件列表，不是工区/井/调查组织 | data_page.py 表格模型 |
| G10 | "为什么存在"问答需要 UI 自己拼 | 无 explain/why 服务 |
| G11 | 部分输出未登记（composition panel 保存、SVG/PNG 导出绕过 record_export） | composition_panel.py:851 |
| G12 | 输入选择面仍遍历 project.resources（预测输入契约、联合分析、可视化选择） | prediction/input_contract.py:136 等 |

## 6. 规模与性能现状

- 分页浏览 SQL（name/type/updated 复合索引 + trashed=0 partial live index）；打开不再全量物化（lazy warm）。
- `WellRegistry` O(1)；绑定复用单注册表（#1213）。
- freshness 图缓存 4 项 LRU。
- 已知约束：Data Manager 表格/树在任何模式下不得回退到全量 list_assets() 物化（#1269 精神）。
