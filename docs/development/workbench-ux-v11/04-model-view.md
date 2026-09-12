# 04 — Model/View Foundation (V11)

## 共享基础层 `paleo_workbench/ui/modelview/`

| 组件 | 作用 | 模式来源 |
|---|---|---|
| `ObjectTableModel` + `ColumnSpec` | 行为对象的虚拟表模型：列声明（取值/排序键/对齐/tooltip/前景 token/字体），`set_rows` 差分重置（同键集合只发 dataChanged），模型侧排序，`row_for_key`/`index_for_key` 稳定键查询 | composite_attribute_table `_AttributeTableModel` + paged_asset_model |
| `StableSelection` | 跨模型重置按稳定业务键存取选择 | paged_asset_model 的选择恢复 |
| `bind_table_defaults` | 统一 QTableView 行为默认（替代各页手写表格 QSS） | data_asset_table |
| `reconcile_widget_items` | QTreeWidget/QListWidget 按键差分同步：复用同键项（身份/展开/选择/滚动保持）、只对缺失键建项、失序才重排 | explorer `_reconcile_children` + correlation `_sync_well_list` |
| `AsyncQuery` | GUI 线程契约门面：epoch + latest-only + 迟到拒绝 + shutdown 即静默（见 11-performance §GUI 线程契约） | OwnedWorkerJob 单槽封装 |

## 迁移清单（01-ui-audit D2 ①-⑮）

| # | 表面 | 迁移 | 结构收益 |
|---|---|---|---|
| ① | `well_table_panel`（井点表，11 列） | ObjectTableModel + StableSelection | 100k 行零 QTableWidgetItem（此前 1.1M 项）；QC 着色经 token 前景角色 |
| ② | `map_attribute_table` feature 选择器 | 搜索框 + 有界列表（≤500 匹配）+ 计数脚注，`reconcile_widget_items` 同步可见窗口 | 不再物化 N 个 combo 串；过滤/排序不再全量重填 |
| ③ | `map_topology_issue_panel` | ObjectTableModel | 无上限问题表不建项 |
| ④ | `correlation_link_editor`（links+tops） | 双 ObjectTableModel + StableSelection | wells×markers=100k 行安全 |
| ⑤ | `catalog_health_dialog` | ObjectTableModel + PwbLoadingState/PwbEmptyState | worker 返回后 GUI 线程零建项 |
| ⑥ | `inspector_panel` 版本表 | ObjectTableModel | 选择按版本 id 保持 |
| ⑦ | `version_workbench_dialog` 时间线 | ObjectTableModel + StableSelection | 每次变更后的 reload 不再全量建项、保持选中 |
| ⑧ | `resource_table` | ObjectTableModel（删除重复表格 QSS） | 同上 |
| ⑨ | `relink_dialog` | ObjectTableModel（替换 insertRow-per-row） | 同上 |
| ⑩ | `visualization_summary_panel` | reconcile | 同键资产项身份保持 |
| ⑪ | inspector 血缘树 | 保持（服务端截断 + 异步加载，见 D1） | — |
| ⑫ | `geological_modeling_3d_page` 树/QC 列表 | 未迁移（中风险，见 12-known-limitations） | — |
| ⑬ | `tag_widgets` TagManagerDialog | 200ms 防抖 + ObjectTableModel | 搜索不再每键全量重建 |
| ⑭ | correlation 井列表 | 保持（已是增量同步——本模式来源之一） | — |
| ⑮ | `map_layer_tree` / `map_document_panel` / `map_reference_panel` | `reconcile_widget_items` | 文档切换不再 clear+rebuild；展开/选择/滚动保持 |
| — | `task_panel_base` 任务列表 | reconcile + 任务词表行渲染 | 同键任务行身份保持 |

## 保留 widget 形态的表面（分类决策，goal §8）

小而固定数据继续 widget：`qc_issue_table`（每规则一行；populate 改 `setRowCount` 批量模式）、`_VersionCompareDialog`（6 固定字段）、`sequence_boundary_table`、`new_project_wizard` 清单、`composition_panel` series 编辑、阶段面板就绪度/命令清单（固定短语表）、palette 结果、导航树（已有 500/页分页）。

## 旗舰面（不重复实现）

Data 资产表（`paged_asset_model`，≥25k 分页 SQL + LRU + epoch）、复合属性表（#1272 虚拟化）、任务中心（增量差分模型 + delegate 绘制）、explorer（键差分标准项树）、表格预览（`table_preview_widget` 虚拟化）——V11 不动其架构。

## 测试

- `tests/test_v11_modelview_data.py`（12）：100k 行结构断言（零 QTableWidgetItem、<5s、中行取值）、同键差分不重置、reconcile 身份保持、防抖单次触发、空态。
- `tests/test_v11_modelview_map.py`（13）：100k 要素有界选择器、50k tops 零建项、版本重载保选择、树 reconcile 展开/身份保持。
- `tests/test_v11_performance_structural.py`（8）：见 11-performance。
