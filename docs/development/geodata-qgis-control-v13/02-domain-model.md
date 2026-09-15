# 02 — Domain Model（V13 增量）

V13 不引入第二权威存储。所有新增概念要么是**既有权威上的 additive 字段**，要么是**派生只读投影**。

## 1. 实体 → 角色 → 资产 → 版本 → 物理文件（复用 V11，无改动）

- 权威：`ProjectDocument.entity_asset_links`（`project/domain.py:258`）+ 角色注册表（`project/roles.py`）。
- V13 无新增实体类型；一口井多资产、bundle（`VersionMember`）、多版本资产全部复用。

## 2. MappingLayerSourceBinding（W-I，本 Goal 核心域增量）

概念：一个编图图层钉住一个 catalog DataVersion。**权威载体是
`LayerMembershipRecord`**（`mapping_workspace/stage_state.py`），V13 起
含完整绑定语义：

| 字段 | 含义 | 缺省（旧工程） |
|---|---|---|
| `source_version_id` | 钉住的 DataVersion | ""（UNKNOWN，不伪造） |
| `source_asset_id` | 绑定资产（反查免跳查） | "" |
| `binding_kind` | `catalog_version` / `content_fingerprint` | ""（有 version 无 kind 的旧记录读取时视为 catalog_version 语义） |
| `bound_at` | 绑定时间 ISO | "" |

写入路径（唯一入口 `LayerGroupController.register_layer`）：
- phase1 建稿（`stage_actions.create_facies_draft`，已有）；
- factor 格网衍生子层（grid/contour/classification/uncertainty/QC——
  V13 补；井点输入层不 pin，它的源是井数据不是格网）；
- 融合子层 + 融合初稿（V13 补 `artifact_version_id`/`catalog_version_id`）；
- 重绑（recompute 后换钉新版本）= 再次 register_layer 覆盖。

**QGIS 侧**：绑定经 `MapLayerSnapshot.source_version_id` 走发布快照
（显示画布可见）；QGS 层对象上不加平行权威（doc_id 是唯一 join key，
不把 catalog id 写成第二个身份）。

## 3. Version → Map Usage 反查（W-M，派生投影）

`mapping_workspace/source_usage.py`：`usages_of_version/usages_of_asset`。
数据源全部是既有权威（memberships、factor_map_tasks.grid_artifact_version_id、
compilation_input_sets[].entries.pinned_version_id、map_products[].output_version_id/run_id、
catalog.runs_consuming 有界）。无新表、无缓存失效问题；
`truncated` 标志如实（run 级上限 100）。

## 4. Manual-Edit Provenance（W-E）

`catalog/lifecycle.py`：`MANUAL_EDIT_OPERATION="manual_edit"` +
`register_manual_edit_run` / `complete_manual_edit_run`。
- 输入端口角色 = 业务角色映射（tops→tops、well_log→well_logs…开放词汇透传）；
- 输出端口角色 = `manual_edit`（port_roles 新词，显示"人工修改"）；
- run 生命周期：running（预订）→ commit_working_copy(run_id) →
  set_run_ports（ports⊆flat 由单一写入核扩展）→ complete；
  零提交 → failed（不留幻影）；部分提交 → complete + failed_checkouts 参数。
- `EditSession.commit` 与 UI `new_version_from_asset` 与 harness
  `data.commit_working_copy` 三路同源。
- ghost-run 监控集合（audit + repair_ghost_runs）纳入 manual_edit。

## 5. Intermediate Policy（W-D）

`catalog/intermediate_policy.py`：写入时口径决策表
（EPHEMERAL/CACHE/INTERMEDIATE/DERIVED/OUTPUT × 必须入库/DataStage/retention）。
与 DataStage（已入库阶段）、retention_class（已入库保留策略）正交；
未知 kind 按INTERMEDIATE 兜底（宁登记勿丢失）并要求补表。
收录：渲染临时体/checkpoint=EPHEMERAL、指北针= CACHE、
factor grid/prediction 中间体=INTERMEDIATE、成图产品/QC/导出=OUTPUT。

## 6. Stage View State（W-P 修复后语义）

`StageViewState`：组级覆盖（V11）+ **图层级覆盖（V13 起 wiring）** +
`active_layer_id`（本阶段持久；切走再回**恢复**用户显式选择——
`_reassign_active_target` 先验后算；不跨阶段继承规则不变）。
用户手势入口（native 树勾选回声 / 不透明度滑条）经
`record_layer_visibility_event/record_layer_opacity_event` 落覆盖层；
程序化批量应用（stage visibility 推送、epoch 切换）不经此。
