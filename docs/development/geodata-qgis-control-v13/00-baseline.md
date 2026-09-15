# 00 — Baseline（V13 起点）

- Branch: `feat/geological-data-lineage-qgis-control-v13`
- Base: `origin/main` @ `40531741`（Merge PR #1305，2026-09-15）
- Worktree: `../paleo-workbench-geodata-qgis-v13`
- 审计时点 open PRs：#1306/#1307/#1308/#1309（全部为 CI 修复，无功能重叠）；open issue：#1230（CI nightly 分簇，P2）。

## 1. 权威地图（Source-of-Truth Map）

| 领域 | 权威 | 位置 | 备注 |
|---|---|---|---|
| 数据资产/版本/运行 | `DataCatalogService`（单 facade + `DataFabricV11Mixin`） | `paleo_workbench/catalog/service.py:264`、`service_v11.py` | SQLite WAL（`<project>.artifacts/metadata/catalog.sqlite`）为 canonical；`catalog.json` 仅 checkpoint |
| 实体/角色/绑定 | `ProjectDocument.entity_asset_links` + `project/roles.py` 角色注册表 | `paleo_workbench/project/domain.py:258-274`、`project/roles.py` | well 9 角色 / survey 7 角色 / geological 4 角色；单 primary 不变量 |
| 图层树（运行时） | **QGIS QgsProject/QgsLayerTree**（有 QGIS runtime 时） | 契约见 `mapping_workspace/layer_tree.py:1-12`、`__init__.py:9-12` | Python 侧只有 frozen `LayerTreeSnapshot`（期望/观测/持久三用途）+ `LayerMembershipRecord` 元数据 |
| 图层顺序 | lexicographic order keys + 语义带（ROLE_BANDS） | `mapping_workspace/layer_order.py` | 观测顺序→keys 的 LIS 保持（`assign_keys_for_order`）；native 事务窗口 `tree_transaction.py` |
| 舞台/工具可用性 | `MappingStageController` + `stage_profiles.py`（单一词汇表 `stage_vocabulary.py`） | `mapping_workspace/controller.py` | 3 stages；工具门控唯一真源 `mapping/tool_availability.py` |
| 编图输入集 | `CompilationInputSet`（draft→frozen，pin 版本） | `workflow/interpretation/compilation.py:26-137` | 持久于 `ProjectDocument.compilation_input_sets` |
| staleness（catalog） | `ImpactService`（永不回写版本） | `catalog/impact.py:86` | 触发=多版本资产的非 current 版本+trash 祖先 |
| staleness（mapping） | `MappingDependencyService.evaluate` | `mapping_workspace/dependencies.py:277-416` | phase1 draft / factor / integrated / mapproduct 四类 |
| Agent 命令 | `harness/registry.py` ActionRegistry（~69 actions） | `paleo_workbench/harness/` | 旧 `agent/` swarm 为 stub（`data_agent.py` 返回 `"stub": True`），未路由 HarnessExecutor |
| 算法注册表 | `workflow/interpretation/algorithm_registry.py`（V9 ADR-5） | — | `agent/registries/` 另有遗留副本 |

## 2. 既有能力清单（复用基线，不重建）

