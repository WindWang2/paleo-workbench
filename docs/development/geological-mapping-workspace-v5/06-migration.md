# 06 — 持久化与旧工程迁移

## 新字段

`ProjectDocument.mapping_workspace: dict[str, Any]`（默认 `{}`）——纯 dict
载体，schema 由 `mapping_workspace.stage_state.MappingWorkspaceState` 拥有
（`schema_version: 1`）。`extra="allow"` 语义下旧版本应用打开新工程不丢段。

## 装载/保存路径

- 打开：`CompositeDocument.set_project` → `load_state(project.mapping_workspace)`
  → `attach_document`（catalog）→ 组合同步（迁移归类 + reconcile）→
  `restore_stage_view`（组显隐 + 展开态 + 编辑目标 + 就绪度评估）。
- 保存：`notify_display_changed` / `flush_edit_sessions` / `shutdown` 三路径
  均写回 `mapping_workspace` + QSettings 展开态。

## 旧工程迁移（§72/§73，保守归类）

`classify_layer_for_migration` 只依据 **machine-readable** 信号：

1. `metadata["layer_role"]`（已是 V5 工程）→ 直接路由；
2. `home_workarea:` id 前缀 → `base.reference`；
3. `metadata["reference"]` → `base.reference`；
4. `UserVectorLayer.template` 模板键（物源线/断层线/古岸线…）→ 约束/草稿角色；
5. 全部未命中 → `LEGACY_UNCLASSIFIED`（「未分类（旧工程）」组）——
   **绝不因猜测显示名改变科学语义**。

迁移发生在首次组合同步（`ensure_memberships`），结果随工程保存持久化；
feature 数/样式/顺序不受迁移影响（只加元数据，不动数据）。

## 测试

- `test_migration_*`（领域）：home_workarea/参考/模板/未知四路归类。
- `test_workspace_state_persists_and_reloads`（UI）：保存 → 新 frame 重开
  恢复阶段与角色。
- `test_project_manager_roundtrip_keeps_workspace_state`（E2E）：
  ProjectManager save/load 后 mapping_workspace 完整。
- `test_project_switch_does_not_leak_state`：工程切换无跨工程状态泄漏。
