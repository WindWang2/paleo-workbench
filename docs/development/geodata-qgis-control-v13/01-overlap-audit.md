# 01 — Overlap Audit（与 main 既有能力的重叠矩阵）

目的：§1 第一原则——发现现有能力后必须复用。本矩阵逐条对照 Goal 各 Workstream 与 main @ 40531741 现状。

图例：Existing=完整可复用（给出代码证据，本轮直接复用不开发）；Partial=部分存在（本轮补齐增量）；Missing=不存在（本轮开发）。

| Capability | 状态 | 证据（main @ 40531741） | 本轮动作 |
|---|---|---|---|
| multi-file well（一井多资产） | Existing | `EntityAssetLink` + `EntityViewService.well_view`（`catalog/entity_views.py:192`）；`tests/test_v11_multifile_well.py` 全生命周期 | 复用；不建第二实体模型 |
| compound asset / bundle | Existing | `VersionMember` + `version_members` 表 + aggregate sha（`catalog/models.py:42-81`） | 复用 |
| RAW immutability | Existing | `ImmutableVersionError` + payload 只读 + hash 永不覆盖（`catalog/storage.py:362`、`queries.py:44-91`） | 复用；补 UI 呈现（W-C 状态徽章） |
| working copy | Existing | `working_copies` 表 + service API + 状态机测试（`test_catalog_working_copy_lifecycle.py`） | 复用；补 EditSession 接线与 UI 动作 |
| DataVersion 链 / supersedes | Existing | `parent_version_ids` + children 索引 + `promote_version`（`service.py:3642-3717`） | 复用 |
| DataRun / typed lineage (ports) | Existing | `RunPort` + `set_run_ports` + lifecycle 助手（`catalog/lifecycle.py`） | 复用；补人工编辑 run（见下） |
| 人工修改 provenance | **Missing** | `EditSession.commit` 无 run（`edit_session.py:166-209`）；仅 UI data_lifecycle_controller 记 `working_copy_commit` | **本轮**：EditSession/UI 统一记 manual_edit run |
| lineage graph 查询 | Existing (bounded) | `build_lineage_chain` max_nodes=5000（`lineage_graph.py:112`） | 复用；不建第二 lineage 存储 |
| impact / stale | Existing | `ImpactService.downstream_stale/delete_impact/entity_staleness`（`impact.py`） | 复用；不存 staleness（遵守"永不回写"） |
| explain | Existing | `ExplainService.explain_version/explain_asset`（`explain.py:63`） | 复用 |
| ingest plan service | Existing | `build_ingest_plan/execute_ingest_plan`（`resources/ingest_plan.py`） | 复用；**接线** UI 与 agent（同一实现） |
| ingest plan UI | **Missing** | UI 走旧 `import_service`；plan 无调用方（grep 证） | **本轮**：W-G import planner 对话框 |
| intermediate 分类 | Partial | retention classes 仅入库版本（`service_v11.py:52-59`）；EPHEMERAL 不存在 | **本轮**：分类策略 + 收编失管产物 |
| Data Manager 框架 | Existing | DataPage/DataWorkspace/NavigationTree/PagedAssetTableModel | 复用框架；增量改造（W-F） |
| entity→role→asset→version 层级 UI | Partial | 树到 asset 叶为止；版本只在对话框 | **本轮**：版本级导航 + 井工作台动作 |
| impact/explain UI | Partial | 仅井详情"过期成果"卡；`DataDetailPanel` 死代码 | **本轮**：破坏性操作前 impact 预览 |
| lineage explorer UI | Partial | modal `LineageExplorerDialog`（lazy、bounded 已达标） | **本轮**：从选中对象直达 + map usage 节点（不大改架构） |
| QGIS layer tree 权威 | Existing | 契约三处声明 + tree transaction + diff | 复用；绝不建平行树 |
| ordering 引擎 | Existing | order keys + ROLE_BANDS + LIS 保持（`layer_order.py`） | 复用 |
| order parity 测试 | Partial | flat/fallback/layout/panel 已 pin；legend、save→reopen 全链、degraded 组模式缺 | **本轮**：补契约测试 |
| 图层↔版本绑定 | Partial | `LayerMembershipRecord.source_version_id`（仅 phase1 draft 写入） | **本轮**：W-I 绑定完善 + 双向查询 + QGIS props |
| version→map usage 反查 | **Missing** | 无任何实现 | **本轮**：usage 查询（派生自 memberships+input sets+runs） |
| stage 切换保留用户状态 | Partial | 组级 overlay 保留；层级 visibility/opacity 不入 overlay；active_layer_id 被重算覆盖 | **本轮**：修复 + 测试 |
| compilation input set | Existing | `CompilationInputSet` draft→frozen（`workflow/interpretation/compilation.py`） | 复用；纳入 usage/lineage 投影 |
| map product → OUTPUT version | Existing | `assemble_map_product`（`workflow/map_product.py:177-310`） | 复用 |
| composition 文档为 lineage 节点 | **Missing** | composition_ref 为不透明字符串 | 本轮（低优先）：登记/引用不另建权威 |
| ad-hoc 导出无 provenance | **Missing** | export_png/svg/layout 无 run/version | 本轮：导出登记 OUTPUT/INTERMEDIATE |
| harness 命令面 | Partial | 69 actions，但 ingest/reorder/working-copy/recompute/add-to-map 缺 | **本轮**：W-S 新 actions 调同一 domain 服务 |
| legacy agent/ swarm | Existing(废弃) | `agent/` stub 未路由 executor | 不投入；仅在文档标注（不动它以免破坏兼容） |
| recompute 编排 | Partial | plan/executor 在，仅 factor_map handler | **本轮**：补 prediction/fusion/map_compile handlers |
| 分页/lazy UI | Existing | 25k 阈值 SQL 分页 + 500/页实体分页 | 复用；不重写 |
| 迁移兼容 | Existing | 幂等 additive 迁移 | 复用模式；新字段 additive + UNKNOWN 默认 |

## 近期 PR 防重复清单

- PR #1290（Cartography Runtime V11）/ #1289（UX V11）：layer tree 单权威、order keys、tree transaction、UIContext——**不得重做**。
- PR #1292（拓扑 M5 retire dual-track）/ #1291（M4 checker）：编辑走原生，**不得重建 Python 拓扑**。
- PR #1301（geotopo M1-M5）/ #1302（paleo-ui M1-M5）/ #1303（vector perf）/ #1304（栈序/标注序一致性 + 渲染预设）：**顺序修复已入 main**，W-K 只补测试缺口，不照抄旧 V11 缺陷清单。
- PR #1305（CI gate 修复）：Visvalingaw 挂死与 V12 登记漂移已修。
- PR #1306-#1309（open，CI 修复）：与本 Goal 无功能重叠；本 PR 测试若触碰同簇测试需 rebase 后复验。

## 结论

Data Fabric 与 QGIS runtime 两个"半场"各自完整，本轮 Goal 的实质工作是**中间的连接组织**（binding/usage/双向导航/统一命令面）+ **失管产物收编** + **契约测试补全** + **UI 产品化（ingest plan/impact/井工作台）**。不需要任何新的权威存储；所有新能力以派生投影、additive 字段、既有 service 的新方法呈现。
