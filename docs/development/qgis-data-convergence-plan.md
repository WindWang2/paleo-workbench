# QGIS 原生工程/数据源/数据管理收敛 — 实施计划（Prompt 3）

Baseline: `192422c60c4eb99ee78a6a410676293ca09053cc` (origin/main, 2026-09-23)
Worktree: `/home/kevin/projects/paleo-qgis-data` · Branch: `feat/qgis-native-data-management`
Build: `build/native-product`（独立目录，复用 main worktree 的 QGIS SDK/deps，`-j4`）

## 职责切分（审计结论）

| 能力 | 现状 | 目标 |
|---|---|---|
| GIS 图层/树/CRS/样式/可见性持久化 | `.paleo.json` 的 `mapping_workspace.tree` + `StageViewState` + `workstation_reference_layers` + `user_vector_layers` 内嵌 features；`QgsProject` 纯内存不落盘 | 真实 `.qgs` 文件（`QgsProject::write/read`）为唯一持久化权威；`.paleo.json` 不再双写 tree/source |
| 工程打开（GIS 部分） | openProject 按绑定逐层物化工作副本再 addVectorLayer | `QgsProject::read` 一步恢复（含 custom properties）；缺失/失效层按绑定走原物化路径兜底 |
| 数据源识别/打开 | 硬编码 `"ogr"` provider + 扩展名文件对话框 | `QgsProviderRegistry::querySublayers` 驱动；文件过滤器来自 provider metadata |
| 通用数据浏览 | 硬编码扩展名 QFileDialog | QGIS Browser dock（`QgsBrowserModel`/`QgsBrowserTreeView`，gui），双击经 querySublayers 加层 |
| domain lineage/provenance/version | catalog.sqlite + CommitCoordinator | 保留（QGIS 无等价物），作为附着在 QgsProject 会话上的 domain service |
| `map_qgis_project_xml`（schema 预留信封） | 无 C++ 写入方 | 退休：QGIS 状态以 `.qgs` 文件为权威，schema 条目删除（老文档 verbatim 透传） |
| `workstation_reference_layers` | 无 C++ 写入方（死数据源描述） | 退休：schema 条目删除；QA 读者对缺失容错 |

## 变更清单

1. **`libs/qgis` 新增 `map_project_store`**：`save(MapSession&, path)` / `load(MapSession&, path)`；`default_qgs_path(project_file)` 推导 `<stem>.qgs`。
2. **`libs/workspace`**：`MappingWorkspaceState.qgis_project_file` 字段（codec 读写）；`write_mapping_workspace` 在指针非空时不再持久化 tree（去双写）。
3. **`MainWindow::openProject`**：优先 `QgsProject::read` 恢复；恢复后 facts 从 QGIS 层 custom properties + memberships 重建；缺失绑定层走原物化循环；`applyLayerControlForOpen` 在恢复路径改为 observe（采纳运行时树）而非 reconcile（重塑）。
4. **保存流（`shell_project_actions::save_open_project`）**：提交脏编辑 → 写 `.qgs`（失败即中止，诚实报错）→ 置 `qgis_project_file` → `syncLayerControlOnSave`（tree 不再落盘）→ 三阶段文档保存。旧工程首次保存即完成迁移。
5. **Provider 归一**：`libs/qgis` 新增 `layer_factory`（querySublayers → 提案层 → 按 providerKey 建层）；`openVectorLayer/openRasterLayer` 的文件对话框过滤器改用 provider filters。
6. **Browser dock**：`apps/paleo_workbench_platform/qgis_data_workspace_install.*` 组合缝；buildUi 里 4 行挂钩（`PWB_WITH_QGIS_BROWSER`，默认 ON）。
7. **Rebind 后刷新层 custom properties**（`MainWindow::commitAllDirtyLayers`，用 `PwbDataStore::binding_for`），防 `.qgs` 持久化 stale version id。
8. **退休清单落地**：schema 删 `workstation_reference_layers`/`map_qgis_project_xml` 条目；`DataFacade` 快照改带 `qgis_project_file`、去掉 xml 信封提取；`data_store.hpp` 权威注释更新。
9. **测试**：`tests/cpp/platform/test_qgis_project_store.cpp`（roundtrip、迁移、invalid provider、rebind 刷新）+ 现有 data/platform 套件回归。
10. **文档**：本文件 + PR 表格（Removed / Retained / Temporary adapter / Future deletion）。

## 边界

- 不改 main shell/layout（Prompt 1）、layer tree/order/editing 核心（Prompt 2）；UI 入口只走新组合缝。
- `user_vector_layers`（composite/constraint authoring 的文档几何）保留为 temporary adapter：大量 QA 读者依赖文档形态，迁移条件 = composite authoring 全量走 QGIS 层 + catalog staging（另列 retirement 条件）。
- seismic volume payload store 不动。
