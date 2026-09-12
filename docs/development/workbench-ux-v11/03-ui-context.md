# 03 — UI Context Coordination (V11)

## 架构（复用既有三层，不建第二个权威）

```
┌─ 权威层（真实状态所有者） ────────────────────────────────────────┐
│ SelectionContext 总线（viz/selection_context.py，线程安全、源标记）  │
│ ViewCoordinationController（ui/view_coordination.py，中介/路由/守卫）│
│ UIContextService（ui/workstation/ui_context.py，只读派生快照）       │
│ OperationRegistry（ui/operations.py，V11 新增：前台操作登记）        │
└──────────────────────────────────────────────────────────────────┘
```

原则不变：UIContextSnapshot **不持有**领域状态——每个字段来自注册的 provider（权威侧适配器），缺席=诚实未知，异常=fail-closed。V11 只做两件事：扩词汇、补身份纪律。

## V11 新增总线槽位（stable IDs）

| 槽位 | 语义 | 权威发布者 | 消费者 |
|---|---|---|---|
| `selected_layer_id` | 用户在树里**点选/高亮**的层（注意力焦点） | explorer 经 `publish_layer_selection`（语义修正：不再冒充 active） | UIContext 投影、agent 快照（回退） |
| `active_layer_id` | 工具作用的**活动层**（QGIS 语义） | 编辑控制器变化 → app_shell `_publish_active_layer`（带变更守卫） | agent 快照、状态条 |
| `edit_target_layer_id` | 阶段控制器**编辑目标**（角色解析） | `active_target_changed` → `publish_edit_target` | UIContext、状态条 |
| `selected_asset_id` / `selected_version_id` | Data 页当前资产/版本（catalog 稳定 id） | DataPage `_emit_data_context` → `publish_asset_selection`（替换零订阅者的死信号） | UIContext、palette 适用性 |
| `active_survey_id` | 地震工区资源 id | `publish_survey_selection`（API 就绪，面板接线待后续） | UIContext |
| `active_task_id` | 预测/计算任务 id | `publish_task_selection`（API 就绪） | UIContext |
| `workflow_stage` | MappingStage.value | `current_stage_changed` → `publish_stage` | UIContext（与 mapping_stage 同源） |

**三个层概念禁止混写**：`selected != active != edit target`（01-ui-audit C3 的根因就是 explorer 把「点选」写进「活动层」槽位）。

## 井身份规范化（C1 修复）

总线跨视图井键 = 井**名**（#1029 既有约定，坐标 hub 全量依赖）。但 Data 井位图/3D fence 路径发布实体 **id** → 名字键消费者静默失配。

V11：`ViewCoordinationController` 维护 name↔id 双向索引（`bind_project` 全量重建、`clear_project` 清空）；`publish_well_selection` 接受任意标识，规范化为规范名发布，并把实体 id 附加在 `custom_attributes["well_entity_id"]`。未知标识按原值发布（不吞选择）。`resolve_well_key(value) -> (name, entity_id)` 是公开查询口。

## 生命周期纪律

| 风险 | V11 处置 |
|---|---|
| 非幂等 attach（K2） | `WorkstationFrame.attach_coordination` 断旧连新（标志位防重复断开告警） |
| 页面销毁后 singleton 回调 | AsyncQuery/OperationRegistry 全部 parent 到宿主 QObject；shell 重建即 `bind_registry_to_shell` 换新实例（旧记录与 jump 回调随之消亡） |
| 工程关闭残留 | registry 随 shell 销毁；`AsyncQuery.shutdown` 在 DataPage `shutdown_workers` 统一调用；血缘缓存随清 |
| 反馈循环 | 发布层不变（source 标记 + changed-only 路由 + 重复守卫）；`_publish_active_layer` 带值守卫防 state_changed 高频重发 |

## 会话级残留（已知边界，见 12-known-limitations）

进程级 `get_scheduler()` 与模块级 `command_registry` 跨工程存活——前者归 Data Fabric owner（goal §22 边界），后者 replace 语义已足够安全（无 shell 私有回调残留）。

## 测试

- `tests/test_selection_context.py`（扩展槽位覆盖）
- `tests/test_v11_performance_structural.py`：重复发布守卫（同 (well,source) 二次发布 → 恰 1 次发射）
- `tests/test_view_coordination_wiring.py`：全部通过（井名规范化不破坏既有路由）