### Data Fabric V11（完整）
- 模型：`DataAsset/DataVersion/DataRun/RunPort/VersionMember`（`catalog/models.py`），stage=RAW/INTERMEDIATE/DERIVED/OUTPUT，schema v1 additive。
- RAW 不可变：`ImmutableVersionError` + payload chmod 只读（`storage.py:362-368`）+ hash 校验永不覆盖记录。
- Working copy：SQLite `working_copies` 表 + `create/commit/discard/recover_working_copy`（`service.py:2247-2502`）+ bundle 副本（`service_v11.py:463-522`）+ `EditSession`（`catalog/edit_session.py`，无生产调用方）。
- Typed lineage：`RunPort` + `set_run_ports`（ports ⊆ flat 不变量）+ `catalog/lifecycle.py` 10 个 run 注册助手（其中 stratigraphic/fault/modeling 3 个无生产接线）。
- 谱系图：`build_lineage_chain`（bounded，max_nodes=5000，cycle-safe，truncated 标志）+ `compute_summaries`。
- Impact/Explain：`downstream_stale`（direct/transitive/nearest-changed-ancestor/pinned 豁免，MAX 20k/2k）、`delete_impact`、`entity_staleness`、`explain_version/explain_asset`。
- 实体视图：`EntityViewService.well_index/well_view/survey_view`（RoleSlot/AssetSummary/missing_source/uncommitted_edits/stale_items）。
- Ingest：`resources/ingest_plan.py` `build_ingest_plan/execute_ingest_plan` 两阶段零副作用、幂等、可取消、可序列化——**无任何 UI/agent 调用方（孤儿服务）**。
- 存储：keyset 分页 `search_assets_page`、`count_assets`、lazy open + 后台 warm、CAS blob 去重、trash/restore/purge、GC（stage/working/temp/trash/blob orphan）、retention classes（cache/recomputable/retain/user）。
- 迁移：`migrate_resources` 幂等；json→sqlite 事务式。
- V11 测试：9 套 61 测试全绿（test_v11_*）。

### QGIS Cartography Runtime V11 + V12（完整）
- 单权威模型 + tree diff（LCS 最小 op 集）+ native tree transaction（begin/end + revision + stale echo 丢弃）。
- 顺序：`mirrorTreeOrderTopFirst()` 为 canvas==tree==legend==layout 唯一来源；`layoutMapLayerOrder()` 为其 bottom-first 反转；fallback 标注后置绘制（V12 #1304 修复四缺陷：镜像序反转、新层落位、fallback 标注序、mirror ledger 自愈）。
- 33 角色词汇 + ROLE_RAW_PROTECTED + 系统组注册表（order 10→950）+ 拖拽角色路由校验。
- Stage 切换：最小 diff 重建空组 + visibility（profile+user overlay 全推）+ active target 重派 + dock 推荐（首次）；`StageViewState` 每舞台覆盖层。
- 持久化：`ProjectDocument.mapping_workspace`（memberships/tree/view states）+ `map_qgis_project_xml`（真实 QgsProject::write envelope）。
- 拓扑编辑 M0-M5（V12）：DCEL 容差梯、原生编辑 v1/v2 双模、geotopo 子模块。
- 已有顺序测试：`test_layer_order_v11/parity_v11`、`test_layer_stack_order_v12`、`test_label_order_v12`。

### 工作流/提供者（大部分完整）
- Provider rail：`execute_provider` begin/complete run + 版本注册（map_export/seismic_attribute/inference）。
- DAG 引擎：canonical_hash 缓存 + receipts（含 catalog_run_id）。
- `assemble_map_product` 注册 OUTPUT version（run+inputs+fingerprint）。
- recompute：`build_recompute_plan`/`PlanExecutor`（仅 factor_map handler 接线于 `ui/workflow_controller.py:109`）。

### Data Manager UI（部分）
- `DataPage`→`DataWorkspace` 三栏；`NavigationTree` 实体优先（500/页 lazy；井文件子节点硬顶 30）；`PagedAssetTableModel` >25k SQL 分页。
- `LineageExplorerDialog`（modal、lazy 一跳展开、bounded 25/1000）；`VersionWorkbenchDialog`（元数据对比）；`WellDetailPanel`（只读角色矩阵+3 状态卡）；`InspectorPanel` 6 tab。
- 旧导入流：`import_service` + 4 个 worker（无计划确认步骤）。

