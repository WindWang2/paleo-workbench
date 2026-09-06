# Workstation UX V6 — 02 上下文模型（UIContextService）

Date: 2026-09-07 · Module: `paleo_workbench/ui/workstation/ui_context.py`

## 1. 定位：派生展示态，非第二权威

`UIContextService` **不持有任何领域状态**。每个快照字段来自注册的 provider（权威侧适配器），provider 缺席 → 诚实未知（`None`/安全默认），provider 抛异常 → 记 warning 降级未知（fail-closed）。快照不可变、按值比较，`refresh()` 只在变化时发射 `context_changed`（拆壳期迟到触发容忍 RuntimeError）。

权威 → 派生字段映射（全部只读）：

| 快照字段 | 权威 | 触发刷新的信号 |
|----------|------|----------------|
| project_open / project_name | ProjectDocument（app.py 应用点） | `_apply_project_to_shell` 显式 refresh |
| mapping_stage / mapping_stage_label | `MappingStageController.current_stage` | `current_stage_changed` |
| active_layer_id/role/editable/block_reason/editing_active | `CompositeDocument.active_editing_target_status()`（内部经 `_role_allows_editing` 单点门禁） | `active_target_changed` |
| active_well/horizon/fault/interpretation_id | `SelectionContext` 地质槽位 | `selection_changed` |
| qgis_bridge_available | `CompositeDocument.uses_native_stack` | 同上（随阶段/目标信号重派生） |
| write_granted | `AgentWorkspace.write_granted_actions`（会话 WRITE 授权集合） | `write_grant_changed` |
| running_task_count | `TaskScheduler.statuses()`，口径 = QUEUED+RUNNING（与任务中心/徽标一致） | `task_center.active_count_changed` |

## 2. 消费者

- **命令面板**（§03）：`evaluate(spec, ctx)` / `find(query, context=)` 的适用性判定源（palette 打开时实时取 `current()`）。
- **状态条工作台段**（§05 词汇 + `workbench_context_text`）：阶段 · 编辑目标（含拒绝原因）· 后端（回退可见）· 任务数。
- **测试**：provider 模型允许无 GUI 注入（`tests/test_ui_context_model.py`）。

## 3. 设计纪律（review round 2 验证通过）

- 不反写权威：service 无任何 setter 进入领域对象。
- `_freshness` 类缓存（layer_group_controller）是**整包替换的推送缓存**，project 切换经 attach_document→refresh_evaluation 重推。
- 未来新增字段必须先有消费者（Karpathy：无空想字段）；字段名与 provider 名强校验（`set_provider` KeyError）。
