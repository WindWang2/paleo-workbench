# Findings — 数据治理闭环（ws0 link_well / set_role / tags / impact / trash）

Base: `c5b95f5e6`（origin/main，PR #1492 已合并）。所有路径相对仓库根。

## 1. 现状实体—关系—写入口—读取入口表

| 实体 | 持久化权威 | 现有写入口 | 现有读取入口 | 治理闭环缺口 |
|---|---|---|---|---|
| DataAsset / DataVersion / Run | `catalog.sqlite`（`<proj>.artifacts/metadata/`，`libs/catalog/src/sqlite.cpp:168-325`） | `CatalogRepository` 各 `*_transaction`；`CatalogClosureAdapter`（`apps/closure_catalog_service.cpp`） | `DataFacade::open_snapshot`、`queries_sql.hpp` 懒 SQL、`paged_sql.hpp` | 无（读侧完备） |
| entity_asset_links | `.paleo.json` `entity_asset_links` 数组（`libs/project/src/schema.cpp:370-387`） | **仅导入流程** `upsert_entity_asset_link`（`libs/data_suite/src/entity_identity.cpp:324-394`）；删除只有整资产/整井级（`remove_links_for_asset:502` 等） | 导航树只读（`closure_data_workspace.cpp:150-184`）；`links_for_asset`（entity_identity.cpp:439+）；影响分析注入（impact_entity_links） | **无单链接删除、无角色编辑、无 UI 写入口** |
| role 词汇 | 编译期注册表（`libs/data_suite/src/role_registry.cpp:10-56`）；schema 中 role 是自由 String（未知角色必须 round-trip，`role_registry.hpp:4-11`） | 无运行时写入方 | 导航树分组/中文标签；`roles_for_entity_type` / `role_display` | **无编辑后端**（schema 已允许自定义角色） |
| tags | `catalog.sqlite` tags/asset_tags/version_tags 三表 + `TagStore`（`libs/catalog/include/pwb/catalog/tags.hpp:31-87`，#1182 懒日志回滚）；正规化 = ASCII fold + 空白折叠（`entity_view.cpp:152-156`） | `CatalogClosureAdapter::add_tag/remove_tag/bulk_*`（closure_catalog_service.cpp:1484-1574）——**旧栈已用**（data_lifecycle.cpp:1318-1533） | `tags_for_version`/`tag_ids_for_asset` SQL；lineage 节点携带 | **新栈（ws0 ribbon/表格/过滤）完全未接**；`AssetView.tags` 从不填充 |
| trash 软删 | `assets.trashed/trashed_at` + `versions.trashed` + `metadata["trash"]` 墓碑 + `<artifacts>/trash/<vid>/` 载荷（trash_service.hpp） | `trash_asset/restore_asset/purge_trashed`（两阶段 save，事务内 CAS）——旧栈已用 | `get_trashed_assets`；`asset_rows_from_snapshot` **跳过 trashed**（closure_preview_adapters.cpp:362-374） | **新栈无回收站视图/恢复入口** |
| lineage / impact | `versions.parent_ids` + `lineage` 表 | 随版本写入 | `build_lineage_chain`（BFS+去环+截断，lineage_graph.cpp:63-128）；`ImpactService::delete_impact`（impact.cpp:288-397，entity_links 注入缝） | `delete_impact_summary`（closure_data_workspace.cpp:310-347）已存在但只被旧栈确认对话框消费；**新栈无影响分析 UI** |

## 2. 关键架构事实（决策依据）

1. **双权威**：资产/版本/标签/回收 → SQLite catalog；井/实体/关联 → 项目 JSON。互不外键。治理闭环不新建任何平行存储。
2. **写路径范式**（ws0 既有）：`WritableSession::open(project_file)` → mutate → `manager().save(document)` → `notify_project_store_changed()`（`execute_folder_ingest`，closure_data_workspace.cpp:351-382）。catalog 侧短生命周期写走 `CatalogClosureAdapter::open`（深核：两阶段 save、#411/#1220 CAS、失败回滚、事件不发布半成品）。
3. **旧栈 vs 新栈**：`ui_controllers::DataLifecycleCore`（data_lifecycle.cpp）已有 trash/tags 流程但面向 legacy ResourceItem 行；新栈（ws0 ribbon → AssetSelectionBus → closure adapters）五个命令 `register_disabled`（ribbon_command_install.cpp:301-452）。ribbon 按钮在 `ribbon_spec.cpp:83-101` 已声明。
4. **选择身份**：bus 行携带 `view.id` = catalog asset_id；版本经 store snapshot `current_version_id` 解析（`resolve_version_id` 范式，data_lineage_panel.cpp:39-53）。
5. **刷新链**：写后 `notify_project_store_changed()` → `bus->set_assets` → 表/树/toolbar 全刷；但 `set_assets` 对仍存在的 current **不重发** `current_asset_changed`（asset_selection_bus.cpp:27-36）→ detail/lineage 面板不会自动刷新，需要新增 `republish_current()`。
6. **过滤框架**：`FilterQuery`（14 字段，含 tags/tag_operator/entity_role/node_type="trash"）+ `DataAssetTable::set_filter_fn`；当前生产 filter 只接了 search/type/status（closure_data_workspace.cpp:425-451）。`DataToolbar` 已有 tag 过滤菜单壳（`set_tag_candidates`/`tag_filter_changed`/`tag_manager_requested`）。
7. **DataLineagePanel** 是 QTabWidget（版本历史/来源关系），第三页签易加；m5_data_install.cpp:74-83 把第二实例的 tab 0/1 reparent 进底签——新页签要同步。
8. **性能既有件**：12 万资产 SQL 深分页测试（metadata_scale_test.cpp，kAssetCount=120000）；1 万井×10 万链接结构性测试（entity_workspace_scale_test.cpp）。
9. **回收站语义决策**：软删**保留** entity_asset_links（JSON 不动，历史可解析，恢复即复原）；显示层（导航树/影响分析）把 trashed 资产如实标注/跳过。purge 不接自动物理删除。
10. **role 决策**：已知词汇来自 role_registry（well 9 个角色等）；schema 允许自定义（classify-never-reject）——编辑后端提供词汇下拉 + 自定义输入（非空校验），不冻结也不再造枚举。

## 3. 已排除的重复开发

- 无 open PR、无 open 治理 issue（仅 #1472/#1429 CI 类）。
- 最近 30 merged PR 无数据治理方向（#1482 是 QGIS providers 收敛读侧）。
- TagStore/trash_service/ImpactService/lineage 内核**全部已存在且有测试**——本 PR 只补内核缺口（单链接删除/角色编辑）+ 新栈服务/UI/接线/测试，不重写内核。

## 4. 风险与注意

- `ribbon_command_install.cpp` 是共享高冲突文件：只做 register_disabled → register_real 的最小替换，逻辑在新文件。
- 短生命周期 CatalogClosureAdapter 与 workflow rail 常驻 adapter 并存：sqlite WAL + 事务内 CAS 保证冲突显式失败（从不静默覆盖），UI 用户节奏下可接受；失败必须如实上屏。
- 平台已知环境型基线红（closure_science.core / ui_data_core.import_oracle / prediction.runtime 缺 onnxruntime / job_runtime.lifecycle 负载 flake）——复跑确认，勿归因本改动。