### 测试基建
- 868 文件 / ~8262 测试；markers：slow/opengl/qgis/welllog_binding/timeout/capacity。
- 结构性断言风格（查询计数 pin、调用计数上限、零全表扫描）已成范式（test_v11_scale、test_v11_performance_structural、test_runtime_scale_v11）。
- 本机 Windows：主仓 `.venv`（py3.12.13）+ 已构建 bridge v0.7.0a0 + qgis-vendor runtime；worktree 通过复制 `.pyd` + `PYTHONPATH` + `PALEO_QGIS_BUILD_DIR` 复用（已验证 fast/qgis 两腿通过）。

## 3. 关键缺口（本轮 Goal 的输入，按 Workstream 归类）

1. **W-I/A 图层↔版本绑定**：仅 `LayerMembershipRecord.source_version_id` 一个字符串字段，只有 phase1 draft 一处生产写入；factor children/integrated/QC 层无 pin；QGIS 层无 catalog id 自定义属性；无反向 "version→map usages" 查询。
2. **W-E 人工编辑黑洞**：`EditSession.commit` 不建 DataRun（`run_id=None`→explain 报 not regenerable）；仅 `data_lifecycle_controller` 的 UI 路径记 `working_copy_commit` run。
3. **W-D 中间产物失管**：三类——(B) artifacts-tree 持久文件（factor grid 注册前活窗、`<artifacts>/intermediate`、`derived/attr.zarr`、workflow run store）、(C) %TEMP% 残留（`paleo-workflow-runs`、`p2-attribute-*`、north-arrow 缓存、constraint-commit mkdtemp 目录）；EPHEMERAL 分类不存在；retention classes 只覆盖已入库版本。
4. **W-G Ingest Plan UI 缺失**：服务在、UI 无、agent action 无。
5. **W-F/H impact/explain UI 面**：`DataDetailPanel.show_downstream_impact` 是死代码；删除/提升/回收前无后果预览；lineage 是 modal 孤岛。
6. **W-K 顺序契约测试缺口**：legend 内容顺序断言、group 模式 save→reopen 全链 parity、degraded（无组 fallback）与 native 组栈序 parity、native 标注序、order_key 持久 roundtrip 直测均缺。
7. **W-P 舞台状态保留缺陷**：层级 visibility/opacity echo 不写 `StageViewState`（native 勾选是组级）；`set_stage` 时 `_reassign_active_target` 覆盖用户显式选择的 `active_layer_id`（返回舞台不恢复）。
8. **W-S harness 缺 actions**：ingest.plan/execute、map.reorder_layer、map.activate_layer、data.create_working_copy/commit、data.recompute_stale、map.add_version_to_map、catalog.trace_lineage 全缺；UI 绕过 executor guard rail。
9. **W-T 规模**：lineage/impact 走全量内存文档遍历（无 SQL CTE 增量）；`entity_staleness` 调全量 `downstream_stale` 后过滤；recompute 仅 factor_map 可执行。
10. **W-§30 主动找问题清单**：见 13-review-findings.md（滚动补充）。

## 4. 明确不做（Boundary）

- 100GB 地震体架构 / GPU volume streaming / out-of-core 渲染。
- 重建第二 catalog / 第二 lineage DB / 第二 layer tree / 第二 undo / 第二项目版本系统。
- 大面积 QGIS vendor 重建（无 C++ 改动不重编；如必须改 C++ 才动 bridge）。

## 5. 环境

- Windows 11（10.0.26200）；Git Bash；主仓 `.venv` Python 3.12.13。
- fast 腿：`QT_QPA_PLATFORM=offscreen PYTHONPATH=<wt>/native/qgis_render_bridge ../paleo-workbench/.venv/Scripts/python.exe -m pytest ... -p no:cacheprovider`
- qgis 腿：追加 `PALEO_QGIS_BUILD_DIR=<main>/native/qgis_render_bridge/build/qgis-vendor`。
- 本 worktree 复制了主仓构建的 bridge `.pyd`（v0.7.0a0，2026-09-15 18:13）以满足 conftest 桥源断言；主仓有少量未提交 C++ 改动，若 qgis 腿出现可疑失败需在主仓 A/B 复跑确认非本分支回归。
