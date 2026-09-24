# QGIS 数据管理收敛 — 组件去向与退休计划

配套实施计划见 `qgis-data-convergence-plan.md`。Baseline `192422c60`，分支 `feat/qgis-native-data-management`。

## Removed because QGIS owns it（本 PR 删除/停用）

| 自研组件 | 去向 |
|---|---|
| `.paleo.json` 的 `mapping_workspace.tree` 完整图层树持久化（handoff 后） | 同级 `.qgs` 文件（`QgsProject::write/read`）；workspace codec 在 `qgis_project_file` 非空时写空对象，不再双写 |
| `.paleo.json` 的 `map_qgis_project_xml` 内嵌 QGIS 工程信封（schema 预留、无写入方） | schema 条目删除；老文档携带该 section 时经 unknown-key 透传无损保留 |
| `.paleo.json` 的 `workstation_reference_layers` 自研数据源描述（迁移后无写入方） | schema 条目 + `MapReferenceLayer` 模型 spec 删除；QA 读者（cartographic_qa）对缺失容错 |
| `DataFacade` 快照的 `map_qgis_project_xml` 提取 | 删除（快照不再携带 QGIS XML 副本） |
| `openVectorDialog/openRasterDialog` 手维护扩展名过滤器 | `QgsProviderMetadata::filters()`（ogr/gdal provider 自声明） |
| 文件打开的隐式 "ogr + 单层" 假设 | `QgsProviderRegistry::querySublayers` 驱动：provider 自己声明 URI 内的每个子层 |
| openProject 的"每绑定一拷贝"全量物化（handoff 项目上） | `QgsProject::read` 一步恢复；物化循环降级为缺失/失效层的兜底 |

## Retained as Paleo domain capability（保留，QGIS 无等价物）

| 组件 | 说明 |
|---|---|
| catalog.sqlite 版本/run/lineage（CatalogRepository） | 科学产物身份与血缘，QGIS 无等价物 |
| CommitCoordinator journal 两阶段提交 | RAW 不可变 + 崩溃恢复，附着在 QGIS session 上，不持有 layer 生命周期 |
| mapping_workspace memberships（asset/version 绑定、role、stage 视图） | 领域语义，通过 `pwb/*` custom properties 与 QgsMapLayer 关联 |
| `.paleo.json` 文档本身（wells/entities/workarea/…约 30 个领域 section） | 地质领域对象；QGIS project 只接管 GIS 状态 |
| seismic payload store（PWBVOL1 瓦片缓存） | QGIS 无原生体数据模型 |
| ingest/interchange 的领域解析器（LAS/WITSML/SMI/OOXML） | 非通用 GIS 格式；GeoJSON/GPKG/SHP/TIF 的识别与打开已归一 QGIS provider |

## Temporary compatibility adapter（兼容层，含退休条件）

| 适配层 | 唯一消费者 | 删除条件 |
|---|---|---|
| openProject 的 legacy 物化路径（无 `.qgs` 指针时全量拷贝工作副本） | 未迁移的老工程 | 全部存量工程完成一次保存迁移后（保存即迁移，无需显式工具）；预计 1-2 个版本后删除 |
| `MappingWorkspaceState.tree` 字段（读兼容 + 非 handoff 写） | 老文档 reconcile 路径 | 同上：迁移完成后 `from_json` 停读、字段删除 |
| `user_vector_layers` 文档几何（composite/constraint authoring 写入） | composite_controller、constraints_sync、map_qa_rules、review_qc_core、cartographic_qa | composite authoring 全量走 QGIS 层 + catalog staging；在此期间它是唯一 geometry 编辑权威之外的暂存（编辑权威已是 QgsVectorLayer edit buffer） |
| `pwb/doc_id` legacy join key 读兼容 | 老图层 | 无老项目后删除 |
| `save_document()` 文档级保存缝（不触发 .qgs 写） | m5_validation/workflow_install/closure_review 的领域 section 保存 | 这些路径不产生 GIS 状态变化，属正确行为而非缺陷；如需同步 .qgs 再评估 |

## Future deletion condition（后续方向）

- `QgsLayerTreeStack` 的 `observe→reconcile` 双向同步：`.qgs` 成为唯一结构权威后，`reconcile`（domain→runtime 塑形）仅剩系统组模板物化一个用途；待 stage-flow 组模板改为 QGIS 原生组约定后可整体退役，只剩 observe。
- `StageViewState` 的 group/layer visibility 覆盖：QGIS layer tree 自带 checked 状态持久化；待 stage 语义（per-stage 视图）确定不需要分阶段视图时可删。

## 已知行为变化（QA 读者与双轨工程）

- **cartographic_qa 的 `broken_factor_group` 规则**：该 QA 只读文档侧 `mapping_workspace.tree`；迁移后的工程 tree 为空对象，规则以 `stats.skip("workspace tree empty")` 记录跳过（不崩溃、有痕迹）。分组结构 QA 的权威应迁到 `.qgs`/运行时树侧，列入后续方向。
- **memory provider 科学产品层**：随 `.qgs` 持久化的只有 schema（QGIS 语义），重开为 0 要素的空层，openProject 恢复路径对此诚实报告（first_error），不建 domain facts、不授予写。科学产品层的持久化正道仍是 catalog publish。
- **legacy Python 双轨**：迁移后的工程若被旧 Python 应用打开，其不认识 `qgis_project_file`，GIS 树不恢复（catalog/文档数据不受影响）。本 PR 的收敛以 C++ 产品为唯一主线（Python 产品已归档），记录在此以防双轨回归。
- **`.qgs` 写入的原子性**：QGIS 4.2 的 `QgsProject::write` 是原地截断写；本实现外裹 `.pwb-bak` 两阶段（写前备份、失败恢复、成功清除）。崩溃窗口内新文件仍可能截断，此时 openProject 走 legacy 绑定物化兜底并如实报错。

